#!/bin/bash
set -euo pipefail
umask 077
/usr/bin/python3 /opt/recovery/bootstrap.py
# Never inherit the portal password into the desktop or agent processes.
unset AUTH_PASSWORD DESKTOP_PASSWORD PORTAL_PASSWORD VNC_PASSWORD MODELSCOPE_TOKEN GITHUB_TOKEN GH_TOKEN
/usr/local/bin/authelia validate-config --config /run/zephyr/authelia.yml
/usr/sbin/nginx -t -c /run/zephyr/nginx.conf
exec /usr/bin/supervisord -c /run/zephyr/supervisord.conf
