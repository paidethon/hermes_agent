#!/bin/bash
# /opt/recovery/diagnose.sh — one-shot sanitized diagnostic bundle.
# Run as root from the platform administrative terminal (the desktop terminal
# cannot use supervisorctl: /run/zephyr/supervisord.conf is root 0600).
# Output contains commit ids, process tables, ports and probe results only;
# every line passes a secret redactor and no process environment is dumped.
# Usage: diagnose.sh [--save]   (--save writes DATA_ROOT/diagnostics/, keeps 10)
set -uo pipefail
umask 077

DATA_ROOT="${DATA_ROOT:-/mnt/workspace/zephyr-v2}"
DIAG_DIR="${DATA_ROOT}/diagnostics"
KEEP=10
REDACT='s/sk-[A-Za-z0-9_-]{12,}/[REDACTED-key]/g;
        s/ghp_[A-Za-z0-9]{20,}/[REDACTED-pat]/g;
        s/github_pat_[A-Za-z0-9_]{20,}/[REDACTED-pat]/g;
        s/ms-[0-9a-f-]{16,}/[REDACTED-ms-token]/g;
        s/[Bb]earer +[^ ]+/[REDACTED-bearer]/g'

out() { sed -E "$REDACT"; }
section() { printf '\n=== %s ===\n' "$1" | out; }

save=0
[ "${1:-}" = "--save" ] && save=1
TMP="$(mktemp /tmp/diagnose.XXXXXX)"
trap 'rm -f "$TMP"' EXIT

{
    section "identity"
    for f in /opt/versions/app.txt /opt/versions/hermes.txt /opt/versions/studio.txt; do
        [ -f "$f" ] && printf '%s: %s\n' "$(basename "$f" .txt)" "$(cat "$f")" | out
    done
    [ -f /opt/versions/app.txt ] && \
        printf 'image build time: %s\n' "$(stat -c %y /opt/versions/app.txt 2>/dev/null | cut -d. -f1)" | out
    printf 'kernel: %s\n' "$(uname -r)" | out

    section "health (liveness) / readiness"
    curl -fsS --max-time 5 http://127.0.0.1:7860/healthz | out || echo 'healthz: FAILED' | out
    printf '\n' | out
    curl -fsS --max-time 10 http://127.0.0.1:7860/readyz | out || echo 'readyz: FAILED' | out
    printf '\n' | out

    section "services (supervisord)"
    /usr/bin/supervisorctl -c /run/zephyr/supervisord.conf status 2>&1 | out

    section "desktop detail"
    /usr/bin/python3 /opt/recovery/health.py --once 2>&1 | out
    printf 'plasmashell: %s\n' "$(pgrep -u 1001 -x plasmashell >/dev/null && echo running || echo MISSING)" | out
    printf 'kwin_x11:    %s\n' "$(pgrep -u 1001 -x kwin_x11 >/dev/null && echo running || echo MISSING)" | out
    if env DISPLAY=:1 XAUTHORITY=/run/user/1001/.Xauthority \
        /usr/sbin/gosu hermes xprop -root _NET_SUPPORTING_WM_CHECK >/tmp/wd-xprop 2>&1; then
        printf 'wm root:     %s\n' "$(cat /tmp/wd-xprop)" | out
    else
        printf 'wm root:     NOT CLAIMED (%s)\n' "$(head -c 120 /tmp/wd-xprop)" | out
    fi
    rm -f /tmp/wd-xprop
    if [ -f /run/zephyr/watchdog-status.json ]; then
        printf 'watchdog: %s\n' "$(cat /run/zephyr/watchdog-status.json)" | out
    fi

    section "memory"
    free -m | out

    section "disk"
    df -h /mnt/workspace /run /tmp 2>/dev/null | out

    section "listening ports"
    ss -ltnp 2>/dev/null | out

    section "top processes by memory"
    ps -eo user,pid,ppid,stat,pmem,rss,etime,comm --sort=-rss 2>/dev/null | head -n 15 | out

    section "diagnostics bundles on disk"
    ls -lt "$DIAG_DIR" 2>/dev/null | head -n "$KEEP" | out

    section "recent logs"
    echo 'In-container services log to the platform container log (supervisor -> stdout).' | out
    echo 'From any docker context: docker logs --tail 200 <container>' | out
} >> "$TMP"

if [ "$save" = 1 ]; then
    mkdir -p "$DIAG_DIR"
    BUNDLE="$DIAG_DIR/diagnose-$(date -u +%Y%m%dT%H%M%SZ).txt"
    cp "$TMP" "$BUNDLE" && chmod 600 "$BUNDLE"
    find "$DIAG_DIR" -maxdepth 1 -name 'diagnose-*' -type f 2>/dev/null | sort | \
        head -n -"$KEEP" | while IFS= read -r old; do rm -f -- "$old"; done
    printf 'diagnose: bundle written to %s\n' "$BUNDLE"
else
    cat "$TMP"
fi
