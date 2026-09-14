#!/usr/bin/python3
"""Desktop self-healing watchdog: turn /readyz failures back into a usable desktop.

supervisord already restarts processes that EXIT. It cannot see, and nothing
else fixes, the states this watchdog owns:
  - kwin dead or no longer owning the X11 root window while plasmashell lives
    (the 2026-09 incident: windows render with no title bar and cannot be
    moved, maximized, or closed);
  - an X server that hangs without exiting;
  - processes stuck in T (stopped) state;
  - supervisor programs that exhausted their start retries (FATAL).

Repair ladder per issue, then stop: try the cheapest safe step first
(`kwin_x11 --replace` inside the live session), re-probe, escalate to a
session restart, and never loop — each issue runs its ladder at most once,
and a global budget caps all repairs per rolling window. After that the
watchdog only records diagnostics. Diagnostics bundles contain process
tables, X/W property state, and dbus reachability; they never contain
process environments (the desktop legitimately carries a model API key) or
any credential material.
"""
from __future__ import annotations

import collections
import http.client
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

APP_UID = '1001'
DISPLAY = ':1'
XAUTHORITY = '/run/user/1001/.Xauthority'
XDG_RUNTIME_DIR = '/run/user/1001'
SUPERVISOR_CONF = '/run/zephyr/supervisord.conf'
STATUS_FILE = Path('/run/zephyr/watchdog-status.json')
DIAGNOSIS_ROOT = Path(os.environ.get('DATA_ROOT', '/mnt/workspace/zephyr-v2')) / 'diagnostics'

LOOP_SECONDS = float(os.environ.get('WATCHDOG_LOOP_SECONDS', '20'))
STARTUP_GRACE = float(os.environ.get('WATCHDOG_STARTUP_GRACE', '60'))
KWIN_WAIT = 30.0        # kwin_x11 --replace must claim the root quickly
DESKTOP_WAIT = 180.0    # a full startplasma-x11 session takes a while
SERVICE_WAIT = 45.0     # vnc / novnc / studio restarts
CONT_WAIT = 10.0
BUDGET_MAX = int(os.environ.get('WATCHDOG_BUDGET_MAX', '4'))
BUDGET_WINDOW = float(os.environ.get('WATCHDOG_BUDGET_WINDOW', '1800'))
KEEP_DIAGNOSIS = 10
GOSU = '/usr/sbin/gosu' if os.path.exists('/usr/sbin/gosu') else '/usr/bin/gosu'

PROBE_NAMES = ('x', 'wm', 'plasma', 'kwin', 'vnc', 'novnc', 'studio')


def run(command: list[str], timeout: float = 8) -> tuple[bool, str]:
    try:
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                timeout=timeout, text=True, errors='replace')
        return result.returncode == 0, result.stdout or ''
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f'{type(exc).__name__}: {exc}'


def as_desktop(command: list[str]) -> list[str]:
    """Run an X client as the desktop user with the session environment.

    The caller's environment is not forwarded (root may carry secrets); the
    three session variables the X client needs are set explicitly.
    """
    return [GOSU, 'hermes', '/usr/bin/env',
            f'DISPLAY={DISPLAY}', f'XAUTHORITY={XAUTHORITY}',
            f'XDG_RUNTIME_DIR={XDG_RUNTIME_DIR}', *command]


# --- probes -------------------------------------------------------------------

def x_ok() -> bool:
    return run(as_desktop(['xdpyinfo']), timeout=8)[0]


def wm_ok() -> bool:
    return run(as_desktop(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK']), timeout=8)[0]


def process_state(binary: str) -> str:
    """'' when absent, else the first process stat, e.g. 'S', 'T', 'Z'."""
    ok, out = run(['/usr/bin/pgrep', '-u', APP_UID, '-x', binary], timeout=5)
    if not ok or not out.strip():
        return ''
    pid = out.split()[0]
    ok, out = run(['/usr/bin/ps', '-o', 'stat=', '-p', pid], timeout=5)
    return out.strip()[:1] if ok else ''


def tcp_ok(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=3):
            return True
    except OSError:
        return False


def http_ok(port: int, path: str) -> bool:
    try:
        connection = http.client.HTTPConnection('127.0.0.1', port, timeout=3)
        connection.request('GET', path)
        status = connection.getresponse().status
        connection.close()
        return status == 200
    except (OSError, http.client.HTTPException):
        return False


def probe_all() -> dict[str, object]:
    return {
        'x': x_ok(),
        'wm': wm_ok(),
        'plasma_state': process_state('plasmashell'),
        'kwin_state': process_state('kwin_x11'),
        'vnc': tcp_ok(5901),
        'novnc': http_ok(6080, '/vnc.html'),
        'studio': http_ok(8648, '/'),
    }


def supervisor_states() -> dict[str, str]:
    ok, out = run(['/usr/bin/supervisorctl', '-c', SUPERVISOR_CONF, 'status'], timeout=15)
    states: dict[str, str] = {}
    if ok:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2:
                states[parts[0]] = parts[1]
    return states


# --- issue classification and ladder -----------------------------------------

# Ladders: one pass each, in order. If the issue survives the whole ladder the
# watchdog records diagnostics and waits for the issue to clear on its own.
LADDERS: dict[str, list[tuple[str, float]]] = {
    'wm': [('replace-kwin', KWIN_WAIT), ('restart-desktop', DESKTOP_WAIT)],
    'x': [('restart-vnc', SERVICE_WAIT), ('restart-desktop', DESKTOP_WAIT)],
    'vnc': [('restart-vnc', SERVICE_WAIT)],
    'novnc': [('restart-novnc', SERVICE_WAIT)],
    'studio': [('restart-studio', SERVICE_WAIT)],
    'stopped': [('cont-stopped', CONT_WAIT)],
}


def classify(probes: dict[str, object], states: dict[str, str],
             streaks: dict[str, int]) -> str | None:
    """Pick the highest-priority actionable issue, or None.

    `streaks` counts consecutive failed observations per issue; transient
    states during supervisor start/backoff windows are not actionable.
    """
    x_alive = bool(probes['x'])
    if not x_alive:
        vnc_state = states.get('vnc', '')
        if vnc_state == 'FATAL' or (vnc_state == 'RUNNING'
                                    and streaks['x'] + 1 >= 2):
            return 'x'
        return None  # starting / backing off / first miss: give it a cycle
    if not probes['wm'] or probes['kwin_state'] in ('', 'Z'):
        return 'wm'
    if not probes['vnc'] and streaks['vnc'] + 1 >= 2 and states.get('vnc') == 'RUNNING':
        return 'vnc'
    if not probes['novnc'] and streaks['novnc'] + 1 >= 2:
        return 'novnc'
    if not probes['studio'] and states.get('studio') == 'FATAL':
        return 'studio'
    if probes['plasma_state'] == 'T' or probes['kwin_state'] == 'T':
        return 'stopped'
    for name in ('auth', 'nginx', 'health', 'dbus'):
        if states.get(name) == 'FATAL':
            return f'fatal:{name}'
    return None


def steps_for(issue: str) -> list[tuple[str, float]]:
    if issue.startswith('fatal:'):
        return [(f"restart-{issue.split(':', 1)[1]}", SERVICE_WAIT)]
    return LADDERS.get(issue, [])


class RepairBudget:
    """Global cap: at most BUDGET_MAX repairs per rolling BUDGET_WINDOW."""

    def __init__(self, maximum: int = BUDGET_MAX, window: float = BUDGET_WINDOW,
                 clock=time.monotonic):
        self.maximum = maximum
        self.window = window
        self.clock = clock
        self.history: collections.deque[float] = collections.deque()

    def allows(self) -> bool:
        now = self.clock()
        while self.history and now - self.history[0] > self.window:
            self.history.popleft()
        return len(self.history) < self.maximum

    def record(self) -> None:
        self.history.append(self.clock())


# --- repair actions ------------------------------------------------------------

def action_runner(action: str) -> tuple[bool, str]:
    if action == 'replace-kwin':
        # Detached: kwin --replace keeps running as the session WM.
        try:
            subprocess.run(as_desktop(['kwin_x11', '--replace']),
                           start_new_session=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=10, check=False)
            return True, 'kwin_x11 --replace dispatched'
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, f'replace failed: {type(exc).__name__}'
    if action == 'cont-stopped':
        # SIGCONT every stopped desktop-user process; SIGSTOP is not something
        # supervisor manages, and a frozen kwin looks exactly like a dead one.
        ok, out = run(['/usr/bin/pgrep', '-u', APP_UID, '-x', 'plasmashell'])
        pids = out.split() if ok else []
        ok, out = run(['/usr/bin/pgrep', '-u', APP_UID, '-x', 'kwin_x11'])
        pids += out.split() if ok else []
        for pid in pids:
            try:
                os.kill(int(pid), signal.SIGCONT)
            except (ValueError, OSError):
                pass
        return True, f'SIGCONT sent to {len(pids)} process(es)'
    program = action.removeprefix('restart-')
    if program in ('desktop', 'vnc', 'novnc', 'studio', 'auth', 'nginx', 'health', 'dbus'):
        states = supervisor_states()
        state = states.get(program, '')
        verb = 'restart' if state in ('RUNNING', 'BACKINGOFF') else 'start'
        ok, out = run(['/usr/bin/supervisorctl', '-c', SUPERVISOR_CONF, verb, program],
                      timeout=30)
        return ok, f'supervisorctl {verb} {program}: {out.strip()[:200]}'
    return False, f'unknown action {action}'


def wait_for(predicate, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(5)
    return predicate()


def issue_resolved(issue: str, probes: dict[str, object], states: dict[str, str]) -> bool:
    if issue == 'x':
        return bool(probes['x']) and bool(probes['wm'])
    if issue == 'wm':
        return bool(probes['x']) and bool(probes['wm']) and probes['kwin_state'] not in ('', 'Z')
    if issue == 'vnc':
        return bool(probes['vnc'])
    if issue == 'novnc':
        return bool(probes['novnc'])
    if issue == 'studio':
        return bool(probes['studio'])
    if issue == 'stopped':
        return probes['plasma_state'] != 'T' and probes['kwin_state'] != 'T'
    if issue.startswith('fatal:'):
        return states.get(issue.split(':', 1)[1]) not in ('FATAL', 'EXITED')
    return True


# --- diagnostics ---------------------------------------------------------------

def session_vars_of(pid_env_owner: str) -> str:
    """Only the four non-secret session variables, read as the desktop user.

    A full environment dump is never taken: the desktop session legitimately
    carries the model API key.
    """
    script = (f"tr '\\0' '\\n' < /proc/{pid_env_owner}/environ "
              "| grep -E '^(DISPLAY|XAUTHORITY|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS)=' "
              "|| true")
    ok, out = run([GOSU, 'hermes', '/bin/sh', '-c', script], timeout=8)
    return out if ok else f'(unreadable)'


def dbus_ping(session_address: str) -> str:
    if 'DBUS_SESSION_BUS_ADDRESS=' not in session_address:
        return 'session bus address: not found'
    ok, out = run(['/usr/bin/pgrep', '-u', APP_UID, '-x', 'plasmashell'], timeout=5)
    if not ok or not out.strip():
        return 'plasmashell pid: not found'
    pid = out.split()[0]
    ok, out = run(as_desktop(['dbus-send', '--session', '--print-reply',
                              '--dest=org.freedesktop.DBus', '/', 'org.freedesktop.DBus.ListNames']),
                  timeout=8)
    return f'dbus ListNames: {"ok" if ok else "FAILED"} {out.strip()[:120]}'


def collect_diagnostics(issue: str, probes: dict[str, object], states: dict[str, str],
                        history: list[str]) -> Path | None:
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    bundle = DIAGNOSIS_ROOT / f'watchdog-{stamp}-{issue.replace(":", "-")}'
    try:
        bundle.mkdir(parents=True, exist_ok=False)
    except OSError as exc:
        print(f'watchdog: cannot create diagnostics bundle: {type(exc).__name__}', flush=True)
        return None
    plasma = run(['/usr/bin/pgrep', '-u', APP_UID, '-x', 'plasmashell'], timeout=5)[1].split()
    x_out = run(as_desktop(['xdpyinfo']), timeout=8)[1]
    wm_out = run(as_desktop(['xprop', '-root', '_NET_SUPPORTING_WM_CHECK',
                             '_NET_WM_NAME', '_NET_SUPPORTED']), timeout=8)[1]
    sections = {
        'summary.txt': f'time={time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}\n'
                       f'issue={issue}\nprobes={json.dumps(probes, sort_keys=True)}\n'
                       f'supervisor={json.dumps(states, sort_keys=True)}\n'
                       f'actions_taken={json.dumps(history)}\n',
        'supervisor-status.txt': run(['/usr/bin/supervisorctl', '-c', SUPERVISOR_CONF,
                                      'status'], timeout=15)[1],
        'processes.txt': run(['/usr/bin/ps', '-eo', 'user,pid,ppid,stat,etime,args'],
                             timeout=10)[1],
        'x-server.txt': (x_out or '(xdpyinfo produced no output)') + '\n--- xprop ---\n' +
                        (wm_out or '(xprop produced no output)'),
        'session.txt': (session_vars_of(plasma[0]) if plasma else 'plasmashell pid: not found'),
        'ports.txt': run(['/usr/bin/ss', '-ltnp'], timeout=10)[1],
    }
    sections['dbus.txt'] = dbus_ping(sections['session.txt'])
    for name, content in sections.items():
        try:
            (bundle / name).write_text(content or '(empty)', encoding='utf-8')
            os.chmod(bundle / name, 0o644)
        except OSError:
            pass
    os.chmod(bundle, 0o755)
    # Retention: keep only the newest KEEP_DIAGNOSIS bundles.
    bundles = sorted(DIAGNOSIS_ROOT.glob('watchdog-*'))
    for stale in bundles[:-KEEP_DIAGNOSIS] if len(bundles) > KEEP_DIAGNOSIS else []:
        shutil.rmtree(stale, ignore_errors=True)
    return bundle


# --- main loop -------------------------------------------------------------------

def write_status(state: dict[str, object]) -> None:
    try:
        STATUS_FILE.write_text(json.dumps(state, sort_keys=True), encoding='utf-8')
        os.chmod(STATUS_FILE, 0o644)
    except OSError:
        pass


class Watchdog:
    def __init__(self, budget: RepairBudget | None = None):
        self.budget = budget or RepairBudget()
        self.episode: dict[str, object] | None = None  # {'issue': str, 'step': int,
        #                                                'history': [..], 'diagnosed': bool}
        self.streaks = {name: 0 for name in ('x', 'vnc', 'novnc')}

    def cycle(self) -> dict[str, object]:
        probes = probe_all()
        states = supervisor_states()
        for name in ('x', 'vnc', 'novnc'):
            failed = not probes[name]
            self.streaks[name] = self.streaks[name] + 1 if failed else 0
        issue = classify(probes, states, self.streaks)
        healthy = issue is None and all(
            bool(probes[key]) for key in ('x', 'wm', 'vnc', 'novnc', 'studio')
        ) and probes['plasma_state'] not in ('', 'Z') and probes['kwin_state'] not in ('', 'Z')

        result: dict[str, object] = {
            'last_check': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'healthy': healthy, 'issue': issue,
            'mode': 'repair' if self.budget.allows() else 'observe-only',
            'repairs_in_window': len(self.budget.history),
            'episode': self.episode['issue'] if self.episode else None,
        }

        if healthy:
            self.episode = None
            write_status(result)
            return result
        if issue is None:
            # Broken but nothing actionable (starting/backoff windows): stand by.
            write_status(result)
            return result

        # New episode, or continue the current one.
        if not self.episode or self.episode['issue'] != issue:
            self.episode = {'issue': issue, 'step': 0, 'history': [], 'diagnosed': False}
        ladder = steps_for(issue)
        step_index = int(self.episode['step'])  # type: ignore[index]
        if step_index >= len(ladder):
            # Ladder exhausted: diagnostics once, then observe until it clears.
            if not self.episode['diagnosed']:  # type: ignore[index]
                bundle = collect_diagnostics(issue, probes, states,
                                             list(self.episode['history']))  # type: ignore[index]
                self.episode['diagnosed'] = True  # type: ignore[index]
                result['diagnostics'] = str(bundle) if bundle else 'unavailable'
                print(f'watchdog: issue {issue} survived its ladder; diagnostics '
                      f'at {bundle or "(unavailable)"}; observing only', flush=True)
            write_status(result)
            return result

        if not self.budget.allows():
            write_status(result)
            return result  # observe-only: budget exhausted, never loop

        action, wait = ladder[step_index]
        ok, detail = action_runner(action)
        self.budget.record()
        print(f'watchdog: issue={issue} action={action} ok={ok} {detail}', flush=True)
        self.episode['history'].append(f'{action}:{ok}')  # type: ignore[index]
        result['last_action'] = f'{action}:{"ok" if ok else "failed"}'
        resolved = wait_for(lambda: issue_resolved(
            issue, probe_all(), supervisor_states()), wait)
        if resolved:
            print(f'watchdog: issue {issue} resolved after {action}', flush=True)
            self.episode = None
            self.streaks = {name: 0 for name in self.streaks}
        else:
            self.episode['step'] = step_index + 1  # type: ignore[index]
        write_status(result)
        return result


def main() -> None:
    print(f'watchdog: starting, grace {STARTUP_GRACE:.0f}s, '
          f'budget {BUDGET_MAX}/{BUDGET_WINDOW:.0f}s', flush=True)
    # Publish state before the grace sleep so /run/zephyr/watchdog-status.json
    # exists (and is truthful) from the very first second of the container.
    write_status({'phase': 'starting', 'grace_seconds': STARTUP_GRACE,
                  'last_check': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    time.sleep(STARTUP_GRACE)
    watchdog = Watchdog()
    while True:
        started = time.monotonic()
        try:
            watchdog.cycle()
        except Exception as exc:  # never die: a dead watchdog heals nothing
            print(f'watchdog: cycle error {type(exc).__name__}: {exc}', flush=True)
        elapsed = time.monotonic() - started
        time.sleep(max(5.0, LOOP_SECONDS - elapsed))


if __name__ == '__main__':
    main()
