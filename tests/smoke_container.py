#!/usr/bin/env python3
"""Integration gate for a REAL built image. Executed by GitHub Actions, not locally here.

No paid LLM request is made. Tests actual Authelia login, noVNC assets, WebSocket
handshake, CLI imports, and restart persistence. Fails rather than publishing on error.
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
PORT = 17860


def docker(*args: str, check: bool = True, **kwargs):
    return subprocess.run(['docker', *args], check=check, text=True, **kwargs)


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
    raise RuntimeError('Actual image readiness failed; publishing is blocked')


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
    env.update({'AUTH_PASSWORD': PASSWORD, 'VNC_PASSWORD': VNC_PASSWORD})
    volume = NAME + '-data'
    try:
        docker('volume', 'create', volume, stdout=subprocess.DEVNULL)
        docker('run', '-d', '--name', NAME, '--shm-size=512m',
            '-p', f'127.0.0.1:{PORT}:7860', '-v', volume + ':/mnt/workspace',
            '-e', 'PUBLIC_ORIGIN=' + ORIGIN, '-e', 'AUTH_USERNAME=ciowner',
            '-e', 'AUTH_PASSWORD', '-e', 'VNC_PASSWORD', IMAGE,
            env=env, stdout=subprocess.DEVNULL)
        await_ready()
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
        docker('exec', '-u', 'hermes', NAME, '/bin/sh', '-c',
               'printf persistence-ok > /home/hermes/recovery-sentinel.txt')
        docker('restart', '-t', '30', NAME, stdout=subprocess.DEVNULL)
        await_ready()
        output = docker('exec', '-u', 'hermes', NAME, 'cat', '/home/hermes/recovery-sentinel.txt',
                        stdout=subprocess.PIPE).stdout
        assert output == 'persistence-ok'
        cookie = login()  # In-memory login sessions intentionally expire on process restart.
        assert get('/', cookie)[0] == 200
        print('REAL CONTAINER GATE PASSED: auth, HTTP, WebSocket, CLI, restart persistence.')
        print('Not tested by this gate: browser-rendered KDE, paid model replies, ModelScope ingress.')
    finally:
        docker('rm', '-f', NAME, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        docker('volume', 'rm', volume, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


if __name__ == '__main__':
    main()
