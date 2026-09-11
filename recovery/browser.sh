#!/bin/bash
set -euo pipefail
args=(--no-first-run --no-default-browser-check --disable-dev-shm-usage)
if [ "${CHROME_NO_SANDBOX:-0}" = 1 ]; then
    echo 'WARNING: Chrome sandbox explicitly disabled. Do not browse untrusted content.' >&2
    args+=(--no-sandbox)
fi
if [ "$#" -eq 0 ]; then
    set -- http://127.0.0.1:8648
fi
exec /usr/bin/google-chrome-stable "${args[@]}" "$@"
