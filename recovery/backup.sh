#!/bin/bash
# Run as root in a maintenance window; freezes all application writers.
# Output is a local consistency snapshot, NOT an off-site backup.
set -euo pipefail
umask 077
root="${DATA_ROOT:-/mnt/workspace/zephyr-v2}"
if [ "$(id -u)" != 0 ]; then
    echo 'Run this backup through the space administrative terminal as root.' >&2
    exit 1
fi
case "$root" in
    /mnt/workspace/zephyr-v2) ;;
    *) echo 'Review this script for a custom DATA_ROOT before backing up.' >&2; exit 1 ;;
esac
ctl=(/usr/bin/supervisorctl -c /run/zephyr/supervisord.conf)
dest=/mnt/workspace/recovery-backups
mkdir -p "$dest"
chmod 700 "$dest"
file="$dest/hermes-$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
if [ -e "$file" ]; then exit 1; fi
# Run from the platform administrative terminal, NOT from noVNC: the desktop is stopped.
resume() {
    "${ctl[@]}" start auth vnc desktop novnc studio health nginx watchdog >/dev/null || true
}
trap resume EXIT
# The watchdog must be stopped FIRST: it would otherwise fight the backup by
# restarting or repairing the services being frozen.
"${ctl[@]}" stop watchdog nginx health studio novnc desktop vnc auth
# Include Chrome and any independent CLI/agent processes spawned from the desktop.
# Never snapshot live SQLite databases by copying only their .db files.
if pgrep -u 1001 >/dev/null; then
    pkill -TERM -u 1001 || true
    for n in $(seq 1 20); do
        pgrep -u 1001 >/dev/null || break
        sleep 1
    done
fi
if pgrep -u 1001 >/dev/null; then
    echo 'A desktop-user process is still running; snapshot aborted, not marked successful.' >&2
    exit 1
fi
tar -czf "$file.partial" -C /mnt/workspace zephyr-v2
tar -tzf "$file.partial" >/dev/null
mv "$file.partial" "$file"
sha256sum "$file" > "$file.sha256"
printf 'Snapshot ready: %s\nContains API credentials and browser profiles; encrypt before off-site copy.\n' "$file"
