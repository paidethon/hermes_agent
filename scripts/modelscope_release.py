#!/usr/bin/env python3
"""ModelScope Space release pipeline: sync → deploy → verify → rollback.

Called by .github/workflows/deploy-modelscope.yml after the GitHub CI has
published a new digest-pinned image. One release = exactly one deployment
commit in the space repo; a failed verification is answered by reverting that
single commit (never force push) and re-verifying the restored version.

Subcommands:
  sync                commit the new pinned Dockerfile to the space repo
  deploy-and-verify   trigger deploy, poll status + public health, rollback
                      on repeated readiness failure
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import modelscope_api as ms  # noqa: E402

POLL_INTERVAL = 30
BUILD_TIMEOUT = 25 * 60       # platform build (image pull) budget
READY_TIMEOUT = 8 * 60        # readiness probes after Running
READY_FAILURES_FOR_ROLLBACK = 3
VERIFY_PROBES = 3


def log(message: str) -> None:
    print(message, flush=True)


def load_deployment(deploy_dir: str) -> tuple[str, str]:
    raw = (Path(deploy_dir) / 'image-digest.txt').read_text().strip()
    # The CI writes the full RepoDigest (registry/repo@sha256:...); accept any
    # form that contains the 64-hex digest.
    found = re.search(r'sha256:([0-9a-f]{64})', raw)
    if not found:
        raise SystemExit(f'deployment artifact digest malformed: {raw[:40]}')
    source_commit = (Path(deploy_dir) / 'source-commit.txt').read_text().strip()
    return found.group(1), source_commit


def space_checkout(workroot: Path) -> Path:
    """Shallow clone of the space repo, authenticated via GIT_ASKPASS."""
    askpass = ms.askpass_script()
    checkout = workroot / 'space-repo'
    try:
        log('cloning space repo (credentials via GIT_ASKPASS, not URLs)')
        os.environ['GIT_ASKPASS'] = askpass
        result = ms.git('-c', 'credential.helper=', 'clone', '--depth', '5',
                        ms.space_git_url(), str(checkout), check=False)
        if result.returncode != 0:
            # Never echo git output: the remote URL could carry auth context.
            raise SystemExit('cloning the space repo failed (check MODELSCOPE_TOKEN '
                             'permissions); no git output printed by design')
    finally:
        os.environ.pop('GIT_ASKPASS', None)
        Path(askpass).unlink(missing_ok=True)
    ms.git('config', 'user.name', 'hermes-release-bot')
    ms.git('config', 'user.email', 'release-bot@users.noreply.github.com', cwd=str(checkout))
    return checkout


def cmd_sync(deploy_dir: str, github_sha: str, workdir: str) -> int:
    digest, source_commit = load_deployment(deploy_dir)
    pinned = Path(deploy_dir) / 'Dockerfile'
    text = pinned.read_text()
    if f'@sha256:{digest}' not in text:
        raise SystemExit('deployment Dockerfile does not match its digest file')

    current = ms.space_dockerfile_digest()
    log(f'space currently pins: {current or "(nothing)"}')
    if current and current == digest:
        log('space already runs this digest — nothing to deploy')
        return 0

    workroot = Path(workdir)
    workroot.mkdir(parents=True, exist_ok=True)
    checkout = space_checkout(workroot)
    old_sha = ms.git('rev-parse', 'HEAD', cwd=str(checkout)).stdout.strip()
    shutil.copyfile(pinned, checkout / 'Dockerfile')

    # Release metadata: identity of the exact build, no secrets. Versions come
    # from the Dockerfile pins at the built commit.
    hermes_ref = studio_ref = 'unknown'
    for line in text_for_commit(source_commit).splitlines():
        if line.startswith('ARG HERMES_REF='):
            hermes_ref = line.split('=', 1)[1].strip()
        if line.startswith('ARG STUDIO_REF='):
            studio_ref = line.split('=', 1)[1].strip()
    metadata = {
        'github_sha': github_sha or source_commit,
        'source_commit': source_commit,
        'image_digest': 'sha256:' + digest,
        'hermes_version': hermes_ref,
        'studio_version': studio_ref,
        'built_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    (checkout / 'deploy-metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')

    ms.git('add', 'Dockerfile', 'deploy-metadata.json', cwd=str(checkout))
    staged = ms.git('diff', '--cached', '--quiet', cwd=str(checkout), check=False)
    if staged.returncode == 0:
        log('space repo unchanged after sync; skipping commit')
        return 0
    ms.git('commit', '-m',
           f'deploy: sync paidethon/hermes_agent {github_sha or source_commit}',
           cwd=str(checkout))
    askpass = ms.askpass_script()
    try:
        os.environ['GIT_ASKPASS'] = askpass
        result = ms.git('push', 'origin', 'master', cwd=str(checkout), check=False)
    finally:
        os.environ.pop('GIT_ASKPASS', None)
        Path(askpass).unlink(missing_ok=True)
    if result.returncode != 0:
        raise SystemExit('pushing the space repo failed; deployment NOT triggered')
    new_sha = ms.git('rev-parse', 'HEAD', cwd=str(checkout)).stdout.strip()
    log(f'space repo: {old_sha} -> {new_sha}')
    Path(workroot / 'space-shas.txt').write_text(f'{old_sha} {new_sha}\n')
    return 0


def text_for_commit(source_commit: str) -> str:
    result = ms.git('show', f'{source_commit}:Dockerfile', check=False)
    return result.stdout if result.returncode == 0 else ''


def verify_once() -> tuple[bool, str]:
    """One readiness pass: platform state + public health + readiness."""
    state = ms.space_status()
    health = ms.public_get('/healthz')
    ready = ms.public_get('/readyz')
    protected = ms.public_get('/')
    ok = (state == 'Running' and health == 200 and ready == 200
          and protected in (200, 302))
    detail = f'state={state} healthz={health} readyz={ready} protected={protected}'
    return ok, detail


def cmd_deploy_and_verify(workdir: str) -> int:
    workroot = Path(workdir)
    shas = (workroot / 'space-shas.txt').read_text().split() if \
        (workroot / 'space-shas.txt').exists() else []
    old_sha = shas[0] if len(shas) >= 2 else None

    log('triggering deployment (single POST /deploy)')
    ms.trigger_deploy()

    log(f'polling build (timeout {BUILD_TIMEOUT}s)')
    deadline = time.monotonic() + BUILD_TIMEOUT
    while time.monotonic() < deadline:
        state = ms.space_status()
        if state == 'Running':
            break
        if state in ('BuildFailed', 'DeployFailed', 'Failed'):
            log(f'platform reports {state}; rolling back')
            return rollback(old_sha)
        time.sleep(POLL_INTERVAL)
    else:
        log('build did not reach Running in time; rolling back')
        return rollback(old_sha)

    failures = 0
    deadline = time.monotonic() + READY_TIMEOUT
    while time.monotonic() < deadline:
        ok, detail = verify_once()
        log(f'verify: {detail}')
        failures = 0 if ok else failures + 1
        if ok and failures == 0:
            log('release verified: Running + healthz + readyz + protected entry')
            return 0
        if failures >= READY_FAILURES_FOR_ROLLBACK:
            log('readiness failed repeatedly; rolling back')
            return rollback(old_sha)
        time.sleep(POLL_INTERVAL)
    log('readiness window expired; rolling back')
    return rollback(old_sha)


def rollback(old_sha: str | None) -> int:
    if not old_sha:
        log('ROLLBACK IMPOSSIBLE: no previous space SHA recorded. '
            'Manual intervention required; leaving the space as-is.')
        return 1
    workroot = Path(os.environ.get('RELEASE_WORKDIR', '.release'))
    checkout = workroot / 'space-repo'
    if not checkout.exists():
        checkout = space_checkout(workroot)
        ms.git('fetch', '--depth', '20', 'origin', 'master', cwd=str(checkout))
    try:
        ms.git('revert', '--no-edit', current_deployment_commit(checkout), cwd=str(checkout))
    except SystemExit:
        log('revert failed to run; aborting without further changes')
        return 1
    askpass = ms.askpass_script()
    try:
        os.environ['GIT_ASKPASS'] = askpass
        result = ms.git('push', 'origin', 'master', cwd=str(checkout), check=False)
    finally:
        os.environ.pop('GIT_ASKPASS', None)
        Path(askpass).unlink(missing_ok=True)
    if result.returncode != 0:
        log('rollback push failed; manual intervention required')
        return 1
    log('rollback commit pushed; re-deploying the previous version')
    ms.trigger_deploy()
    deadline = time.monotonic() + BUILD_TIMEOUT
    while time.monotonic() < deadline:
        if ms.space_status() == 'Running':
            break
        time.sleep(POLL_INTERVAL)
    else:
        log('rollback: previous version did not come back Running in time')
        return 1
    failures = 0
    for _ in range(VERIFY_PROBES):
        ok, detail = verify_once()
        log(f'rollback verify: {detail}')
        if ok:
            log('rollback verified: previous version is serving again')
            return 1  # release failed, but rollback succeeded: stay red
        failures += 1
        time.sleep(POLL_INTERVAL)
    log('rollback completed but verification still fails; manual intervention required')
    return 1


def current_deployment_commit(checkout: Path) -> str:
    """The most recent 'deploy: sync' commit (the one to revert)."""
    log_result = ms.git('log', '--format=%H %s', '-n', '10', cwd=str(checkout))
    for line in log_result.stdout.splitlines():
        sha, _, subject = line.partition(' ')
        if subject.startswith('deploy: sync'):
            return sha
    raise SystemExit('no deploy commit found to revert')


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sync = sub.add_parser('sync')
    sync.add_argument('--deploy-dir', required=True)
    sync.add_argument('--github-sha', default=os.environ.get('GITHUB_SHA', ''))
    sync.add_argument('--workdir', default=os.environ.get('RELEASE_WORKDIR', '.release'))
    deploy = sub.add_parser('deploy-and-verify')
    deploy.add_argument('--workdir', default=os.environ.get('RELEASE_WORKDIR', '.release'))
    args = parser.parse_args()
    if args.command == 'sync':
        return cmd_sync(args.deploy_dir, args.github_sha, args.workdir)
    return cmd_deploy_and_verify(args.workdir)


if __name__ == '__main__':
    raise SystemExit(main())
