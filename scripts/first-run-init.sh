#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — First Run Initializer
# =============================================================================
# 首次启动时执行的初始化逻辑：
#   1. 检查 / 恢复 OneDrive 加密备份
#   2. 检查 / 下载 Qwen3 GGUF 模型
#   3. 生成 Hermes 种子配置（如不存在）
#   4. 初始化 Open WebUI 默认设置
#
# 此脚本由 entrypoint.sh 在 init_persistence 之后调用
# （或直接在 entrypoint.sh 末尾 exec supervisord 之前 source）
#
# 维护者：海豚-容器工程师
# =============================================================================

set -euo pipefail

PERSIST_ROOT="/mnt/workspace/zephyr"
LOG_PREFIX="[first-run]"

log()  { echo "${LOG_PREFIX} $*"; }
warn() { echo "${LOG_PREFIX} [WARN] $*" >&2; }

# ---------------------------------------------------------------------------
# 1. 恢复 OneDrive 加密备份（首次部署时）
# ---------------------------------------------------------------------------
restore_from_onedrive() {
    local rclone_conf="${PERSIST_ROOT}/config/rclone.conf"
    local restore_flag="${PERSIST_ROOT}/.restored"

    # 已经恢复过，跳过
    if [ -f "$restore_flag" ]; then
        log "Backup already restored, skipping"
        return 0
    fi

    # 没有配置文件，跳过
    if [ ! -f "$rclone_conf" ]; then
        log "No rclone.conf, skipping restore"
        return 0
    fi

    log "Checking OneDrive for backup..."
    local backup_exists
    backup_exists=$(rclone --config="$rclone_conf" lsf crypt: 2>/dev/null | head -1 || echo "")

    if [ -n "$backup_exists" ]; then
        log "Backup found on OneDrive, restoring..."
        rclone --config="$rclone_conf" copy \
            crypt:zephyr-backup \
            "${PERSIST_ROOT}" \
            --transfers 4 \
            --checkers 8 \
            --progress || {
            warn "Restore failed, continuing with fresh state"
            return 0
        }
        touch "$restore_flag"
        log "Restore complete"
    else
        log "No backup on OneDrive, starting fresh"
        touch "$restore_flag"
    fi
}

# ---------------------------------------------------------------------------
# 2. 检查 / 下载 Qwen3 GGUF 模型
# ---------------------------------------------------------------------------
# 修正（极客-AI模型通指出）：
#   方案文档写的 Qwen/Qwen3-8B-GGUF 不存在，实际仓库是 unsloth/Qwen3-8B-GGUF
#   文件名是 Qwen3-8B-Q4_K_M.gguf（大写 Q）
# supervisord.conf 中模型路径需要与这里一致
# ---------------------------------------------------------------------------
ensure_model() {
    local model_dir="${PERSIST_ROOT}/models"
    local model_repo="unsloth/Qwen3-8B-GGUF"
    local model_file="Qwen3-8B-Q4_K_M.gguf"
    local expected_path="${model_dir}/${model_repo}/${model_file}"

    mkdir -p "${model_dir}/${model_repo}"

    # 如果已有模型文件，跳过
    if [ -f "$expected_path" ]; then
        log "Model already exists: ${expected_path}"
        return 0
    fi

    # 检查构建时预下载的模型
    local preloaded_model="/opt/models/${model_repo}/${model_file}"
    if [ -f "$preloaded_model" ]; then
        log "Copying preloaded model from image..."
        cp "$preloaded_model" "$expected_path"
        log "Model copied: ${expected_path}"
        return 0
    fi

    # 运行时下载（调用极客-AI模型通提供的脚本）
    if [ -x /opt/zephyr/scripts/model-download.sh ]; then
        log "Running model-download.sh..."
        /opt/zephyr/scripts/model-download.sh || {
            warn "Model download failed, llama.cpp will not start"
            warn "You can manually run: /opt/zephyr/scripts/model-download.sh"
            return 1
        }
    else
        log "Downloading Qwen3-8B-Q4_K_M GGUF (≈5GB)..."
        export MODELSCOPE_CACHE="${model_dir}"
        modelscope download \
            --model "$model_repo" \
            --include "$model_file" \
            --local_dir "${model_dir}/${model_repo}" || {
            warn "Model download failed, llama.cpp will not start"
            return 1
        }
    fi

    # 验证文件存在
    if [ -f "$expected_path" ]; then
        log "Model ready: ${expected_path}"
    else
        warn "Model file not found at expected path: ${expected_path}"
        return 1
    fi
}

# ---------------------------------------------------------------------------
# 3. 生成 Hermes 种子配置（如不存在）
# ---------------------------------------------------------------------------
ensure_hermes_seed() {
    local seed_dir="/opt/hermes-seed"
    local config_dir="${PERSIST_ROOT}/config/hermes-seed"

    if [ ! -d "$seed_dir" ]; then
        return 0
    fi

    mkdir -p "$config_dir"

    # 如果配置不存在，从种子拷贝
    if [ ! -f "${config_dir}/config.yaml" ]; then
        log "Seeding Hermes config..."
        cp -a "${seed_dir}/." "$config_dir/"
        chown -R hermes:hermes "$config_dir"
        log "Hermes seed config deployed"
    fi
}

# ---------------------------------------------------------------------------
# 4. 初始化 Open WebUI 数据目录
# ---------------------------------------------------------------------------
ensure_open_webui() {
    local data_dir="${PERSIST_ROOT}/open-webui"

    if [ ! -d "$data_dir" ]; then
        mkdir -p "$data_dir"
    fi

    # 确保 hermes 用户有读取权限
    chmod 755 "$data_dir"
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    log "=== First Run Initialization ==="

    restore_from_onedrive
    ensure_model || true
    ensure_hermes_seed
    ensure_open_webui

    log "=== First Run Complete ==="
}

main "$@"
