#!/bin/bash
set -euo pipefail
export NODE_ENV=production PORT=8648 BIND_HOST=127.0.0.1
export HERMES_WEB_UI_HOME="${DATA_ROOT}/studio"
export HERMES_WEB_UI_DISABLE_GATEWAY_AUTOSTART=1
export HERMES_BIN=/opt/hermes-venv/bin/hermes
export HERMES_HOME="${DATA_ROOT}/hermes"
cd /opt/hermes-studio
exec node dist/server/index.js
