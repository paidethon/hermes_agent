#!/bin/bash
set -euo pipefail
# Refuse to boot a half-working desktop: without a window manager the session
# still shows a taskbar, but windows have no title bar and cannot be moved,
# maximized, minimized, or closed. Fail loudly instead.
for binary in dbus-run-session startplasma-x11 kwin_x11 plasmashell xdpyinfo; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        echo "FATAL: required KDE runtime binary missing: $binary" >&2
        exit 1
    fi
done
attempts="${DESKTOP_X_WAIT_ATTEMPTS:-60}"
for attempt in $(seq 1 "$attempts"); do
    if xdpyinfo -display :1 >/dev/null 2>&1; then
        exec dbus-run-session -- startplasma-x11
    fi
    sleep 1
done
echo 'X server did not become ready; refusing to start a broken desktop.' >&2
exit 1
