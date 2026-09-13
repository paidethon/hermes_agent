#!/usr/bin/python3
"""Fail-closed, idempotent initialization for a single-user ModelScope desktop.

Authentication is delegated to Authelia; this module does not implement login.
Never import or delete the legacy /mnt/workspace/zephyr tree automatically.
"""
from __future__ import annotations

import html
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
from urllib.parse import urlsplit

import yaml
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError
try:  # argon2-cffi >= 23.1 renamed InvalidHash to InvalidHashError.
    from argon2.exceptions import InvalidHashError
except ImportError:  # Ubuntu 24.04 ships 21.1 with the old name.
    from argon2.exceptions import InvalidHash as InvalidHashError

APP_UID = APP_GID = 1001
AUTH_UID = AUTH_GID = 1002
RUN = Path('/run/zephyr')


def validate_origin(value: str) -> tuple[str, str, str]:
    """Only an explicitly configured HTTPS origin is trusted, never Host/XFF."""
    parsed = urlsplit(value)
    if parsed.scheme != 'https' or not parsed.hostname:
        raise ValueError('PUBLIC_ORIGIN must be an HTTPS origin with a DNS hostname')
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('PUBLIC_ORIGIN must not contain credentials, a query, or a fragment')
    if parsed.path not in ('', '/'):
        raise ValueError('PUBLIC_ORIGIN must not contain an application path')
    host = parsed.hostname.lower()
    if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?', host) or '.' not in host:
        raise ValueError('PUBLIC_ORIGIN needs a full ASCII DNS hostname')
    for label in host.split('.'):
        if not label or len(label) > 63 or label.startswith('-') or label.endswith('-'):
            raise ValueError('Invalid PUBLIC_ORIGIN hostname')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Use a DNS name, not an IP address, for the authentication cookie')
    port = parsed.port
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('Invalid origin port')
    authority = host + (f':{port}' if port and port != 443 else '')
    return f'https://{authority}', host, authority


def validate_data_root(value: str) -> Path:
    if not re.fullmatch(r'/mnt/workspace/[A-Za-z0-9][A-Za-z0-9_-]*', value):
        raise ValueError('DATA_ROOT must be one named directory directly under /mnt/workspace')
    if value == '/mnt/workspace/zephyr':
        raise ValueError('Do not initialize over the legacy zephyr directory; migrate explicitly')
    path = Path(value)
    if path.is_symlink() or path.resolve().parent != Path('/mnt/workspace').resolve():
        raise ValueError('DATA_ROOT must not escape the persistent workspace through a symlink')
    return path


def directory(path: Path, uid: int, gid: int, mode: int) -> None:
    if path.is_symlink():
        raise ValueError(f'Refusing symlink for managed directory: {path}')
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, uid, gid)
    os.chmod(path, mode)


def atomic_write(path: Path, text: str | bytes, uid: int, gid: int, mode: int = 0o600) -> None:
    if path.is_symlink():
        raise ValueError(f'Refusing symlink for managed file: {path}')
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    try:
        with temporary.open('xb') as handle:
            handle.write(text.encode() if isinstance(text, str) else text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, uid, gid)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def render_authelia(root: Path, origin: str, host: str, keys: dict[str, str]) -> str:
    config = {
        'server': {'address': 'tcp://127.0.0.1:9091/auth'},
        'log': {'level': 'info', 'format': 'json'},
        'authentication_backend': {
            'password_reset': {'disable': True},
            'password_change': {'disable': True},
            'file': {'path': str(root / 'auth/users.yml')},
        },
        'access_control': {
            'default_policy': 'deny',
            'rules': [{'domain': host, 'policy': 'one_factor'}],
        },
        'session': {
            'secret': keys['session'], 'name': 'zephyr_session',
            # ModelScope presents the app inside a cross-site iframe, so the
            # session cookie must be SameSite=None (always Secure here).
            'same_site': 'none',
            'inactivity': '30m', 'expiration': '12h', 'remember_me': '0',
            'cookies': [{'domain': host, 'authelia_url': origin + '/auth/',
                         'default_redirection_url': origin + '/'}],
        },
        'storage': {'encryption_key': keys['storage'],
                    'local': {'path': str(root / 'auth/db.sqlite3')}},
        'notifier': {'filesystem': {'filename': str(root / 'auth/notifications.txt')}},
        'ntp': {'disable_startup_check': True},
    }
    return yaml.safe_dump(config, sort_keys=False)


def render_nginx(origin: str, host: str, authority: str, runtime: str = '/run/zephyr',
                 port: int = 7860, auth_port: int = 9091, desktop_port: int = 6080,
                 health_port: int = 9092, worker_user: str = 'www-data') -> str:
    # Values come from validation, not user-supplied request headers.
    # ModelScope only exposes the app through its own iframe, so framing is
    # restricted to ModelScope origins instead of denied outright.
    frame_csp = ("Content-Security-Policy \"frame-ancestors 'self' "
                 "https://www.modelscope.cn https://modelscope.cn\" always;")
    protected = f'''auth_request /internal/authelia/authz;
            auth_request_set $auth_cookie $upstream_http_set_cookie;
            add_header Set-Cookie $auth_cookie always;
            add_header {frame_csp}
            add_header X-Content-Type-Options nosniff always;
            add_header Referrer-Policy no-referrer always;
            error_page 401 = @login;'''
    forwarded = f'''proxy_set_header Host {authority};
            proxy_set_header X-Forwarded-Host {authority};
            proxy_set_header X-Forwarded-Proto https;
            proxy_set_header X-Forwarded-Ssl on;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header Authorization "";
            proxy_set_header Proxy-Authorization "";'''
    return f'''user {worker_user};
worker_processes auto;
pid {runtime}/nginx.pid;
error_log stderr warn;
events {{ worker_connections 1024; }}
http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server_tokens off;
    log_format safe '$remote_addr $request_method $uri $status';
    access_log /dev/stdout safe;
    sendfile on;
    keepalive_timeout 65;
    client_max_body_size 1m;
    client_body_temp_path {runtime}/client_body;
    proxy_temp_path {runtime}/proxy;
    fastcgi_temp_path {runtime}/fastcgi;
    uwsgi_temp_path {runtime}/uwsgi;
    scgi_temp_path {runtime}/scgi;
    proxy_connect_timeout 5s;
    proxy_read_timeout 60s;
    map $http_upgrade $connection_upgrade {{ default upgrade; '' close; }}
    map $http_origin $ws_origin_ok {{ default 0; "{origin}" 1; }}
    server {{
        listen 0.0.0.0:{port} default_server;
        server_name {host};
        absolute_redirect off;
        add_header {frame_csp}
        add_header X-Content-Type-Options nosniff always;
        add_header Referrer-Policy no-referrer always;
        location = /healthz {{ access_log off; default_type text/plain; return 200 'alive\\n'; }}
        location = /readyz {{
            access_log off;
            proxy_pass http://127.0.0.1:{health_port}/readyz;
            proxy_connect_timeout 1s;
            proxy_read_timeout 7s;
        }}
        location = /internal/authelia/authz {{
            internal;
            proxy_pass http://127.0.0.1:{auth_port}/auth/api/authz/auth-request;
            proxy_pass_request_body off;
            proxy_set_header Content-Length "";
            proxy_set_header Connection "";
            proxy_set_header X-Original-Method $request_method;
            proxy_set_header X-Original-URL {origin}$request_uri;
            {forwarded}
            proxy_http_version 1.1;
            proxy_buffer_size 16k;
            proxy_buffers 4 16k;
        }}
        location @login {{ return 302 {origin}/auth/; }}
        location = /auth {{ return 302 {origin}/auth/; }}
        location ^~ /auth/ {{
            proxy_pass http://127.0.0.1:{auth_port};
            {forwarded}
            proxy_set_header X-Forwarded-URI $request_uri;
            proxy_http_version 1.1;
            proxy_buffer_size 16k;
            proxy_buffers 4 16k;
            # Authelia ships its own deny-framing headers; replace them so the
            # portal is frameable only from ModelScope, like the rest of the app.
            proxy_hide_header X-Frame-Options;
            proxy_hide_header Content-Security-Policy;
            add_header {frame_csp}
            add_header X-Content-Type-Options nosniff always;
        }}
        location = / {{
            {protected}
            root {runtime}/www;
            try_files /index.html =404;
        }}
        location = /desktop {{ return 302 /desktop/vnc.html?autoconnect=1&resize=remote&path=desktop/websockify; }}
        location = /desktop/websockify {{
            if ($ws_origin_ok = 0) {{ return 403; }}
            {protected}
            proxy_pass http://127.0.0.1:{desktop_port}/websockify;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection $connection_upgrade;
            proxy_set_header Host 127.0.0.1;
            proxy_set_header Authorization "";
            proxy_buffering off;
            proxy_read_timeout 3600s;
            proxy_send_timeout 3600s;
        }}
        location /desktop/ {{
            {protected}
            proxy_pass http://127.0.0.1:{desktop_port}/;
            proxy_http_version 1.1;
            proxy_set_header Host 127.0.0.1;
            proxy_set_header Authorization "";
        }}
        location / {{ return 404; }}
    }}
}}
'''


def render_supervisor(root: Path, geometry: str, no_sandbox: str) -> str:
    env = (f'HOME="/home/hermes",USER="hermes",LOGNAME="hermes",DISPLAY=":1",'
           f'XAUTHORITY="/run/user/1001/.Xauthority",XDG_RUNTIME_DIR="/run/user/1001",'
           f'XDG_SESSION_TYPE="x11",LIBGL_ALWAYS_SOFTWARE="1",QT_X11_NO_MITSHM="1",'
           f'KWIN_COMPOSE="N",DATA_ROOT="{root}",CHROME_NO_SANDBOX="{no_sandbox}",'
           f'HERMES_HOME="{root}/hermes",QT_IM_MODULE="fcitx",GTK_IM_MODULE="fcitx",'
           f'XMODIFIERS="@im=fcitx"')
    programs = [
        ('dbus', 'root', '/usr/bin/dbus-daemon --system --nofork --nopidfile', 5),
        ('auth', 'zephyr-auth', '/usr/local/bin/authelia --config /run/zephyr/authelia.yml', 10),
        ('vnc', 'hermes', '/usr/bin/Xtigervnc :1 -localhost=1 -rfbport 5901 '
         f'-geometry {geometry} -depth 24 -SecurityTypes VncAuth '
         '-rfbauth /home/hermes/.vnc/passwd -auth /run/user/1001/.Xauthority -nolisten tcp', 20),
        ('desktop', 'hermes', '/opt/recovery/desktop.sh', 30),
        ('novnc', 'hermes', '/usr/bin/websockify --web=/usr/share/novnc 127.0.0.1:6080 127.0.0.1:5901', 40),
        ('studio', 'hermes', '/opt/recovery/studio.sh', 50),
        ('health', 'hermes', '/usr/bin/python3 /opt/recovery/health.py', 60),
        ('nginx', 'root', '/usr/sbin/nginx -g "daemon off;" -c /run/zephyr/nginx.conf', 70),
    ]
    text = '''[unix_http_server]
file=/run/zephyr/supervisor.sock
chmod=0700

[supervisord]
nodaemon=true
user=root
logfile=/dev/null
logfile_maxbytes=0
pidfile=/run/zephyr/supervisord.pid
childlogdir=/var/log/supervisor

[rpcinterface:supervisor]
supervisor.rpcinterface_factory=supervisor.rpcinterface:make_main_rpcinterface

[supervisorctl]
serverurl=unix:///run/zephyr/supervisor.sock
'''
    for name, user, command, priority in programs:
        text += f'''
[program:{name}]
command={command}
user={user}
directory={"/home/hermes" if user == "hermes" else "/"}
environment={env}
priority={priority}
autostart=true
autorestart=true
startsecs=3
startretries=5
stopwaitsecs=20
stopasgroup=true
killasgroup=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
'''
    return text


def initialize_auth(root: Path, username: str, password: str) -> None:
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,31}', username):
        raise ValueError('AUTH_USERNAME must be a lowercase identifier of 1 to 32 characters')
    path = root / 'auth/users.yml'
    users = yaml.safe_load(path.read_text()) if path.exists() else {'users': {}}
    if password:
        if len(password) < 16 or len(password) > 256 or any(ord(c) < 32 for c in password):
            raise ValueError('AUTH_PASSWORD must have 16-256 characters and no control characters')
        hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)
        old = users.get('users', {}).get(username, {}).get('password', '')
        valid = False
        try:
            valid = bool(old) and hasher.verify(old, password)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        if not valid:
            users = {'users': {username: {'displayname': username,
                     'password': hasher.hash(password), 'email': username + '@example.invalid',
                     'groups': ['owners']}}}
            atomic_write(path, yaml.safe_dump(users), AUTH_UID, AUTH_GID)
    elif username not in users.get('users', {}):
        raise ValueError('AUTH_PASSWORD is required on first boot or when changing the username')
    os.chown(path, AUTH_UID, AUTH_GID)
    os.chmod(path, 0o600)


def initialize_home(root: Path) -> None:
    home = root / 'home'
    new_home = not home.exists()
    directory(home, APP_UID, APP_GID, 0o700)
    if new_home:
        shutil.copytree('/opt/home-seed', home, dirs_exist_ok=True)
        for item in home.rglob('*'):
            if not item.is_symlink():
                os.chown(item, APP_UID, APP_GID)
    target = Path('/home/hermes')
    if target.is_symlink():
        if target.resolve() != home.resolve():
            raise ValueError('/home/hermes points to a different data directory')
    elif target.exists():
        # Preserve the immutable image's initial home; never recursively delete it.
        seed_backup = Path('/home/hermes.image-seed')
        if seed_backup.exists():
            raise ValueError('Unexpected non-symlink home: refusing to overwrite it')
        target.rename(seed_backup)
        target.symlink_to(home, target_is_directory=True)
    else:
        target.symlink_to(home, target_is_directory=True)
    for child in ('Desktop', '.vnc', '.config', '.local'):
        directory(home / child, APP_UID, APP_GID, 0o700)
    hidden = home / '.hermes'
    if hidden.is_symlink():
        if hidden.resolve() != (root / 'hermes').resolve():
            raise ValueError('Unexpected .hermes symlink; inspect it before proceeding')
    elif hidden.exists():
        raise ValueError('Unexpected .hermes directory; migration must be explicit')
    else:
        hidden.symlink_to(root / 'hermes', target_is_directory=True)
        os.lchown(hidden, APP_UID, APP_GID)
    bashrc = home / '.bashrc'
    old = bashrc.read_text() if bashrc.exists() else ''
    marker = 'source /opt/recovery/session-env.sh'
    if marker not in old:
        atomic_write(bashrc, old + '\n' + marker + '\n', APP_UID, APP_GID)
    for name, contents in {
        'Hermes-Studio.desktop': '[Desktop Entry]\nType=Application\nName=Hermes Studio\n'
                                'Exec=/usr/local/bin/zephyr-browser\nIcon=web-browser\nTerminal=false\n',
        'Hermes-Terminal.desktop': '[Desktop Entry]\nType=Application\nName=Hermes Terminal\n'
                                  'Exec=konsole\nIcon=utilities-terminal\nTerminal=false\n',
    }.items():
        if not (home / 'Desktop' / name).exists():
            atomic_write(home / 'Desktop' / name, contents, APP_UID, APP_GID, 0o700)
    # The workspace mount is a network filesystem where xauth lock files time out.
    # The cookie is regenerated on every boot, so keep it on local tmpfs instead.
    xauthority = Path('/run/user/1001/.Xauthority')
    atomic_write(xauthority, b'', APP_UID, APP_GID)
    # Cookie is not a bearer credential for the public web application.
    # Ubuntu 24.04 ships gosu in /usr/sbin, Debian older releases in /usr/bin.
    gosu = shutil.which('gosu')
    if not gosu:
        raise OSError('gosu binary is required but was not found in PATH')
    subprocess.run([gosu, 'hermes', '/usr/bin/xauth', '-f', str(xauthority),
                    'add', ':1', '.', secrets.token_hex(16)], check=True)
    initialize_vnc_password(home, os.environ.get('VNC_PASSWORD', ''))


def initialize_vnc_password(home: Path, password: str) -> None:
    vnc_file = home / '.vnc/passwd'
    if not password:
        if not vnc_file.exists():
            raise ValueError('VNC_PASSWORD is required on first boot')
        return
    if not 8 <= len(password) <= 64 or not all(33 <= ord(c) <= 126 for c in password):
        raise ValueError('VNC_PASSWORD must be 8-64 printable ASCII characters')
    # The VNC challenge-response protocol derives its key from only the first
    # 8 characters; every client truncates the same way.
    result = subprocess.run(['/usr/bin/tigervncpasswd', '-f'],
                            input=(password[:8] + '\n').encode(), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True)
    atomic_write(vnc_file, result.stdout, APP_UID, APP_GID)


def initialize_desktop_auth() -> None:
    password = os.environ.get('DESKTOP_PASSWORD', '')
    if not 8 <= len(password) <= 256 or any(ord(c) < 32 for c in password):
        raise ValueError('DESKTOP_PASSWORD must be 8-256 characters without control characters')
    # The KDE lock screen authenticates the hermes account against /etc/shadow,
    # which lives in the ephemeral container layer; re-apply on every boot.
    subprocess.run(['/usr/sbin/chpasswd'], input=f'hermes:{password}\n'.encode(), check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def initialize_model(root: Path) -> None:
    config_file = root / 'hermes/config.yaml'
    model = os.environ.get('HERMES_MODEL', '').strip()
    base_url = os.environ.get('OPENAI_BASE_URL', '').strip()
    if not config_file.exists() and model and base_url:
        parsed = urlsplit(base_url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Cloud OPENAI_BASE_URL must be HTTPS and must not include credentials')
        cfg = {'model': {'default': model, 'provider': 'custom', 'base_url': base_url}}
        atomic_write(config_file, yaml.safe_dump(cfg), APP_UID, APP_GID)
    # API keys remain injected environment secrets, never copied into the image or YAML.
    if not config_file.exists():
        print('Model is not configured: run `hermes model` in the desktop terminal.', flush=True)


def main() -> None:
    origin, host, authority = validate_origin(os.environ.get('PUBLIC_ORIGIN', ''))
    root = validate_data_root(os.environ.get('DATA_ROOT', '/mnt/workspace/zephyr-v2'))
    geometry = os.environ.get('DESKTOP_GEOMETRY', '1280x800')
    if not re.fullmatch(r'[1-9][0-9]{2,3}x[1-9][0-9]{2,3}', geometry):
        raise ValueError('DESKTOP_GEOMETRY must look like 1280x800')
    no_sandbox = os.environ.get('CHROME_NO_SANDBOX', '0')
    if no_sandbox not in ('0', '1'):
        raise ValueError('CHROME_NO_SANDBOX must be 0 or 1')
    directory(root, 0, 0, 0o755)
    for child in ('home', 'hermes', 'studio', 'work'):
        if child != 'home':
            directory(root / child, APP_UID, APP_GID, 0o700)
    directory(root / 'auth', AUTH_UID, AUTH_GID, 0o700)
    directory(RUN, 0, 0, 0o755)
    directory(RUN / 'www', 0, 0, 0o755)
    directory(Path('/run/user/1001'), APP_UID, APP_GID, 0o700)
    directory(Path('/tmp/.X11-unix'), 0, 0, 0o1777)
    initialize_auth(root, os.environ.get('AUTH_USERNAME', 'zephyr'), os.environ.get('AUTH_PASSWORD', ''))
    keys_file = root / 'auth/keys.json'
    if keys_file.exists():
        keys = json.loads(keys_file.read_text())
    else:
        keys = {name: secrets.token_hex(32) for name in ('session', 'storage')}
        atomic_write(keys_file, json.dumps(keys), AUTH_UID, AUTH_GID)
    initialize_home(root)
    initialize_desktop_auth()
    initialize_model(root)
    atomic_write(RUN / 'authelia.yml', render_authelia(root, origin, host, keys), AUTH_UID, AUTH_GID)
    atomic_write(RUN / 'nginx.conf', render_nginx(origin, host, authority), 0, 0, 0o644)
    atomic_write(RUN / 'supervisord.conf', render_supervisor(root, geometry, no_sandbox), 0, 0, 0o600)
    page = f'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Hermes Desktop</title><body><main><h1>Hermes Desktop</h1>
<p>Authenticated entry at {html.escape(origin)}.</p>
<p><a href="/desktop/vnc.html?autoconnect=1&amp;resize=remote&amp;path=desktop/websockify">Open KDE desktop</a></p>
<p>In the desktop browser, open <code>http://127.0.0.1:8648</code> for Hermes Studio.</p>
<p>The VNC password is separate from the web sign-in password. This is not multi-factor authentication.</p>
<p><a href="/auth/">Account / sign out</a></p></main></body></html>'''
    atomic_write(RUN / 'www/index.html', page, 0, 0, 0o644)
    subprocess.run(['/usr/bin/dbus-uuidgen', '--ensure'], check=True)
    print('Recovery configuration generated; no legacy data has been changed.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        # Do not print environment values, supplied passwords, or API error bodies.
        raise SystemExit(f'Initialization failed: {type(exc).__name__}: {exc}')
