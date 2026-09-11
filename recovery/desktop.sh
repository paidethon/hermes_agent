#!/bin/bash
set -euo pipefail
for attempt in $(seq 1 60); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        exec dbus-run-session -- startplasma-x11
    fi
    sleep 1
done
echo 'X server did not become ready; refusing to start a broken desktop.' >&2
exit 1
