#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — Backup Script
# =============================================================================
# rclone → OneDrive 备份（2026-08-09 起移除 crypt 加密层，直接明文写入）
# 用法：
#   ./backup.sh           # 全量备份
#   ./backup.sh hourly     # 每小时增量备份
#   ./backup.sh daily      # 每日全量备份
#   ./backup.sh manual     # 手动触发
#
# 可通过 cron 或 supervisord 定时调用
# 维护者：海豚-容器工程师
# =============================================================================

set -euo pipefail

PERSIST_ROOT="/mnt/workspace/zephyr"
RCLONE_CONF="${PERSIST_ROOT}/config/rclone.conf"
REMOTE="onedrive:zephyr-backup"
LOG_PREFIX="[backup]"

MODE="${1:-manual}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")

log()  { echo "${LOG_PREFIX} $*"; }
warn() { echo "${LOG_PREFIX} [WARN] $*" >&2; }
fail() { echo "${LOG_PREFIX} [ERROR] $*" >&2; exit 1; }

# 检查配置
if [ ! -f "$RCLONE_CONF" ]; then
    fail "rclone.conf not found at ${RCLONE_CONF}"
fi

# 检查 rclone 远程可用
if ! rclone --config="$RCLONE_CONF" listremotes | grep -q "^onedrive:$"; then
    fail "onedrive remote not configured in rclone.conf"
fi

# ---------------------------------------------------------------------------
# 备份目录定义
# ---------------------------------------------------------------------------
backup_paths=(
    "${PERSIST_ROOT}/hermes"
    "${PERSIST_ROOT}/hermes-studio"
    "${PERSIST_ROOT}/open-webui"
    "${PERSIST_ROOT}/config"
    "${PERSIST_ROOT}/projects"
    "${PERSIST_ROOT}/desktop"
)

# 排除规则
EXCLUDES=(
    "--exclude"
    "**__pycache__/**"
    "--exclude"
    "**node_modules/**"
    "--exclude"
    "**.cache/**"
    "--exclude"
    "**models/**"
    "--exclude"
    "**backups/**"
    "--exclude"
    "**.log"
)

# ---------------------------------------------------------------------------
# 执行备份
# ---------------------------------------------------------------------------
do_backup() {
    local target="${REMOTE}/${MODE}_${TIMESTAMP}"

    log "Starting ${MODE} backup to ${target}"
    log "Paths: ${backup_paths[*]}"

    for path in "${backup_paths[@]}"; do
        if [ ! -d "$path" ]; then
            warn "Path not found, skipping: ${path}"
            continue
        fi

        local basename
        basename=$(basename "$path")
        local dest="${target}/${basename}"

        log "Backing up: ${path} → ${dest}"

        rclone --config="$RCLONE_CONF" copy \
            "$path" "$dest" \
            "${EXCLUDES[@]}" \
            --transfers 4 \
            --checkers 8 \
            --stats 1m \
            --stats-log-level NOTICE \
            --log-file "${PERSIST_ROOT}/backups/${MODE}_backup_${TIMESTAMP}.log" \
            2>&1 || warn "Failed to backup ${path}"
    done

    # 创建备份清单
    rclone --config="$RCLONE_CONF" lsd "${target}" > \
        "${PERSIST_ROOT}/backups/${MODE}_manifest_${TIMESTAMP}.txt" 2>/dev/null || true

    log "Backup complete: ${target}"

    # 清理旧备份（保留最近 7 个 hourly + 7 个 daily）
    cleanup_old_backups

    # 更新最新备份标记
    echo "${MODE}_${TIMESTAMP}" > "${PERSIST_ROOT}/.last_backup"
    log "Last backup marker updated"
}

# ---------------------------------------------------------------------------
# 清理旧备份
# ---------------------------------------------------------------------------
cleanup_old_backups() {
    log "Cleaning old backups..."

    # 保留最近 7 个 hourly
    rclone --config="$RCLONE_CONF" lsd "${REMOTE}" 2>/dev/null | \
        grep "hourly_" | sort -r | tail -n +8 | while read -r dir; do
        local name=$(echo "$dir" | awk '{print $NF}')
        log "Removing old hourly backup: ${name}"
        rclone --config="$RCLONE_CONF" purge "${REMOTE}/${name}" 2>/dev/null || true
    done

    # 保留最近 7 个 daily
    rclone --config="$RCLONE_CONF" lsd "${REMOTE}" 2>/dev/null | \
        grep "daily_" | sort -r | tail -n +8 | while read -r dir; do
        local name=$(echo "$dir" | awk '{print $NF}')
        log "Removing old daily backup: ${name}"
        rclone --config="$RCLONE_CONF" purge "${REMOTE}/${name}" 2>/dev/null || true
    done

    log "Cleanup complete"
}

# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
mkdir -p "${PERSIST_ROOT}/backups/${MODE}"
do_backup
