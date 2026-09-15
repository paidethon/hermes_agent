#!/bin/bash
# Temporary VNC-refusal diagnostic (ADR 0005 follow-up): samples who is
# connected to the loopback VNC, with which process, once a minute.
# Output is redacted-free (ports/process names only) and served via /readyz.
while true; do
    {
        date -u +%Y-%m-%dT%H:%M:%SZ
        echo '--- listeners/connections on 5901 ---'
        ss -tnp 2>/dev/null | grep -E '5901|State' || true
        echo '--- vnc/websockify processes ---'
        ps -eo pid,ppid,user,stat,etime,args | grep -E 'Xtigervnc|websockify' | grep -v grep || true
        echo '--- supervisor ---'
        /usr/bin/supervisorctl -c /run/zephyr/supervisord.conf status 2>&1 || true
    } > /run/zephyr/diag-vnc.txt 2>&1
    chmod 644 /run/zephyr/diag-vnc.txt
    sleep 60
done
