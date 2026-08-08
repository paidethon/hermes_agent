#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — Health Check
# =============================================================================
# 容器健康检查脚本，由 Docker HEALTHCHECK 调用
# 检查项：
#   1. Nginx :7860 响应
#   2. Supervisord 运行中
#   3. 关键进程存活
#
# 维护者：海豚-容器工程师
# =============================================================================

set -euo pipefail

NGINX_URL="http://127.0.0.1:7860/health"

# ---------------------------------------------------------------------------
# 1. Nginx HTTP 响应
# ---------------------------------------------------------------------------
check_nginx() {
    local http_code
    http_code=$(curl -sf -o /dev/null -w "%{http_code}" "${NGINX_URL}" 2>/dev/null || echo "000")
    if [ "$http_code" != "200" ]; then
        echo "FAIL: Nginx not responding (HTTP ${http_code})"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# 2. Supervisord 状态
# ---------------------------------------------------------------------------
check_supervisor() {
    if ! supervisorctl status >/dev/null 2>&1; then
        echo "FAIL: supervisord not running"
        return 1
    fi
    return 0
}

# ---------------------------------------------------------------------------
# 3. 关键进程检查
# ---------------------------------------------------------------------------
check_processes() {
    local errors=0

    # Nginx
    if ! pgrep -x nginx >/dev/null 2>&1; then
        echo "WARN: nginx process not found"
        errors=$((errors + 1))
    fi

    # VNC（ENABLE_LLAMA_CPP 等不影响 VNC）
    if ! pgrep -x Xvnc >/dev/null 2>&1; then
        echo "WARN: Xvnc process not found"
        errors=$((errors + 1))
    fi

    # noVNC
    if ! pgrep -f "novnc_proxy" >/dev/null 2>&1; then
        echo "WARN: novnc_proxy process not found"
        errors=$((errors + 1))
    fi

    # Hermes Gateway
    if ! pgrep -f "hermes.*gateway" >/dev/null 2>&1; then
        echo "WARN: hermes-gateway process not found"
        errors=$((errors + 1))
    fi

    return $errors
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    check_nginx || exit 1
    check_supervisor || exit 1
    check_processes || true  # 进程检查仅告警，不导致健康检查失败

    echo "OK"
    exit 0
}

main "$@"
