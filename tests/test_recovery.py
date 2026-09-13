"""Unit tests and REAL nginx integration tests with deterministic mock backends.

These do not claim to test real Authelia, VNC, KDE, Hermes, or ModelScope.
"""
import configparser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import importlib.util
import json
import os
from pathlib import Path
try:
    import pwd
except ImportError:  # Unix-only; the nginx integration tests skip without it.
    pwd = None
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]

# subprocess resolves plain 'bash' to System32's WSL launcher on Windows
# (CreateProcess searches System32 before PATH); prefer an explicit PATH hit
# and fall back to a standard Git Bash location.
BASH = shutil.which('bash')
if BASH and sys.platform == 'win32' and 'system32' in BASH.lower():
    for candidate in ('C:/Program Files/Git/usr/bin/bash.exe',
                      'C:/Program Files (x86)/Git/usr/bin/bash.exe'):
        if Path(candidate).exists():
            BASH = candidate
            break

spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'recovery/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
spec_health = importlib.util.spec_from_file_location('health', ROOT / 'recovery/health.py')
health = importlib.util.module_from_spec(spec_health)
spec_health.loader.exec_module(health)


class ConfigurationTests(unittest.TestCase):
    def test_origin_normalization(self):
        self.assertEqual(bootstrap.validate_origin('https://Zephyr.test/'),
                         ('https://zephyr.test', 'zephyr.test', 'zephyr.test'))

    def test_nonstandard_https_port(self):
        self.assertEqual(bootstrap.validate_origin('https://zephyr.test:8443')[2], 'zephyr.test:8443')

    def test_origin_injection_and_insecure_values(self):
        values = ['http://zephyr.test', 'https://user:pass@zephyr.test', 'https://zephyr.test/path',
                  'https://zephyr.test?evil=1', 'https://127.0.0.1', 'https://localhost',
                  'https://zephyr.test;evil', 'https://a..test', 'https://-a.test',
                  'https://zephyr.test/#fragment', 'https://zephyr.test:99999', '']
        for value in values:
            with self.subTest(value=value), self.assertRaises(ValueError):
                bootstrap.validate_origin(value)

    def test_root_guards(self):
        for path in ['/etc', '/mnt/workspace', '/mnt/workspace/zephyr',
                     '/mnt/workspace/a/../b', '/mnt/workspace/a/b', '/mnt/workspace/a;echo']:
            with self.subTest(path=path), self.assertRaises(ValueError):
                bootstrap.validate_data_root(path)

    def test_authentication_configuration(self):
        conf = yaml.safe_load(bootstrap.render_authelia(Path('/mnt/workspace/test-v2'),
            'https://zephyr.test', 'zephyr.test', {'session': 'a' * 64, 'storage': 'b' * 64}))
        self.assertEqual(conf['server']['address'], 'tcp://127.0.0.1:9091/auth')
        self.assertEqual(conf['access_control']['default_policy'], 'deny')
        self.assertEqual(conf['session']['cookies'][0]['domain'], 'zephyr.test')
        self.assertTrue(conf['authentication_backend']['password_reset']['disable'])
        self.assertNotIn('password', conf['authentication_backend']['file'])

    def test_supervisor_no_legacy_or_public_studio(self):
        raw = bootstrap.render_supervisor(Path('/mnt/workspace/test-v2'), '1280x800', '0')
        parser = configparser.ConfigParser(interpolation=None)
        parser.read_string(raw)
        self.assertNotIn('inet_http_server', parser)
        self.assertEqual(parser['program:auth']['user'], 'zephyr-auth')
        self.assertEqual(parser['program:auth']['directory'], '/')
        self.assertEqual(parser['program:desktop']['user'], 'hermes')
        self.assertIn('127.0.0.1:6080', parser['program:novnc']['command'])
        self.assertNotIn('llama', raw)
        self.assertNotIn('gateway', raw)

    def test_shell_syntax(self):
        for path in (ROOT / 'recovery').glob('*.sh'):
            # as_posix(): Git Bash on Windows mangles backslash arguments.
            subprocess.run([BASH, '-n', path.as_posix()], check=True)

    def test_install_uses_final_path(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertNotIn('/opt/hermes-src', dockerfile)
        self.assertIn('python3 -m venv /opt/hermes-venv', dockerfile)
        self.assertIn('cd /tmp && /opt/hermes-venv/bin/hermes --help', dockerfile)

    @unittest.skipUnless(hasattr(os, 'chown'), 'POSIX-only: os.chown missing')
    def test_password_is_hashed_and_initialization_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap.os, 'chown'):
            root = Path(temp)
            (root / 'auth').mkdir()
            password = 'local-test-value-not-a-real-password'
            bootstrap.initialize_auth(root, 'testowner', password)
            original = (root / 'auth/users.yml').read_text()
            self.assertNotIn(password, original)
            self.assertIn('$argon2id$', original)
            bootstrap.initialize_auth(root, 'testowner', password)
            self.assertEqual((root / 'auth/users.yml').read_text(), original)
            bootstrap.initialize_auth(root, 'testowner', '')
            self.assertEqual((root / 'auth/users.yml').read_text(), original)

    def test_first_boot_without_password_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            root = Path(temp)
            (root / 'auth').mkdir()
            bootstrap.initialize_auth(root, 'testowner', '')

    def test_short_password_rejected(self):
        with tempfile.TemporaryDirectory() as temp, self.assertRaises(ValueError):
            root = Path(temp)
            (root / 'auth').mkdir()
            bootstrap.initialize_auth(root, 'testowner', 'short')

    @unittest.skipUnless(hasattr(os, 'chown'), 'POSIX-only: os.chown missing')
    def test_managed_file_symlink_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap.os, 'chown'):
            root = Path(temp)
            target = root / 'original'
            target.write_text('untouched')
            link = root / 'managed'
            link.symlink_to(target)
            with self.assertRaises(ValueError):
                bootstrap.atomic_write(link, 'replaced', 1001, 1001)
            self.assertEqual(target.read_text(), 'untouched')

    @unittest.skipUnless(hasattr(os, 'chown'), 'POSIX-only: os.chown missing')
    def test_vnc_password_uses_protocol_truncation(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(bootstrap.os, 'chown'), \
                patch.object(bootstrap.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, stdout=b'vnc-hash')
            home = Path(temp) / 'home'
            (home / '.vnc').mkdir(parents=True)
            bootstrap.initialize_vnc_password(home, 'Vnc114514')
            self.assertEqual((home / '.vnc/passwd').read_text(), 'vnc-hash')
            self.assertEqual(run.call_args.kwargs['input'], b'Vnc11451\n')

    def test_vnc_password_rejects_invalid_values(self):
        for value in ['', '7chars!', 'Vnç11451', 'V' + 'x' * 64]:
            with self.subTest(length=len(value)), self.assertRaises(ValueError):
                bootstrap.initialize_vnc_password(Path('/nonexistent-home'), value)

    def test_vnc_password_optional_when_file_exists(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            (home / '.vnc').mkdir()
            (home / '.vnc/passwd').write_bytes(b'existing')
            bootstrap.initialize_vnc_password(home, '')

    def test_desktop_password_applied_via_chpasswd(self):
        with patch.dict(os.environ, {'DESKTOP_PASSWORD': 'kde-lock-test'}), \
                patch.object(bootstrap.subprocess, 'run') as run:
            bootstrap.initialize_desktop_auth()
            self.assertEqual(run.call_args.kwargs['input'], b'hermes:kde-lock-test\n')

    def test_desktop_password_rejects_weak_values(self):
        for value in ['', 'short', 'x' * 257, 'bad\nvalue']:
            with self.subTest(length=len(value)), \
                    patch.dict(os.environ, {'DESKTOP_PASSWORD': value}), \
                    self.assertRaises(ValueError):
                bootstrap.initialize_desktop_auth()

    def test_no_public_studio_reverse_proxy(self):
        conf = bootstrap.render_nginx('https://zephyr.test', 'zephyr.test', 'zephyr.test')
        self.assertNotIn('auth_basic', conf)
        self.assertNotIn('8648', conf)
        self.assertNotIn('listen 8080', conf)
        self.assertIn('listen 0.0.0.0:7860', conf)


class DesktopReadinessTests(unittest.TestCase):
    """Regression for the 2026-09 incident: the image shipped without a window
    manager, and "plasmashell alive" was misread as "desktop usable"."""

    def test_dockerfile_declares_kwin_and_build_gate(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertIn('kde-plasma-desktop kwin-x11', dockerfile)
        # The trim must stay: kwin-x11 is added explicitly, not via Recommends.
        self.assertIn('--no-install-recommends', dockerfile)
        self.assertNotIn('kde-plasma-desktop sddm', dockerfile)
        self.assertIn('FATAL: required desktop binary missing', dockerfile)
        self.assertIn('test -x /usr/bin/kwin_x11', dockerfile)

    def test_desktop_usable_requires_shell_kwin_and_wm(self):
        with patch.object(health, 'process_ok',
                          side_effect=lambda binary: binary == 'plasmashell'), \
                patch.object(health, 'wm_ok', return_value=True):
            self.assertFalse(health.desktop_ok(), 'kwin dead must fail desktop_ok')
        with patch.object(health, 'process_ok', return_value=True), \
                patch.object(health, 'wm_ok', return_value=False):
            self.assertFalse(health.desktop_ok(), 'WM not owning :1 must fail desktop_ok')
        with patch.object(health, 'process_ok', return_value=True), \
                patch.object(health, 'wm_ok', return_value=True):
            self.assertTrue(health.desktop_ok())

    def test_checks_gate_readiness_on_window_manager(self):
        with patch.object(health, 'http_ok', return_value=True), \
                patch.object(health, 'tcp_ok', return_value=True), \
                patch.object(health, 'process_ok',
                             side_effect=lambda binary: binary == 'plasmashell'), \
                patch.object(health, 'wm_ok', return_value=True):
            state = health.checks()
            self.assertTrue(state['desktop'])
            self.assertFalse(state['kwin'])
            self.assertFalse(all(state.values()),
                             'plasmashell alive with kwin dead must not be ready')
        with patch.object(health, 'http_ok', return_value=True), \
                patch.object(health, 'tcp_ok', return_value=True), \
                patch.object(health, 'process_ok', return_value=True), \
                patch.object(health, 'wm_ok', return_value=True):
            self.assertTrue(all(health.checks().values()))

    def readyz_status(self, state: dict) -> int:
        server = ThreadingHTTPServer(('127.0.0.1', 0), health.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            connection = http.client.HTTPConnection('127.0.0.1', server.server_address[1],
                                                    timeout=4)
            connection.request('GET', '/readyz')
            response = connection.getresponse()
            status, body = response.status, json.loads(response.read())
            connection.close()
            self.assertEqual(body, {'ready': status == 200})
            return status
        finally:
            server.shutdown()
            server.server_close()

    def test_readyz_reports_broken_desktop_as_503(self):
        # The exact incident: taskbar fine, every window uncontrollable.
        broken = {'auth': True, 'novnc': True, 'studio': True, 'vnc': True,
                  'desktop': True, 'kwin': False, 'wm': False}
        with patch.object(health, 'checks', return_value=broken):
            self.assertEqual(self.readyz_status(broken), 503)
        healthy = dict(broken, kwin=True, wm=True)
        with patch.object(health, 'checks', return_value=healthy):
            self.assertEqual(self.readyz_status(healthy), 200)

    def test_probe_environment_matches_supervisor_session(self):
        raw = bootstrap.render_supervisor(Path('/mnt/workspace/test-v2'), '1280x800', '0')
        self.assertIn(f'DISPLAY="{health.DISPLAY}"', raw)
        self.assertIn(f'XAUTHORITY="{health.XAUTHORITY}"', raw)


class DesktopPreflightTests(unittest.TestCase):
    """desktop.sh must refuse to start a half-working desktop (fail fast)."""

    SCRIPT = ROOT / 'recovery' / 'desktop.sh'

    def run_script(self, stubs: dict[str, int | str], extra_env: dict[str, str] | None = None,
                   include_system_path: bool = True):
        stub_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, stub_dir, ignore_errors=True)
        for name, behavior in stubs.items():
            stub = stub_dir / name
            body = behavior if isinstance(behavior, str) else f'exit {behavior}'
            stub.write_text(f'#!/bin/sh\n{body}\n')
            stub.chmod(0o755)
        # Stubs shadow any same-named system binaries; the rest of PATH keeps
        # bash helpers (seq, sleep) available. The stub-only PATH makes the
        # first-missing-binary assertions deterministic on any host.
        env = os.environ.copy()
        path_parts = [stub_dir.as_posix()]
        if include_system_path:
            path_parts.append(env.get('PATH', ''))
        env['PATH'] = os.pathsep.join(path_parts)
        env['HOME'] = stub_dir.as_posix()
        env.update(extra_env or {})
        return subprocess.run([BASH, self.SCRIPT.as_posix()], env=env,
                              capture_output=True, text=True, timeout=120)

    def test_missing_binaries_fail_fast(self):
        result = self.run_script({}, include_system_path=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FATAL: required KDE runtime binary missing: dbus-run-session',
                      result.stderr)

    def test_missing_kwin_fails_fast_even_with_rest_of_kde(self):
        stubs = {'dbus-run-session': 0, 'startplasma-x11': 0, 'plasmashell': 0,
                 'xdpyinfo': 0}  # kwin_x11 deliberately absent
        result = self.run_script(stubs, include_system_path=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn('FATAL: required KDE runtime binary missing: kwin_x11',
                      result.stderr)
        self.assertNotIn('startplasma', result.stdout)

    def test_x_server_never_ready_refuses_to_start(self):
        stubs = {'dbus-run-session': 0, 'startplasma-x11': 0, 'kwin_x11': 0,
                 'plasmashell': 0, 'xdpyinfo': 3}
        result = self.run_script(stubs, {'DESKTOP_X_WAIT_ATTEMPTS': '2'})
        self.assertEqual(result.returncode, 1)
        self.assertIn('X server did not become ready', result.stderr)

    def test_ready_x_server_starts_session(self):
        stubs = {'dbus-run-session': 'echo session-started', 'startplasma-x11': 0,
                 'kwin_x11': 0, 'plasmashell': 0, 'xdpyinfo': 0}
        result = self.run_script(stubs)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('session-started', result.stdout)


class MockBackend(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    available = True
    received = []

    def do_GET(self):
        type(self).received.append((self.path, dict(self.headers)))
        if self.path == '/auth/api/authz/auth-request':
            if not type(self).available:
                code = 503
            else:
                code = 200 if self.headers.get('Cookie') == 'zephyr_session=valid' else 401
            body = b''
        elif self.path == '/readyz':
            code, body = 503, b'{"ready":false}'
        elif self.headers.get('Upgrade', '').lower() == 'websocket':
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.end_headers()
            self.close_connection = True
            return
        else:
            code, body = 200, b'upstream-desktop'
        self.send_response(code)
        if code == 200 and self.path == '/auth/api/authz/auth-request':
            self.send_header('Set-Cookie', 'zephyr_session=refreshed; Secure; HttpOnly; SameSite=Lax; Path=/')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@unittest.skipUnless(shutil.which('nginx') and pwd, 'nginx binary not installed')
class NginxIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        (cls.root / 'www').mkdir()
        (cls.root / 'www/index.html').write_text('protected-portal')
        cls.backend = ThreadingHTTPServer(('127.0.0.1', 0), MockBackend)
        cls.backend.daemon_threads = True
        threading.Thread(target=cls.backend.serve_forever, daemon=True).start()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            cls.port = sock.getsockname()[1]
        backend_port = cls.backend.server_port
        conf = bootstrap.render_nginx('https://zephyr.test', 'zephyr.test', 'zephyr.test',
            runtime=str(cls.root), port=cls.port, auth_port=backend_port,
            desktop_port=backend_port, health_port=backend_port,
            worker_user=pwd.getpwuid(os.getuid()).pw_name)
        cls.conf = cls.root / 'nginx.conf'
        cls.conf.write_text(conf)
        cls.log = (cls.root / 'nginx.log').open('w')
        subprocess.run(['nginx', '-t', '-c', str(cls.conf), '-p', str(cls.root)], check=True,
                       stdout=cls.log, stderr=cls.log)
        cls.process = subprocess.Popen(['nginx', '-c', str(cls.conf), '-p', str(cls.root),
            '-g', 'daemon off;'], stdout=cls.log, stderr=cls.log)
        for _ in range(100):
            try:
                with socket.create_connection(('127.0.0.1', cls.port), timeout=.1):
                    break
            except OSError:
                time.sleep(.03)
        else:
            raise RuntimeError('Test nginx did not start')

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        cls.process.wait(timeout=5)
        cls.backend.shutdown()
        cls.backend.server_close()
        cls.log.close()
        cls.temp.cleanup()

    def setUp(self):
        MockBackend.available = True
        MockBackend.received = []

    def request(self, path, cookie=None, extra=None):
        headers = {'Host': 'zephyr.test'}
        if cookie:
            headers['Cookie'] = cookie
        headers.update(extra or {})
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=4)
        conn.request('GET', path, headers=headers)
        resp = conn.getresponse()
        result = resp.status, dict(resp.getheaders()), resp.read()
        conn.close()
        return result

    def test_liveness_does_not_require_login(self):
        self.assertEqual(self.request('/healthz')[0], 200)

    def test_unready_is_not_healthy(self):
        self.assertEqual(self.request('/readyz')[0], 503)

    def test_anonymous_protected_routes_redirect_without_basic_auth(self):
        for path in ['/', '/desktop/vnc.html', '/desktop/app/ui.js']:
            with self.subTest(path=path):
                status, headers, body = self.request(path)
                self.assertEqual(status, 302)
                self.assertEqual(headers['Location'], 'https://zephyr.test/auth/')
                self.assertNotIn('WWW-Authenticate', headers)
                self.assertNotIn(b'upstream-desktop', body)

    def test_invalid_cookie_denied(self):
        self.assertEqual(self.request('/', 'zephyr_session=invalid')[0], 302)

    def test_valid_cookie_allows_portal_and_assets(self):
        self.assertEqual(self.request('/', 'zephyr_session=valid')[2], b'protected-portal')
        status, headers, body = self.request('/desktop/vnc.html', 'zephyr_session=valid')
        self.assertEqual((status, body), (200, b'upstream-desktop'))
        self.assertIn('Secure', headers['Set-Cookie'])
        csp = headers.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)
        self.assertIn('https://www.modelscope.cn', csp)
        self.assertNotIn('X-Frame-Options', headers)

    def test_auth_portal_allows_modelscope_framing_only(self):
        status, headers, _ = self.request('/auth/', 'zephyr_session=valid')
        self.assertEqual(status, 200)
        csp = headers.get('Content-Security-Policy', '')
        self.assertIn('frame-ancestors', csp)
        self.assertIn('https://modelscope.cn', csp)
        self.assertNotIn('X-Frame-Options', headers)

    def test_auth_failure_is_fail_closed(self):
        MockBackend.available = False
        self.assertEqual(self.request('/desktop/vnc.html', 'zephyr_session=valid')[0], 500)

    def test_no_public_internal_authorization_endpoint(self):
        self.assertEqual(self.request('/internal/authelia/authz')[0], 404)

    def test_legacy_app_routes_not_accidentally_exposed(self):
        for path in ['/api/settings', '/socket.io/', '/chat/', '/flow/', '/.env']:
            with self.subTest(path=path):
                self.assertEqual(self.request(path, 'zephyr_session=valid')[0], 404)

    def test_spoofed_host_and_authorization_not_forwarded(self):
        self.request('/desktop/vnc.html', 'zephyr_session=valid',
                     {'Host': 'attacker.test', 'Authorization': 'Bearer unused-test-value',
                      'X-Forwarded-Proto': 'http', 'X-Forwarded-For': '6.6.6.6'})
        auth_headers = next(h for p, h in MockBackend.received if p.endswith('auth-request'))
        self.assertEqual(auth_headers['Host'], 'zephyr.test')
        self.assertEqual(auth_headers['X-Forwarded-Proto'], 'https')
        self.assertEqual(auth_headers['X-Forwarded-For'], '127.0.0.1')
        self.assertNotIn('Authorization', auth_headers)

    def test_cross_origin_websocket_rejected(self):
        status = self.request('/desktop/websockify', 'zephyr_session=valid',
            {'Origin': 'https://attacker.test', 'Upgrade': 'websocket', 'Connection': 'Upgrade'})[0]
        self.assertEqual(status, 403)

    def test_anonymous_websocket_not_upgraded(self):
        status = self.request('/desktop/websockify', extra={
            'Origin': 'https://zephyr.test', 'Upgrade': 'websocket', 'Connection': 'Upgrade'})[0]
        self.assertEqual(status, 302)

    def test_authenticated_websocket_upgrade(self):
        status = self.request('/desktop/websockify', 'zephyr_session=valid', {
            'Origin': 'https://zephyr.test', 'Upgrade': 'websocket', 'Connection': 'Upgrade'})[0]
        self.assertEqual(status, 101)


if __name__ == '__main__':
    unittest.main(verbosity=2)
