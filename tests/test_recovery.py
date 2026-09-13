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
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('bootstrap', ROOT / 'recovery/bootstrap.py')
bootstrap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)


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
            subprocess.run(['bash', '-n', str(path)], check=True)

    def test_install_uses_final_path(self):
        dockerfile = (ROOT / 'Dockerfile').read_text()
        self.assertNotIn('/opt/hermes-src', dockerfile)
        self.assertIn('python3 -m venv /opt/hermes-venv', dockerfile)
        self.assertIn('cd /tmp && /opt/hermes-venv/bin/hermes --help', dockerfile)

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
