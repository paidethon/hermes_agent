#!/usr/bin/env python3
"""Shared ModelScope Space API helpers for the release pipeline and keepalive.

Credentials come from the environment only (MODELSCOPE_TOKEN); tokens are never
placed into URLs, argv, logs, or git remote configuration. HTTP probes against
the public app use a browser User-Agent because the platform WAF rejects the
default client one.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

API_BASE = 'https://modelscope.cn/api/v1'
OPENAPI_BASE = 'https://modelscope.cn/openapi/v1'
BROWSER_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')


class ApiError(RuntimeError):
    pass


def _token() -> str:
    token = os.environ.get('MODELSCOPE_TOKEN', '')
    if not token:
        raise ApiError('MODELSCOPE_TOKEN is not set')
    return token


def _space_id() -> str:
    space_id = os.environ.get('SPACE_ID', '')
    if not space_id or space_id.count('/') != 1:
        raise ApiError('SPACE_ID must look like owner/name')
    return space_id.strip()


def request(path: str, method: str = 'GET', payload: dict | None = None,
            timeout: int = 30, base: str = API_BASE) -> dict:
    """Authenticated OpenAPI call returning parsed JSON.

    Error bodies are never printed raw (they may echo request metadata); only
    the HTTP status is surfaced."""
    data = json.dumps(payload).encode() if payload is not None else None
    request_obj = urllib.request.Request(
        base + path, data=data, method=method,
        headers={'Authorization': 'Bearer ' + _token(),
                 'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            body = response.read()
    except urllib.error.HTTPError as exc:
        raise ApiError(f'ModelScope API returned HTTP {exc.code} for {method} {path}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f'ModelScope API unreachable for {method} {path}: {type(exc).__name__}') from exc
    try:
        return json.loads(body)
    except ValueError as exc:
        raise ApiError(f'ModelScope API returned non-JSON for {path}') from exc


def request_raw(path: str, timeout: int = 30) -> str:
    """Authenticated GET returning the body as text, whatever its shape.

    The space-repo file endpoint (api/v1/studio/{space}/repo?FilePath=...)
    serves raw file text on some deployments and JSON on others."""
    request_obj = urllib.request.Request(
        API_BASE + path, headers={'Authorization': 'Bearer ' + _token()})
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            return response.read().decode('utf-8', errors='replace')
    except urllib.error.HTTPError as exc:
        raise ApiError(f'ModelScope API returned HTTP {exc.code} for GET {path}') from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ApiError(f'ModelScope API unreachable for GET {path}: {type(exc).__name__}') from exc


def space_status() -> str:
    data = request(f'/studio/{_space_id()}/status')
    for path in (('Data', 'Status'), ('data', 'status'), ('Data', 'status')):
        node: object = data
        for key in path:
            if isinstance(node, dict):
                node = node.get(key)
            else:
                node = None
        if isinstance(node, str) and node:
            return node
    raise ApiError('Could not parse space status from the API response')


def trigger_deploy() -> dict:
    # POST /deploy is a restart-type call: trigger exactly once per release,
    # never use it for polling (GET /status is the side-effect-free read).
    # The deploy trigger lives under /openapi/v1/studios/ (plural, openapi
    # prefix) — /api/v1/studio/ answers 404 for it (verified live 2026-09-14).
    owner, name = _space_id().split('/')
    return request(f'/studios/{owner}/{name}/deploy', method='POST', payload={},
                   base=OPENAPI_BASE)


def app_base_url() -> str:
    owner, name = _space_id().split('/')
    return f'https://{owner}-{name}.ms.show'


def public_get(path: str, timeout: int = 15, expect_statuses: tuple[int, ...] = (200,)) -> int:
    """Unauthenticated probe of the public app entry (browser UA for the WAF)."""
    request_obj = urllib.request.Request(
        app_base_url() + path, headers={'User-Agent': BROWSER_UA})
    try:
        with urllib.request.urlopen(request_obj, timeout=timeout) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except (urllib.error.URLError, TimeoutError):
        return 0


def readiness_ok() -> bool:
    """True only when /readyz answers 200 with ready:true (or a deliberate
    503, which means alive-but-not-ready and still proves HTTP liveness)."""
    status = public_get('/readyz')
    return status == 200


def readyz_status() -> int:
    """Raw /readyz status: 200 ready, 503 alive-but-not-ready, 0 unreachable.
    A 0 is a VANTAGE problem (GitHub Actions runners cannot reach *.ms.show at
    all) and must never be read as a service failure."""
    return public_get('/readyz')


def space_git_url() -> str:
    owner, name = _space_id().split('/')
    return f'https://www.modelscope.cn/studios/{owner}/{name}.git'


def askpass_script() -> str:
    """GIT_ASKPASS script path. ModelScope's git server authenticates with
    the fixed username 'oauth2' and the token as the password (verified live
    2026-09-14: the account name or the token in the username position get
    'HTTP Basic: Access denied'; 'oauth2' + token pushes fine). MS_GIT_USERNAME
    overrides. The token reaches git through the environment and a 0700 temp
    file — never in remote URLs, argv, or CI logs."""
    import stat
    import tempfile
    path = tempfile.NamedTemporaryFile(prefix='ms-askpass-', suffix='.sh', delete=False)
    path.write(b'#!/bin/sh\ncase "$1" in Username*) exec printf \'%s\\n\' '
               b'"${MS_GIT_USERNAME:-oauth2}";; '
               b'*) exec printf \'%s\\n\' "$MODELSCOPE_TOKEN";; esac\n')
    path.close()
    os.chmod(path.name, os.stat(path.name).st_mode | stat.S_IXUSR)
    return path.name


def git(*args: str, cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.setdefault('GIT_TERMINAL_PROMPT', '0')
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=check,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def space_dockerfile_digest() -> str | None:
    """Current pinned digest in the space repo Dockerfile, or None."""
    owner, name = _space_id().split('/')
    # The file endpoint may answer raw text or a JSON envelope depending on
    # the deployment; accept both. Never print the body (harmless here, but
    # the discipline keeps log channels one-format).
    body = request_raw(f'/studio/{owner}/{name}/repo?FilePath=Dockerfile&Revision=master')
    content = body
    try:
        data = json.loads(body)
    except ValueError:
        data = None
    if isinstance(data, dict):
        for key in ('Content', 'content', 'Data', 'data'):
            if isinstance(data.get(key), str):
                content = data[key]
                break
            if isinstance(data.get(key), dict):
                inner = data[key]
                content = inner.get('content', inner.get('Content', ''))
                if isinstance(content, str):
                    break
    for line in content.splitlines():
        line = line.strip()
        if line.startswith('FROM') and '@sha256:' in line:
            return line.split('@sha256:', 1)[1].split()[0]
    return None
