#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — Restore Script
# =============================================================================
# 从 OneDrive 备份恢复数据（2026-08-09 起移除 crypt 加密层，直接读取明文）
# 用法：
#   ./restore.sh                    # 恢复最新备份
#   ./restore.sh hourly_20260808_1  # 恢复指定备份
#   ./restore.sh --list             # 列出可用备份
#
# 维护者：海豚-容器工程师
# =============================================================================

set -euo pipefail

PERSIST_ROOT="/mnt/workspace/zephyr"
RCLONE_CONF="${PERSIST_ROOT}/config/rclone.conf"
REMOTE="onedrive:zephyr-backup"
LOG_PREFIX="[restore]"

log()  { echo "${LOG_PREFIX} $*"; }
warn() { echo "${LOG_PREFIX} [WARN] $*" >&2; }
fail() { echo "${LOG_PREFIX} [ERROR] $*" >&2; exit 1; }

# 检查配置
if [ ! -f "$RCLONE_CONF" ]; then
    fail "rclone.conf not found at ${RCLONE_CONF}"
fi

# ---------------------------------------------------------------------------
# 列出可用备份
# ---------------------------------------------------------------------------
list_backups() {
    log "Available backups on OneDrive:"
    echo "----------------------------------------"
    rclone --config="$RCLONE_CONF" lsd "${REMOTE}" 2>/dev/null | \
        awk '{print $NF}' | sort -r
    echo "----------------------------------------"
    log "Use: ./restore.sh <backup_name>"
}

# ---------------------------------------------------------------------------
# 恢复备份
# ---------------------------------------------------------------------------
do_restore() {
    local backup_name="$1"
    local target="${REMOTE}/${backup_name}"

    # 验证备份存在
    if ! rclone --config="$RCLONE_CONF" lsd "${target}" >/dev/null 2>&1; then
        fail "Backup not found: ${backup_name}"
    fi

    log "Restoring from: ${target}"
    log "Target directory: ${PERSIST_ROOT}"

    # 停止关键服务（防止文件冲突）
    warn "Stopping services before restore..."
    supervisorctl stop hermes-gateway hermes-studio open-webui 2>/dev/null || true

    # 恢复数据
    rclone --config="$RCLONE_CONF" copy \
        "$target" "${PERSIST_ROOT}" \
        --transfers 4 \
        --checkers 8 \
        --progress || fail "Restore failed"

    # 修复权限
    log "Fixing permissions..."
    chown -R hermes:hermes "${PERSIST_ROOT}/hermes" 2>/dev/null || true
    chown -R hermes:hermes "${PERSIST_ROOT}/hermes-studio" 2>/dev/null || true
    chown -R hermes:hermes "${PERSIST_ROOT}/config/hermes-seed" 2>/dev/null || true
    chmod 600 "${PERSIST_ROOT}/config/rclone.conf" 2>/dev/null || true
    chmod 600 "/etc/nginx/.htpasswd" 2>/dev/null || true
    chmod 600 "/root/.vnc/passwd" 2>/dev/null || true

    # 标记已恢复
    touch "${PERSIST_ROOT}/.restored"

    # 重启服务
    log "Restarting services..."
    supervisorctl start hermes-gateway hermes-studio open-webui 2>/dev/null || true

    log "Restore complete: ${backup_name}"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
case "${1:-}" in
    --list|list)
        list_backups
        ;;
    "")
        # 无参数：查找最新备份
        log "Finding latest backup..."
        LATEST=$(rclone --config="$RCLONE_CONF" lsd "${REMOTE}" 2>/dev/null | \
            awk '{print $NF}' | sort -r | head -1)
        if [ -z "$LATEST" ]; then
            fail "No backups found on OneDrive"
        fi
        log "Latest backup: ${LATEST}"
        do_restore "$LATEST"
        ;;
    *)
        do_restore "$1"
        ;;
esac
