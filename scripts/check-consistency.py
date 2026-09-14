#!/usr/bin/env python3
"""Cross-check that ports, env vars, and endpoints agree across the runtime code,
compose file, env template, and architecture docs. Stdlib only; exits non-zero on drift.

This is the automated answer to "does every description of the running system agree
with recovery/bootstrap.py, which is the machine source of truth".
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

failures: list[str] = []
notes: list[str] = []


def read(*parts: str) -> str:
    with open(os.path.join(ROOT, *parts), encoding='utf-8') as handle:
        return handle.read()


def fail(message: str) -> None:
    failures.append(message)


# --- 1. Env vars consumed by bootstrap.py -----------------------------------
bootstrap_src = read('recovery', 'bootstrap.py')
consumed = set(re.findall(r"os\.environ\.get\('([A-Z_]+)'", bootstrap_src))
if not consumed:
    fail('bootstrap.py: no os.environ.get() vars found — parser drift?')
# Consumed by the agent/Studio processes directly (injected env, never read by
# bootstrap); the template and compose must still carry them.
runtime_env = {'OPENAI_API_KEY'}

# Template must document every consumed var (VAR= line, value may be empty).
template = read('.env.recovery.example')
documented = set(re.findall(r'^([A-Z_]+)=', template, re.M))
missing_in_template = sorted(consumed - documented)
if missing_in_template:
    fail(f'.env.recovery.example is missing vars consumed by bootstrap.py: {missing_in_template}')
stale_in_template = sorted(documented - consumed - runtime_env)
if stale_in_template:
    fail(f'.env.recovery.example documents vars nobody reads: {stale_in_template}')

# --- 2. Compose passes only real vars, and all required ones ----------------
try:
    import yaml  # type: ignore
    compose = yaml.safe_load(read('docker-compose.yml'))
except ImportError:
    compose = None
    notes.append('PyYAML unavailable; compose env check skipped (CI installs it).')
if compose is not None:
    service = compose.get('services', {}).get('hermes-desktop')
    if not service:
        fail("docker-compose.yml: expected service 'hermes-desktop'")
    else:
        env = service.get('environment', {}) or {}
        unknown = sorted(set(env) - consumed - runtime_env)
        if unknown:
            fail(f'docker-compose.yml passes vars nobody reads: {unknown}')
        for required in ('PUBLIC_ORIGIN', 'AUTH_PASSWORD', 'VNC_PASSWORD', 'DESKTOP_PASSWORD'):
            if required not in env:
                fail(f'docker-compose.yml is missing required var {required}')
        legacy_args = re.findall(r'^\s{8}([A-Z_]+):', read('docker-compose.yml'), re.M)
        for banned in ('ENABLE_FLOWISE', 'ENABLE_LLAMA_CPP', 'PRELOAD_QWEN3_8B',
                       'PORTAL_PASSWORD', 'PORTAL_USER', 'LLAMA_CPP_THREADS'):
            if banned in env:
                fail(f'docker-compose.yml still passes legacy var {banned}')

# --- 3. Secret hygiene: consumed secrets must be unset before services start -
entrypoint = read('recovery', 'entrypoint.sh')
unset_block = re.search(r'^unset (.+)$', entrypoint, re.M)
if not unset_block:
    fail('recovery/entrypoint.sh: no unset line found')
else:
    unset_vars = set(unset_block.group(1).split())
    for var in sorted(consumed):
        if re.search(r'(PASSWORD|TOKEN|SECRET)', var) and var not in unset_vars:
            fail(f'{var} is consumed but never unset in entrypoint.sh')
    # OPENAI_* are deliberately kept for the agent processes; everything else
    # matching the secret pattern must go.
    for var in sorted(unset_vars):
        if var not in consumed and var not in ('PORTAL_PASSWORD', 'MODELSCOPE_TOKEN',
                                               'GITHUB_TOKEN', 'GH_TOKEN'):
            notes.append(f'entrypoint unsets {var}, which bootstrap.py does not consume')

# --- 4. Ports agree across code, compose, and architecture doc ---------------
ports = {'7860': 'public nginx', '9091': 'authelia', '6080': 'novnc',
         '5901': 'vnc', '8648': 'studio', '9092': 'readyz backend'}
for port, role in ports.items():
    if port not in bootstrap_src:
        fail(f'port {port} ({role}) missing from bootstrap.py')
    if port not in read('docs', 'ARCHITECTURE.md'):
        fail(f'port {port} ({role}) missing from docs/ARCHITECTURE.md')
if '7860:7860' not in read('docker-compose.yml'):
    fail('docker-compose.yml does not publish 7860:7860')

# --- 5. The legacy /health endpoint must not reappear in active files --------
active_globs = [('recovery',), ('tests',), ('scripts',), ('.github', 'workflows')]
for parts in active_globs:
    directory = os.path.join(ROOT, *parts)
    for dirpath, dirnames, filenames in os.walk(directory):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            path = os.path.join(dirpath, name)
            try:
                text = open(path, encoding='utf-8').read()
            except (UnicodeDecodeError, OSError):
                continue
            rel = os.path.relpath(path, ROOT)
            # The defensive unset line in entrypoint.sh names legacy vars on purpose.
            text_scanned = '\n'.join(line for line in text.splitlines()
                                     if not line.strip().startswith('unset '))
            if re.search(r'["\']/health(?!z)', text_scanned):
                fail(f'{rel}: references legacy /health endpoint (use /healthz or /readyz)')
            for stale in ('PORTAL_PASSWORD', 'PORTAL_USER', 'ENABLE_FLOWISE',
                          'ENABLE_LLAMA_CPP', 'llama.cpp', 'FLOWISE_'):
                if stale in text_scanned and not rel.startswith(('tests' + os.sep + 'test_',
                                                         'scripts' + os.sep + 'check-consistency')):
                    fail(f'{rel}: active file references legacy symbol {stale}')

# Legacy sources of truth must stay under legacy/.
for moved in ('modelscope/', 'portal/', 'config/hermes-seed'):
    if os.path.exists(os.path.join(ROOT, moved)):
        fail(f'{moved} still exists at repo root — it belongs under legacy/')

# --- 6. Runtime modules a fresh checkout must never lose ---------------------
# (extended as new runtime entry points land)
for required in ('recovery/bootstrap.py', 'recovery/health.py', 'recovery/entrypoint.sh',
                 'recovery/desktop-watchdog.py', 'recovery/diagnose.sh',
                 'scripts/migrate-data.sh', 'scripts/smoke-container.sh',
                 '.env.recovery.example'):
    if not os.path.exists(os.path.join(ROOT, required)):
        fail(f'required runtime/doc file missing: {required}')

print('consistency notes:')
for note in notes:
    print(f'  - {note}')
if failures:
    print('\nconsistency FAILURES:')
    for item in failures:
        print(f'  - {item}')
    sys.exit(1)
print('\nconsistency: OK — ports, env vars, endpoints and file layout agree.')
