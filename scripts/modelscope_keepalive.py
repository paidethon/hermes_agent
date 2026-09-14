#!/usr/bin/env python3
"""Keepalive with health awareness (replaces the Stopped-only workflow).

Decision table, executed on every schedule tick:
  Stopped                                  -> deploy (retries capped)
  Building / Deploying                     -> no-op
  Running + /readyz OK                     -> no-op
  Running + /readyz failing VERIFY_COUNT
  times in a row this run                  -> one recovery deploy, unless the
                                              cooldown / daily cap says stop
  Failed / BuildFailed / DeployFailed      -> treated like Running-unhealthy

State (last recovery time, recovery timestamps) comes from a JSON file the
workflow passes in via actions/cache, so the limits survive across runs
without any remote mutable state.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modelscope_api as ms  # noqa: E402

VERIFY_COUNT = 3
VERIFY_INTERVAL = 30          # seconds between readiness probes in one run
COOLDOWN_SECONDS = 4 * 3600   # no recovery more often than this
MAX_RECOVERIES_24H = 3
DEPLOY_RETRIES = 3


def log(message: str) -> None:
    print(message, flush=True)


def load_state(path: str) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {'recoveries': []}


def save_state(path: str, state: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(state))


def deploy_with_retry() -> bool:
    for attempt in range(1, DEPLOY_RETRIES + 1):
        try:
            result = ms.trigger_deploy()
            log(f'deploy accepted (attempt {attempt}): '
                f'{json.dumps(result)[:120]}')
            return True
        except ms.ApiError as exc:
            log(f'deploy attempt {attempt} failed: {exc}')
            time.sleep(10)
    return False


def readiness_failing() -> bool:
    """VERIFY_COUNT consecutive readiness misses within this run.

    A connection-level failure (status 0) is a VANTAGE blind spot, not
    evidence about the service: GitHub Actions runners cannot reach
    *.ms.show at all. Counting those misses as readiness failures made the
    keepalive redeploy the space every tick and kill live user sessions
    (2026-09-15 05:34 incident). Unreachable probes therefore never trigger
    a recovery; only REAL HTTP statuses (e.g. 503 while Running) do.
    """
    failures = 0
    unreachable = 0
    for _ in range(VERIFY_COUNT):
        try:
            state = ms.space_status()
        except ms.ApiError as exc:
            log(f'status unavailable: {exc}')
            state = 'Unknown'
        status = ms.readyz_status()
        log(f'probe: state={state} readyz={status or "unreachable"}')
        if status == 0:
            unreachable += 1
        elif state != 'Running' or status != 200:
            failures += 1
        else:
            return False
        if failures < VERIFY_COUNT and unreachable < VERIFY_COUNT:
            time.sleep(VERIFY_INTERVAL)
    if unreachable >= VERIFY_COUNT:
        log('readyz unreachable from this vantage point; trusting the '
            'platform state and not recovering on blindness')
        return False
    return failures >= VERIFY_COUNT


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--state-file', default='keepalive-state.json')
    args = parser.parse_args()
    state = load_state(args.state_file)
    now = time.time()
    state['recoveries'] = [ts for ts in state.get('recoveries', [])
                           if now - ts < 24 * 3600][-MAX_RECOVERIES_24H:]

    try:
        space = ms.space_status()
    except ms.ApiError as exc:
        log(f'::error::cannot read space status: {exc}')
        return 1
    log(f'space state: {space}')

    if space in ('Building', 'Deploying'):
        log('platform is building/deploying; not interfering')
        save_state(args.state_file, state)
        return 0

    if space != 'Stopped':
        if not readiness_failing():
            log('Running and ready; nothing to do')
            save_state(args.state_file, state)
            return 0
        if state['recoveries'] and now - state['recoveries'][-1] < COOLDOWN_SECONDS:
            log('unhealthy, but cooldown since the last recovery has not elapsed')
            save_state(args.state_file, state)
            return 0
        if len(state['recoveries']) >= MAX_RECOVERIES_24H:
            log('::error::unhealthy and the 24h recovery cap is reached; '
                'manual investigation required')
            save_state(args.state_file, state)
            return 1

    log('triggering recovery deploy')
    if not deploy_with_retry():
        log('::error::all deploy attempts failed')
        return 1
    if space != 'Stopped':
        state['recoveries'].append(now)
    save_state(args.state_file, state)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
