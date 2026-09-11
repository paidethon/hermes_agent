#!/usr/bin/python3
"""Readiness means desktop + local Studio + auth respond, not that an LLM replied."""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import subprocess
import sys
from urllib.error import URLError, HTTPError
from urllib.request import build_opener, ProxyHandler


def http_ok(url: str) -> bool:
    try:
        with build_opener(ProxyHandler({})).open(url, timeout=2) as response:
            return response.status == 200
    except (URLError, HTTPError, OSError, TimeoutError):
        return False


def tcp_ok() -> bool:
    try:
        with socket.create_connection(('127.0.0.1', 5901), timeout=2):
            return True
    except OSError:
        return False


def desktop_ok() -> bool:
    try:
        return subprocess.run(['pgrep', '-u', '1001', '-x', 'plasmashell'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                              timeout=2).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def checks() -> dict[str, bool]:
    probes = {
        'auth': lambda: http_ok('http://127.0.0.1:9091/auth/api/health'),
        'novnc': lambda: http_ok('http://127.0.0.1:6080/vnc.html'),
        'studio': lambda: http_ok('http://127.0.0.1:8648/'),
        'vnc': tcp_ok,
        'desktop': desktop_ok,
    }
    with ThreadPoolExecutor(max_workers=len(probes)) as pool:
        values = list(pool.map(lambda fn: fn(), probes.values()))
    return dict(zip(probes, values))


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path != '/readyz':
            self.send_error(404)
            return
        state = checks()
        status = 200 if all(state.values()) else 503
        # A minimal public status does not expose paths, models, accounts, or versions.
        body = json.dumps({'ready': status == 200}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        return


if __name__ == '__main__':
    if '--once' in sys.argv:
        state = checks()
        print(json.dumps(state, sort_keys=True))
        sys.exit(0 if all(state.values()) else 1)
    ThreadingHTTPServer(('127.0.0.1', 9092), Handler).serve_forever()
