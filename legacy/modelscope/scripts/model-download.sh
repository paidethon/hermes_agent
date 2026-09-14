#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — ModelScope 模型预下载脚本
# =============================================================================
# 职责：
#   1. 安装 modelscope CLI（如未安装）
#   2. 下载 Qwen3-8B-Q4_K_M.gguf 到持久化目录
#   3. 校验文件完整性
#
# 依赖：pip / Python 3.11+
# 维护者：极客-AI模型通
#
# 重要修正（相比方案文档 §8.5）：
#   方案文档写的仓库名 `Qwen/Qwen3-8B-GGUF` 在魔搭社区不存在，
#   实际仓库是 `unsloth/Qwen3-8B-GGUF`（unsloth 量化维护）。
#   文件名是 `Qwen3-8B-Q4_K_M.gguf`（大写 Q，下划线分隔），不是小写。
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 环境变量（可通过 Docker ARG / Secrets 覆盖）
# ---------------------------------------------------------------------------
MODEL_DIR="${MODELSCOPE_CACHE:-/mnt/workspace/zephyr/models}"
MODELSCOPE_SDK_TOKEN="${MODELSCOPE_SDK_TOKEN:-}"   # 私有模型下载用，公开模型可不填

# 仓库与文件（修正后）
GGUF_REPO="unsloth/Qwen3-8B-GGUF"
GGUF_FILE="Qwen3-8B-Q4_K_M.gguf"
GGUF_EXPECTED_SIZE_GB=5.2    # 预估 ~5.2 GB
# §L1 修复：官方 SHA256（来源：modelscope.cn/api/v1/models/unsloth/Qwen3-8B-GGUF/repo/files）
GGUF_EXPECTED_SHA256="120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4"

GGUF_FULL_PATH="${MODEL_DIR}/${GGUF_REPO}/${GGUF_FILE}"

log()  { echo "[model-download] $*"; }
warn() { echo "[model-download] [WARN] $*" >&2; }
fail() { echo "[model-download] [ERROR] $*" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 1. 安装 modelscope CLI
# ---------------------------------------------------------------------------
install_modelscope_cli() {
    if command -v modelscope &>/dev/null; then
        log "modelscope CLI already installed: $(modelscope --version 2>&1 || echo 'ok')"
        return 0
    fi

    log "Installing modelscope CLI via pip..."
    pip install --no-cache-dir "modelscope==1.39.1"
    log "modelscope CLI installed: $(modelscope --version 2>&1 || echo 'ok')"
}

# ---------------------------------------------------------------------------
# 2. 下载 Qwen3-8B-Q4_K_M.gguf
# ---------------------------------------------------------------------------
download_model() {
    mkdir -p "${MODEL_DIR}"

    # 已存在则跳过
    if [ -f "$GGUF_FULL_PATH" ]; then
        local actual_size
        actual_size=$(stat -c '%s' "$GGUF_FULL_PATH" 2>/dev/null || echo 0)
        local actual_gb
        actual_gb=$(echo "scale=2; $actual_size / 1073741824" | bc 2>/dev/null || echo "?")
        log "Model already exists: ${GGUF_FULL_PATH} (~${actual_gb} GB), skipping download."
        return 0
    fi

    log "Downloading ${GGUF_REPO}/${GGUF_FILE} to ${MODEL_DIR}..."
    log "  repository: ${GGUF_REPO}"
    log "  file:       ${GGUF_FILE}"
    log "  target:     ${GGUF_FULL_PATH}"
    log "  expected:   ~${GGUF_EXPECTED_SIZE_GB} GB"

    # modelscope download 命令：
    #   --model    指定仓库 ID（组织/模型名）
    #   --include  只下载匹配的文件（支持 glob），避免下载全部量化版本
    #   --local_dir  指定下载目录
    #   MODELSCOPE_CACHE 环境变量控制缓存根目录
    #
    # §L2 修复：Token 通过临时文件传递，避免 export 到子进程环境
    #           防止 /proc/<PID>/environ 泄露
    local token_args=()
    if [ -n "$MODELSCOPE_SDK_TOKEN" ]; then
        token_file=$(mktemp)
        printf '%s' "$MODELSCOPE_SDK_TOKEN" > "$token_file"
        chmod 600 "$token_file"
        token_args=(--token "$(cat "$token_file")")
    fi

    modelscope download \
        --model "$GGUF_REPO" \
        --include "$GGUF_FILE" \
        --local_dir "${MODEL_DIR}/${GGUF_REPO}" \
        "${token_args[@]}"

    # 清理临时 token 文件
    if [ -n "${token_file:-}" ] && [ -f "$token_file" ]; then
        shred -u "$token_file" 2>/dev/null || rm -f "$token_file"
    fi

    # 校验文件存在
    if [ ! -f "$GGUF_FULL_PATH" ]; then
        fail "Download completed but file not found at ${GGUF_FULL_PATH}"
    fi

    local actual_size
    actual_size=$(stat -c '%s' "$GGUF_FULL_PATH")
    local actual_gb
    actual_gb=$(echo "scale=2; $actual_size / 1073741824" | bc 2>/dev/null || echo "?")

    # 简单大小校验（不应小于预期的 90%）
    local min_expected_bytes
    min_expected_bytes=$(echo "${GGUF_EXPECTED_SIZE_GB} * 1073741824 * 0.9" | bc 2>/dev/null || echo 0)

    if [ "$actual_size" -lt "$min_expected_bytes" ] 2>/dev/null; then
        warn "File size ${actual_gb} GB is smaller than expected ~${GGUF_EXPECTED_SIZE_GB} GB"
        warn "Download may be incomplete. Please re-run this script."
        return 1
    fi

    # §L1 修复：SHA256 完整性校验（防 CDN 劫持/篡改）
    local actual_sha256
    actual_sha256=$(sha256sum "$GGUF_FULL_PATH" | awk '{print $1}')
    if [ "$actual_sha256" != "$GGUF_EXPECTED_SHA256" ]; then
        fail "SHA256 mismatch! Possible CDN tampering or corrupted download.
  expected: $GGUF_EXPECTED_SHA256
  actual:   $actual_sha256
  file:     $GGUF_FULL_PATH"
    fi
    log "SHA256 verified: ${actual_sha256:0:16}..."

    log "Download complete: ${GGUF_FULL_PATH} (~${actual_gb} GB)"
}

# ---------------------------------------------------------------------------
# 3. 可选：下载 Qwen3-1.7B-Q4_K_M（轻量模型，备用）
# ---------------------------------------------------------------------------
download_small_model() {
    local small_repo="unsloth/Qwen3-1.7B-GGUF"
    local small_file="Qwen3-1.7B-Q4_K_M.gguf"
    local small_path="${MODEL_DIR}/${small_repo}/${small_file}"
    # §L1 修复：官方 SHA256（来源：modelscope.cn/api/v1/models/unsloth/Qwen3-1.7B-GGUF/repo/files）
    local small_expected_sha256="b139949c5bd74937ad8ed8c8cf3d9ffb1e99c866c823204dc42c0d91fa181897"

    if [ -f "$small_path" ]; then
        log "Small model already exists: ${small_path}, skipping."
        return 0
    fi

    log "Downloading ${small_repo}/${small_file} (~1.1 GB)..."

    # §L2 修复：Token 临时文件传递
    local token_args=()
    if [ -n "$MODELSCOPE_SDK_TOKEN" ]; then
        local token_file
        token_file=$(mktemp)
        printf '%s' "$MODELSCOPE_SDK_TOKEN" > "$token_file"
        chmod 600 "$token_file"
        token_args=(--token "$(cat "$token_file")")
    fi

    modelscope download \
        --model "$small_repo" \
        --include "$small_file" \
        --local_dir "${MODEL_DIR}/${small_repo}" \
        "${token_args[@]}"

    if [ -n "${token_file:-}" ] && [ -f "$token_file" ]; then
        shred -u "$token_file" 2>/dev/null || rm -f "$token_file"
    fi

    if [ -f "$small_path" ]; then
        # §L1 修复：SHA256 校验
        local actual_sha256
        actual_sha256=$(sha256sum "$small_path" | awk '{print $1}')
        if [ "$actual_sha256" != "$small_expected_sha256" ]; then
            warn "Small model SHA256 mismatch! Expected $small_expected_sha256, got $actual_sha256"
            warn "File may be corrupted. Please re-run this script."
            return 1
        fi
        log "Small model SHA256 verified: ${actual_sha256:0:16}..."
        log "Small model downloaded: ${small_path}"
    else
        warn "Small model download failed (non-fatal, it's optional)"
    fi
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    log "=== Zephyr AI Desktop — Model Download ==="

    install_modelscope_cli
    download_model

    # 小模型可选，失败不影响主流程
    download_small_model || true

    log "=== Model download complete ==="
    log "Local model path: ${GGUF_FULL_PATH}"
    log "llama.cpp 启动参数: --model ${GGUF_FULL_PATH}"
}

main "$@"
