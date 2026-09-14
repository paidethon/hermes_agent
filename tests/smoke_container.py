#!/usr/bin/env python3
"""Integration gate for a REAL built image. Executed by GitHub Actions, not locally here.

No paid LLM request is made. Tests actual Authelia login, noVNC assets, WebSocket
handshake, CLI imports, restart persistence, and — at X11 protocol level — that
the window manager is installed, running, and actually managing windows.
Fails rather than publishing on error.
"""
from __future__ import annotations
import base64
import hashlib
import http.client
import json
import os
import secrets
import socket
import subprocess
import sys
import time
from http.cookies import SimpleCookie

IMAGE = os.environ.get('TEST_IMAGE', 'hermes-recovery:test')
NAME = 'hermes-recovery-test-' + secrets.token_hex(4)
ORIGIN = 'https://zephyr.test'
PASSWORD = secrets.token_urlsafe(24)
VNC_PASSWORD = secrets.token_hex(4)
DESKTOP_PASSWORD = secrets.token_urlsafe(24)
FAKE_AGENT_KEY = 'sk-ci-fake-key-not-a-real-secret'
PORT = 17860

# The X probes run as the desktop user with the session environment the
# supervisor renders; never rely on the caller's ambient environment.
XENV = ('-u', 'hermes', '-e', 'DISPLAY=:1', '-e', 'XAUTHORITY=/run/user/1001/.Xauthority')
# Capabilities a desktop user depends on for maximize/minimize/close/move.
WM_REQUIRED_ATOMS = ('_NET_WM_STATE', '_NET_WM_STATE_MAXIMIZED_VERT',
                     '_NET_WM_STATE_MAXIMIZED_HORZ', '_NET_CLOSE_WINDOW',
                     '_NET_MOVERESIZE_WINDOW')
# A real X client probe: xterm via Xft (fonts-noto-cjk is in the image), so
# the check needs no extra packages and no screenshot pipeline.
MANAGED_WINDOW_PROBE = r'''
set -e
xterm -fa monospace -fs 12 -geometry 80x24+20+20 >/dev/null 2>&1 &
xpid=$!
trap 'kill $xpid 2>/dev/null || true' EXIT
sleep 3
clients=$(xprop -root _NET_CLIENT_LIST | sed 's/.*window id # //')
echo "CLIENTS=$clients"
test -n "$clients"
wid=
for w in $clients; do
    w=${w%,}
    if xprop -id "$w" WM_CLASS 2>/dev/null | grep -q xterm; then wid=$w; break; fi
done
test -n "$wid" || { echo 'xterm window not found in client list'; exit 1; }
extents=$(xprop -id "$wid" _NET_FRAME_EXTENTS)
echo "FRAME=$extents"
frame=$(echo "$extents" | sed 's/.*= //')
test "$frame" != "0, 0, 0, 0"
'''


def docker(*args: str, check: bool = True, **kwargs):
    return subprocess.run(['docker', *args], check=check, text=True, **kwargs)


def exec_out(*args: str, check: bool = True) -> str:
    return docker('exec', *args, check=check, stdout=subprocess.PIPE).stdout


def get(path: str, cookie: str = '', method: str = 'GET', payload=None):
    connection = http.client.HTTPConnection('127.0.0.1', PORT, timeout=10)
    headers = {'Host': 'zephyr.test', 'Origin': ORIGIN}
    if cookie:
        headers['Cookie'] = cookie
    body = None
    if payload is not None:
        headers['Content-Type'] = 'application/json'
        body = json.dumps(payload)
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    status, out_headers, content = response.status, response.getheaders(), response.read()
    connection.close()
    return status, out_headers, content


def await_ready():
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        try:
            if get('/readyz')[0] == 200:
                return
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(3)
    # Log availability only; do not dump application logs or environment secrets to CI.
    docker('exec', NAME, '/usr/bin/python3', '/opt/recovery/health.py', '--once', check=False)
    docker('exec', NAME, '/usr/bin/supervisorctl', '-c', '/run/zephyr/supervisord.conf', 'status', check=False)
    # Keep the first boot failure diagnosable: the boot path prints no secrets.
    docker('logs', '--tail', '150', NAME, check=False)
    state = subprocess.run(['docker', 'inspect', '--format',
        'container state: status={{.State.Status}} exitcode={{.State.ExitCode}} '
        'oom={{.State.OOMKilled}} error={{.State.Error}}', NAME],
        check=False, text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    print(state.stdout, flush=True)
    raise RuntimeError('Actual image readiness failed; publishing is blocked')


def verify_window_manager(stage: str) -> None:
    """Protocol-level proof the desktop is manageable (2026-09 regression).

    "plasmashell is running" once passed every gate while the image shipped
    without a window manager at all. Gate on: binary exists, process owned by
    the desktop user, and an EWMH window manager actually owns the root window
    of :1 with the atoms maximize/close/move depend on.
    """
    docker('exec', NAME, 'test', '-x', '/usr/bin/kwin_x11')
    docker('exec', NAME, '/usr/bin/pgrep', '-u', '1001', '-x', 'kwin_x11',
           stdout=subprocess.DEVNULL)
    docker('exec', *XENV, NAME, '/usr/bin/xdpyinfo', stdout=subprocess.DEVNULL)
    ownership = exec_out(*XENV, NAME, '/usr/bin/xprop', '-root', '_NET_SUPPORTING_WM_CHECK')
    assert 'window id' in ownership, \
        f'[{stage}] No EWMH window manager owns the X11 root window of :1'
    supported = exec_out(*XENV, NAME, '/usr/bin/xprop', '-root', '_NET_SUPPORTED')
    missing = [atom for atom in WM_REQUIRED_ATOMS if atom not in supported]
    assert not missing, f'[{stage}] Window manager lacks required EWMH atoms: {missing}'


def verify_managed_window(stage: str) -> None:
    """A spawned X client must be listed as managed AND carry a WM frame.

    A frame with non-zero extents is the protocol-level witness of a title
    bar: without the window manager, windows appear in no client list and
    carry no frame.
    """
    result = docker('exec', *XENV, NAME, '/bin/bash', '-c', MANAGED_WINDOW_PROBE,
                    check=False, stdout=subprocess.PIPE)
    output = (result.stdout or '').strip()
    print(f'[{stage}] managed-window probe: {output or "(no output)"}', flush=True)
    assert result.returncode == 0, \
        f'[{stage}] X client window is not managed/framed by the window manager'


def verify_lock_does_not_kill_kwin() -> None:
    """Regression: locking the screen must not take the window manager down.

    Locks via the session bus, requires the greeter to appear, then unlocks
    by terminating the greeter (no VNC input driver needed in CI) and
    requires kwin_x11 to still own :1 afterwards.
    """
    # Read the session bus address as the desktop user: reading another
    # uid's /proc/*/environ needs CAP_SYS_PTRACE, which default docker
    # caps omit, so root's read came back empty.
    bus = exec_out(*XENV, NAME, '/bin/sh', '-c',
                   'for pid in $(pgrep -u 1001); do '
                   "a=$(tr '\\0' '\\n' < /proc/$pid/environ 2>/dev/null"
                   " | sed -n 's/^DBUS_SESSION_BUS_ADDRESS=//p' | head -n1); "
                   '[ -n "$a" ] && { printf %s "$a"; break; }; done').strip()
    assert bus.startswith('unix:'), 'Plasma session bus address not found'
    # dbus-send rejects --session combined with an explicit address; --bus
    # alone targets the session bus we just discovered.
    docker('exec', *XENV, NAME, '/usr/bin/dbus-send', '--print-reply',
           f'--bus={bus}', '--dest=org.freedesktop.ScreenSaver',
           '/ScreenSaver', 'org.freedesktop.ScreenSaver.Lock')
    time.sleep(5)
    greeter = exec_out(NAME, '/usr/bin/pgrep', '-u', '1001', '-f', 'kscreenlocker_greet').strip()
    assert greeter, 'Lock screen greeter did not start'
    docker('exec', NAME, '/usr/bin/pgrep', '-u', '1001', '-x', 'kwin_x11',
           stdout=subprocess.DEVNULL)
    docker('exec', NAME, '/usr/bin/pkill', '-u', '1001', '-f', 'kscreenlocker_greet')
    time.sleep(5)
    docker('exec', NAME, '/usr/bin/pgrep', '-u', '1001', '-x', 'kwin_x11',
           stdout=subprocess.DEVNULL)
    verify_window_manager('after lock/unlock')


def verify_liveness_readiness_distinction() -> None:
    """liveness (/healthz) answers 'is the entrypoint alive'; readiness
    (/readyz) answers 'is a user actually served'. They must stay distinct."""
    status, headers, body = get('/healthz')
    assert status == 200 and body == b'alive\n', \
        f'/healthz must be an unauthenticated liveness answer, got {status} {body!r}'
    status, _, body = get('/readyz')
    assert status == 200, '/readyz must be 200 once ready'
    payload = json.loads(body)
    assert payload['ready'] is True and all(payload['checks'].values()), \
        f'/readyz body must carry the per-probe aggregation: {payload}'
    assert set(payload['versions']) == {'app', 'hermes', 'studio'}, \
        '/readyz must publish the pinned upstream commit ids'
    # Unauthenticated access to the protected root redirects to the portal.
    status, headers, _ = get('/')
    location = next((v for k, v in headers if k.lower() == 'location'), '')
    assert status == 302 and location.endswith('/auth/'), \
        f'unauthenticated / must redirect to the portal, got {status} -> {location}'


def verify_env_isolation() -> None:
    """Per-service allowlist in the real container: the fake model key must be
    present (with value) ONLY in the agent consumers, blanked everywhere else.

    Other-uid environments are read as that uid: default docker caps omit
    CAP_SYS_PTRACE, so root cannot read uid-1001 /proc/*/environ here.
    """
    fake = 'sk-ci-fake-key-not-a-real-secret'

    def environ_of(user: str, pattern: str) -> str:
        result = docker('exec', NAME, '/usr/sbin/gosu', user, '/bin/sh', '-c',
                        f"tr '\\0' '\\n' < /proc/$(pgrep -u 1001 {pattern} | head -n1)/environ "
                        '|| true', check=False, stdout=subprocess.PIPE).stdout
        return result or ''

    for program, pattern in (('studio', '-f "node dist/server/index.js"'),
                             ('plasmashell', '-x plasmashell')):
        env = environ_of('hermes', pattern)
        assert f'OPENAI_API_KEY={fake}' in env, \
            f'{program} must receive the agent key'
    for program, pattern in (('novnc/websockify', '-f websockify'),
                             ('health', '-f "health.py"'),
                             ('vnc', '-x Xtigervnc')):
        env = environ_of('hermes', pattern)
        assert fake not in env, f'{program} must not carry the agent key value'
        assert 'OPENAI_API_KEY=' in env, \
            f'{program} must at least blank the key explicitly'
    # nginx runs as root; root may read it directly.
    nginx_env = docker('exec', NAME, '/bin/sh', '-c',
                       "tr '\\0' '\\n' < /proc/$(pgrep -o nginx | head -n1)/environ || true",
                       stdout=subprocess.PIPE).stdout or ''
    assert fake not in nginx_env, 'nginx must not carry the agent key value'
    print('env isolation: agent key confined to studio + desktop session', flush=True)


def watchdog_status(timeout: float = 180) -> str:
    """Poll until the watchdog has completed its first real cycle after boot
    (the file appears immediately with a 'starting' phase, before the grace
    sleep elapses); return the latest content, or '' on timeout."""
    deadline = time.monotonic() + timeout
    latest = ''
    while time.monotonic() < deadline:
        result = docker('exec', NAME, '/bin/cat', '/run/zephyr/watchdog-status.json',
                        check=False, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        if result.returncode == 0 and result.stdout.strip():
            latest = result.stdout
            if '"healthy"' in latest:
                return latest
        time.sleep(5)
    return latest


def verify_kwin_selfheal() -> None:
    """Kill the window manager hard and require the system to self-heal.

    Either recovery path is acceptable — startplasma restarting kwin, or the
    watchdog's `kwin_x11 --replace` / session restart ladder — but /readyz
    must come back AND the recovered WM must actually frame windows.
    """
    docker('exec', NAME, '/usr/bin/pkill', '-9', '-u', '1001', '-x', 'kwin_x11',
           stdout=subprocess.DEVNULL, check=False)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            if get('/readyz')[0] == 200:
                break
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(5)
    else:
        raise RuntimeError('Window manager self-heal failed: /readyz did not recover')
    # Let any concurrent WM handover (plasma session restart vs watchdog
    # replace) settle before demanding a stable, framing window manager.
    time.sleep(10)
    status = watchdog_status()
    print(f'[selfheal] watchdog status: {status.strip()[:300]}', flush=True)
    verify_window_manager('after kwin kill')
    verify_managed_window('after kwin kill')


def kded5_stability_report() -> None:
    """Diagnostic only (goal: evidence, not attribution).

    The 2026-09 live log showed KCrash restarting kded5 about once a minute.
    The health gate already covers user impact; this records whether the
    crash loop reproduces in a clean container so it can be triaged from CI
    logs without touching the live deployment.
    """
    running = exec_out(NAME, '/usr/bin/pgrep', '-a', 'kded5', check=False).strip()
    print(f'kded5 diagnostic: currently {running or "(not running)"}', flush=True)
    logs = docker('logs', '--tail', '400', NAME, check=False, stdout=subprocess.PIPE).stdout
    crashes = [line for line in (logs or '').splitlines() if 'KCrash' in line]
    print(f'kded5 diagnostic: {len(crashes)} KCrash lines in container log; '
          'non-fatal, triage only', flush=True)
    for line in crashes[-3:]:
        print(f'  {line}', flush=True)


def login() -> str:
    status, headers, _ = get('/auth/api/firstfactor', method='POST', payload={
        'username': 'ciowner', 'password': PASSWORD, 'keepMeLoggedIn': False,
        'targetURL': ORIGIN + '/', 'requestMethod': 'GET',
    })
    if status != 200:
        raise RuntimeError(f'Actual Authelia login failed with HTTP {status}; publishing is blocked')
    jar = SimpleCookie()
    for key, value in headers:
        if key.lower() == 'set-cookie':
            jar.load(value)
    session = jar.get('zephyr_session')
    assert session and session.value, 'Authelia session cookie is missing'
    assert session['secure'] and session['httponly'], 'Session cookie is not Secure and HttpOnly'
    # HTTP is used ONLY on the private CI loopback listener. A production browser
    # obtains and sends this Secure cookie through ModelScope HTTPS termination.
    return 'zephyr_session=' + session.value


def websocket(cookie: str):
    key = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection(('127.0.0.1', PORT), timeout=10) as conn:
        request = (f'GET /desktop/websockify HTTP/1.1\r\nHost: zephyr.test\r\n'
                   f'Origin: {ORIGIN}\r\nCookie: {cookie}\r\n'
                   f'Upgrade: websocket\r\nConnection: Upgrade\r\n'
                   f'Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n'
                   'Sec-WebSocket-Protocol: binary\r\n\r\n')
        conn.sendall(request.encode())
        data = b''
        while b'\r\n\r\n' not in data:
            chunk = conn.recv(4096)
            if not chunk:
                raise RuntimeError('WebSocket closed before the handshake')
            data += chunk
            if len(data) > 32768:
                raise RuntimeError('Unexpected oversized WebSocket headers')
        header = data.split(b'\r\n\r\n', 1)[0].decode()
        assert header.startswith('HTTP/1.1 101'), 'Actual noVNC WebSocket did not upgrade'
        accept = base64.b64encode(hashlib.sha1(
            (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
        assert accept in header, 'WebSocket handshake accept value is incorrect'


def main():
    env = os.environ.copy()
    env.update({'AUTH_PASSWORD': PASSWORD, 'VNC_PASSWORD': VNC_PASSWORD,
                'DESKTOP_PASSWORD': DESKTOP_PASSWORD, 'OPENAI_API_KEY': FAKE_AGENT_KEY})
    volume = NAME + '-data'
    try:
        docker('volume', 'create', volume, stdout=subprocess.DEVNULL)
        docker('run', '-d', '--name', NAME, '--shm-size=512m',
            '-p', f'127.0.0.1:{PORT}:7860', '-v', volume + ':/mnt/workspace',
            '-e', 'PUBLIC_ORIGIN=' + ORIGIN, '-e', 'AUTH_USERNAME=ciowner',
            '-e', 'AUTH_PASSWORD', '-e', 'VNC_PASSWORD', '-e', 'DESKTOP_PASSWORD',
            '-e', 'OPENAI_API_KEY', IMAGE,
            env=env, stdout=subprocess.DEVNULL)
        await_ready()
        verify_liveness_readiness_distinction()
        verify_window_manager('cold start')
        verify_managed_window('cold start')
        shadow = docker('exec', NAME, '/bin/sh', '-c',
                        "grep '^hermes:' /etc/shadow | cut -d: -f2",
                        stdout=subprocess.PIPE).stdout.strip()
        assert shadow.startswith('$'), 'KDE lock-screen password was not applied to the hermes account'
        status, headers, _ = get('/desktop/vnc.html')
        assert status == 302
        assert not any(k.lower() == 'www-authenticate' for k, _ in headers)
        assert get('/internal/authelia/authz')[0] == 404
        assert get('/api/settings')[0] == 404
        cookie = login()
        assert get('/', cookie)[0] == 200
        assert get('/desktop/vnc.html', cookie)[0] == 200
        websocket(cookie)
        docker('exec', '-u', 'hermes', '-w', '/tmp', '-e', 'HOME=/home/hermes',
               '-e', 'HERMES_HOME=/mnt/workspace/zephyr-v2/hermes', NAME,
               '/opt/hermes-venv/bin/hermes', '--help', stdout=subprocess.DEVNULL)
        verify_lock_does_not_kill_kwin()
        verify_env_isolation()
        verify_kwin_selfheal()
        docker('exec', '-u', 'hermes', NAME, '/bin/sh', '-c',
               'printf persistence-ok > /home/hermes/recovery-sentinel.txt')
        docker('restart', '-t', '30', NAME, stdout=subprocess.DEVNULL)
        await_ready()
        verify_window_manager('after restart')
        verify_managed_window('after restart')
        output = docker('exec', '-u', 'hermes', NAME, 'cat', '/home/hermes/recovery-sentinel.txt',
                        stdout=subprocess.PIPE).stdout
        assert output == 'persistence-ok'
        cookie = login()  # In-memory login sessions intentionally expire on process restart.
        assert get('/', cookie)[0] == 200
        status = watchdog_status()
        assert '"healthy": true' in status, f'watchdog not healthy after restart: {status}'
        kded5_stability_report()
        print('REAL CONTAINER GATE PASSED: auth, HTTP, WebSocket, CLI, window manager, '
              'lock/unlock, env isolation, kwin self-heal, restart persistence.')
        print('Not tested by this gate: pixel-level desktop rendering, paid model replies, '
              'ModelScope ingress.')
    finally:
        docker('rm', '-f', NAME, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        docker('volume', 'rm', volume, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
