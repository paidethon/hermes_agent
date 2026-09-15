#!/usr/bin/python3
"""Readiness means a manageable desktop + local Studio + auth respond.

A running plasmashell alone does not make the desktop usable: without the
window manager, windows render but have no title bar and cannot be moved,
maximized, minimized, or closed. The desktop probes therefore answer three
different questions instead of one:
  desktop - the Plasma shell process is alive
  kwin    - the window manager process is alive
  wm      - a window manager has actually claimed the X11 root window (EWMH)
"""
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import URLError, HTTPError
from urllib.request import build_opener, ProxyHandler

# Must match the session environment rendered by bootstrap.render_supervisor();
# a unit test pins this consistency.
DISPLAY = ':1'
XAUTHORITY = '/run/user/1001/.Xauthority'
APP_UID = '1001'


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


def _run(command: list[str], timeout: float = 3) -> bool:
    # Probes run from supervisord, the Docker HEALTHCHECK, and CI exec calls;
    # none of those callers is guaranteed to carry the session environment.
    env = dict(os.environ, DISPLAY=DISPLAY, XAUTHORITY=XAUTHORITY)
    try:
        return subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL,
                              timeout=timeout).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def process_ok(binary: str) -> bool:
    return _run(['pgrep', '-u', APP_UID, '-x', binary], timeout=2)


def wm_ok() -> bool:
    # Only an EWMH window manager publishes _NET_SUPPORTING_WM_CHECK on the
    # root window; a bare X server leaves it unset. This catches "kwin died
    # while Xvnc still runs", which a process check alone would miss if the
    # process list were ever replaced by an equivalent.
    return _run(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK'])


def desktop_ok() -> bool:
    """True only when shell, WM process, and WM root-window ownership all hold."""
    return process_ok('plasmashell') and process_ok('kwin_x11') and wm_ok()


def x_ok() -> bool:
    """The X server itself answers protocol requests (a hung server fails this
    while every process-level probe can still look alive)."""
    return _run(['xdpyinfo', '-display', DISPLAY])


def dbus_ok() -> bool:
    # The session bus runs as the desktop user; the system bus runs as root and
    # must not satisfy this probe.
    return process_ok('dbus-daemon')


# Build-time inputs copied into the image; absence (local dev) degrades to '?'.
def _read_version(name: str) -> str:
    try:
        return (Path('/opt/versions') / name).read_text().strip()[:12] or '?'
    except OSError:
        return '?'


VERSIONS = {'app': _read_version('app.txt'), 'hermes': _read_version('hermes.txt'),
            'studio': _read_version('studio.txt')}


def _read_vnc_cmd() -> str:
    try:
        return (Path('/run/zephyr/vnc-cmd.txt').read_text().strip())[:160]
    except OSError:
        return '?'


VERSIONS['vncCmd'] = _read_vnc_cmd()


def checks() -> dict[str, bool]:
    probes = {
        'auth': lambda: http_ok('http://127.0.0.1:9091/auth/api/health'),
        'novnc': lambda: http_ok('http://127.0.0.1:6080/vnc.html'),
        'studio': lambda: http_ok('http://127.0.0.1:8648/'),
        'vnc': tcp_ok,
        'x': x_ok,
        'dbus': dbus_ok,
        'desktop': lambda: process_ok('plasmashell'),
        'kwin': lambda: process_ok('kwin_x11'),
        'wm': wm_ok,
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
        # Public status carries only probe names, booleans, and the pinned
        # upstream commit ids; never paths, models, accounts, or environment.
        body = json.dumps({'ready': status == 200, 'checks': state,
                           'versions': VERSIONS}).encode()
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
