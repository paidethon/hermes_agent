#!/bin/bash
# =============================================================================
# Zephyr AI Desktop — ModelScope Entry Point
# =============================================================================
# 职责：
#   1. 持久化目录初始化与符号链接建立
#   2. Nginx Basic Auth htpasswd 生成 (§2)
#   3. TigerVNC 密码配置与校验 (§3)
#   4. rclone.conf 运行时生成 (§4)
#   5. 安全校验：符号链接/权限/种子配置 (§6)
#   6. 启动 supervisord
#
# 合并自：林深-安全合规员 安全加固补充文件 §2/§3/§4/§6
# 维护者：行者-Linux专家
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# 全局变量
# ---------------------------------------------------------------------------
PERSIST_ROOT="/mnt/workspace/zephyr"
SEED_DIR="/opt/zephyr/seeds"
SEED_CHECKSUM="${SEED_DIR}/checksums.sha256"
LOG_PREFIX="[entrypoint]"

log()    { echo "${LOG_PREFIX} $*"; }
warn()   { echo "${LOG_PREFIX} [WARN] $*" >&2; }
error()  { echo "${LOG_PREFIX} [ERROR] $*" >&2; }
fail()   { error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# 0. 持久化目录初始化
# ---------------------------------------------------------------------------
init_persistence() {
    log "Initializing persistence at ${PERSIST_ROOT}"

    local dirs=(
        "${PERSIST_ROOT}/hermes"
        "${PERSIST_ROOT}/hermes-studio"
        "${PERSIST_ROOT}/open-webui"
        "${PERSIST_ROOT}/models"
        "${PERSIST_ROOT}/desktop"
        "${PERSIST_ROOT}/projects"
        "${PERSIST_ROOT}/rclone"
        "${PERSIST_ROOT}/backups/hourly"
        "${PERSIST_ROOT}/backups/daily"
        "${PERSIST_ROOT}/backups/manual"
        "${PERSIST_ROOT}/config"
        "${PERSIST_ROOT}/flowise"
    )

    for d in "${dirs[@]}"; do
        mkdir -p "$d"
    done

    # 确保 /app/backend 存在（Open WebUI 数据目录父路径）
    mkdir -p /app/backend

    # 建立符号链接：将运行时路径指向持久化盘（方案 §7.2）
    create_safe_symlink "${PERSIST_ROOT}/hermes"        "/root/hermes-data"
    create_safe_symlink "${PERSIST_ROOT}/hermes-studio" "/root/.hermes-web-ui"
    create_safe_symlink "${PERSIST_ROOT}/open-webui"    "/app/backend/data"
    create_safe_symlink "${PERSIST_ROOT}/desktop"       "/root/Desktop"
    # hermes 用户家目录持久化（BUG-8 修复配套）：
    # studio 的默认 profile 目录是 ~/.hermes（hermes-profile.ts），
    # 数据目录默认 ~/.hermes-web-ui——两者都软链到持久化盘，
    # 与 supervisord 显式注入的 HERMES_HOME/HERMES_WEB_UI_HOME 双保险一致
    create_safe_symlink "${PERSIST_ROOT}/hermes"        "/home/hermes/.hermes"
    create_safe_symlink "${PERSIST_ROOT}/hermes-studio" "/home/hermes/.hermes-web-ui"

    # 确保 hermes 用户对持久化目录有读写权限
    # Hermes Gateway / Studio / Open WebUI / llama.cpp 均以 hermes 用户运行
    chown -R hermes:hermes "${PERSIST_ROOT}/hermes" \
                           "${PERSIST_ROOT}/hermes-studio" \
                           "${PERSIST_ROOT}/open-webui" \
                           "${PERSIST_ROOT}/models" \
                           "${PERSIST_ROOT}/projects" \
                           "${PERSIST_ROOT}/flowise" 2>/dev/null || true

    # 设置 Hermes 环境变量
    export HERMES_HOME="${PERSIST_ROOT}/hermes"
    export HERMES_WEB_UI_HOME="${PERSIST_ROOT}/hermes-studio"
    export DATA_DIR="${PERSIST_ROOT}"
    export MODELSCOPE_CACHE="${PERSIST_ROOT}/models"

    log "Persistence initialized. HERMES_HOME=${HERMES_HOME}"
}

# ---------------------------------------------------------------------------
# §6.1 符号链接安全校验（防 symlink traversal）
# ---------------------------------------------------------------------------
create_safe_symlink() {
    local src="$1"
    local dst="$2"
    local resolved_src

    resolved_src=$(realpath -m "$src")

    # 校验目标在持久化盘范围内
    if [[ "$resolved_src" != /mnt/workspace/* ]]; then
        fail "symlink target $src outside /mnt/workspace, refusing"
    fi

    # 如果 dst 已存在且不是符号链接，先备份
    if [ -e "$dst" ] && [ ! -L "$dst" ]; then
        warn "$dst exists and is not a symlink, backing up to ${dst}.bak"
        mv "$dst" "${dst}.bak"
    fi

    ln -sfn "$resolved_src" "$dst"
    log "Symlink: ${dst} -> ${resolved_src}"
}

# ---------------------------------------------------------------------------
# §6.2 种子配置完整性校验
# ---------------------------------------------------------------------------
verify_seed() {
    local file="$1"
    local expected_sha256="$2"
    local actual_sha256

    if [ ! -f "$file" ]; then
        fail "seed config $file not found"
    fi

    actual_sha256=$(sha256sum "$file" | awk '{print $1}')
    if [ "$actual_sha256" != "$expected_sha256" ]; then
        error "seed config $file checksum mismatch"
        error "  expected: $expected_sha256"
        error "  actual:   $actual_sha256"
        fail "checksum verification failed"
    fi
    log "Seed verified: ${file}"
}

# ---------------------------------------------------------------------------
# §6.2b 批量种子配置校验（使用 sha256sum -c）
# ---------------------------------------------------------------------------
verify_all_seeds() {
    log "Verifying seed configuration integrity"

    if [ ! -d "$SEED_DIR" ]; then
        warn "Seed directory not found at ${SEED_DIR}, skipping verification"
        return 0
    fi

    if [ ! -f "$SEED_CHECKSUM" ]; then
        warn "Seed checksum file not found at ${SEED_CHECKSUM}, skipping verification"
        return 0
    fi

    # 使用 sha256sum -c 批量校验所有种子文件
    if ! (cd "$SEED_DIR" && sha256sum -c checksums.sha256 --quiet 2>&1); then
        fail "Seed configuration checksum verification failed — possible image tampering"
    fi

    log "All seed configurations verified"
}

# ---------------------------------------------------------------------------
# §6.3 启动前校验关键文件权限
# ---------------------------------------------------------------------------
check_perms() {
    local file="$1"
    local expected="$2"
    local actual

    if [ ! -f "$file" ]; then
        return 0  # 文件尚未生成，跳过
    fi

    actual=$(stat -c '%a' "$file")
    if [ "$actual" != "$expected" ]; then
        warn "$file perm $actual (expected $expected), fixing..."
        chmod "$expected" "$file"
    fi
}

# ---------------------------------------------------------------------------
# §2. Nginx Basic Auth — htpasswd 生成（SHA-512 crypt）
# ---------------------------------------------------------------------------
generate_htpasswd() {
    log "Generating Nginx Basic Auth (.htpasswd)"

    if [ -z "${PORTAL_USER:-}" ] || [ -z "${PORTAL_PASSWORD:-}" ]; then
        fail "PORTAL_USER/PORTAL_PASSWORD not set, refusing to start"
    fi

    # ⚠️ 坑（2026-08-09 实测）：nginx auth_basic 官方仅支持 crypt()/apr1/{SHA}
    # 格式（https://nginx.org/en/docs/http/ngx_http_auth_basic_module.html），
    # 不支持 bcrypt ($2y$)。原写法 htpasswd -bcB 生成 bcrypt → nginx 永远验证
    # 失败 → 浏览器无限弹登录框。
    # 改用 SHA-512 crypt（$6$）：glibc crypt() 原生支持，是 nginx 可用的最强格式。
    local hash
    hash=$(openssl passwd -6 "$PORTAL_PASSWORD") || \
        fail "openssl passwd failed, cannot generate htpasswd"
    printf '%s:%s\n' "$PORTAL_USER" "$hash" > /etc/nginx/.htpasswd
    chmod 600 /etc/nginx/.htpasswd

    log "htpasswd generated for user '${PORTAL_USER}' (SHA-512 crypt, nginx-compatible)"
}

# ---------------------------------------------------------------------------
# §3. TigerVNC 密码配置
# ---------------------------------------------------------------------------
generate_vnc_password() {
    log "Configuring TigerVNC password"

    local vnc_password="${VNC_PASSWORD:-}"

    if [ -z "$vnc_password" ]; then
        fail "VNC_PASSWORD not set, refusing to start desktop"
    fi

    # 密码复杂度校验：>=8 位，含字母 + 数字
    if [ ${#vnc_password} -lt 8 ]; then
        fail "VNC_PASSWORD too weak: need >=8 chars with letters and digits"
    fi
    if ! echo "$vnc_password" | grep -q '[A-Za-z]'; then
        fail "VNC_PASSWORD too weak: must contain letters"
    fi
    if ! echo "$vnc_password" | grep -q '[0-9]'; then
        fail "VNC_PASSWORD too weak: must contain digits"
    fi

    # 生成 TigerVNC 密码文件
    # Ubuntu 24.04 起命令更名为 tigervncpasswd（tigervnc-tools 包提供），
    # 旧版本为 vncpasswd —— 运行时探测，两者都没有则快速失败
    local vncpasswd_cmd=""
    if command -v tigervncpasswd >/dev/null 2>&1; then
        vncpasswd_cmd="tigervncpasswd"
    elif command -v vncpasswd >/dev/null 2>&1; then
        vncpasswd_cmd="vncpasswd"
    else
        fail "Neither tigervncpasswd nor vncpasswd found — install tigervnc-tools"
    fi

    mkdir -p /root/.vnc
    echo "$vnc_password" | "$vncpasswd_cmd" -f > /root/.vnc/passwd
    chmod 600 /root/.vnc/passwd

    log "VNC password configured via $vncpasswd_cmd (complexity validated)"
}

# ---------------------------------------------------------------------------
# §4. rclone.conf 运行时生成
# 2026-08-09 用户决定移除 crypt 加密层：备份直接写入 OneDrive 明文
# （onedrive:zephyr-backup），不再需要 RCLONE_CRYPT_PASSWORD/PASSWORD2
# ---------------------------------------------------------------------------
generate_rclone_config() {
    log "Generating rclone.conf at runtime"

    local rclone_conf="${PERSIST_ROOT}/config/rclone.conf"
    mkdir -p "$(dirname "$rclone_conf")"

    # 分级校验：
    # 第一级：ONEDRIVE_TOKEN 缺失 = 用户不需要备份，跳过
    if [ -z "${ONEDRIVE_TOKEN:-}" ]; then
        warn "ONEDRIVE_TOKEN not set, skipping rclone config generation"
        warn "Backup to OneDrive will be unavailable until configured"
        return 0
    fi

    # 第二级：ONEDRIVE_TOKEN 存在 = 用户要备份，DRIVE_ID 必须齐全
    if [ -z "${ONEDRIVE_DRIVE_ID:-}" ]; then
        fail "ONEDRIVE_TOKEN set but ONEDRIVE_DRIVE_ID missing — cannot generate valid rclone config"
    fi

    cat > "$rclone_conf" <<EOF
[onedrive]
type = onedrive
token = ${ONEDRIVE_TOKEN}
drive_id = ${ONEDRIVE_DRIVE_ID}
drive_type = personal
EOF

    chmod 600 "$rclone_conf"

    # 校验配置有效性
    if ! rclone --config="$rclone_conf" listremotes >/dev/null 2>&1; then
        fail "rclone config invalid, refusing to start backup service"
    fi

    log "rclone.conf generated and validated (remotes: $(rclone --config="$rclone_conf" listremotes | tr '\n' ' '))"
}

# ---------------------------------------------------------------------------
# §6.3 最终权限校验（所有敏感文件已生成后）
# ---------------------------------------------------------------------------
final_permission_check() {
    log "Running final permission checks"

    check_perms /etc/nginx/.htpasswd          600
    check_perms /root/.vnc/passwd             600
    check_perms "${PERSIST_ROOT}/config/rclone.conf" 600

    # 确保持久化目录权限正确
    chmod 700 /root/.vnc 2>/dev/null || true
    chmod 755 "${PERSIST_ROOT}"

    log "Permission checks passed"
}

# ---------------------------------------------------------------------------
# §8.1 模型存在性检查（极客-AI模型通 建议集成）
# ---------------------------------------------------------------------------
check_model_availability() {
    log "Checking local model availability..."

    local model_path="${LLAMA_CPP_MODEL_PATH:-/mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf}"

    if [ "${ENABLE_LLAMA_CPP:-1}" = "1" ]; then
        if [ ! -f "$model_path" ]; then
            warn "Local model not found at ${model_path}"
            log "Running model-download.sh to fetch Qwen3-8B-Q4_K_M..."
            if [ -x /opt/zephyr/scripts/model-download.sh ]; then
                /opt/zephyr/scripts/model-download.sh || {
                    warn "Model download failed, llama.cpp will be disabled"
                    export ENABLE_LLAMA_CPP=0
                }
            else
                warn "model-download.sh not found at /opt/zephyr/scripts/, llama.cpp will be disabled"
                export ENABLE_LLAMA_CPP=0
            fi
        else
            local model_size
            model_size=$(stat -c '%s' "$model_path" 2>/dev/null || echo 0)
            local model_gb
            model_gb=$(echo "scale=2; $model_size / 1073741824" | bc 2>/dev/null || echo "?")
            log "Local model found: ${model_path} (~${model_gb} GB)"
        fi
    else
        log "ENABLE_LLAMA_CPP=0, skipping model check"
    fi
}

# ---------------------------------------------------------------------------
# A2 修复：统一配置源 — 启动前 source 模型层 env 文件
# ---------------------------------------------------------------------------
# 背景（云鹤-架构审计师 架构审计报告 A2）：
#   llama-cpp.env / open-webui-models.env 被 COPY 进镜像但从未被 source，
#   supervisord.conf 的 %(ENV_LLAMA_CPP_*)s 依赖 Dockerfile ENV 层兜底，
#   形成"Dockerfile ENV + env 文件"两套配置源，维护者改一边另一边不生效。
# 修复：在 exec supervisord 前 source env 文件，使其成为运行时唯一配置源。
#   env 文件内均用 ${VAR:-default} 形式，Dockerfile ENV 仍可作为兜底，
#   但优先级以 env 文件为准（运行时可改、无需重建镜像）。
# ---------------------------------------------------------------------------
load_service_env_files() {
    log "Loading service env files (unified config source, A2 fix)"

    local env_files=(
        "/opt/zephyr/config/llama-cpp.env"
        "/opt/zephyr/config/open-webui-models.env"
    )

    for f in "${env_files[@]}"; do
        if [ -f "$f" ]; then
            # set -a 使 source 进来的变量自动 export，供 supervisord %(ENV_*)s 引用
            set -a
            # shellcheck disable=SC1090
            . "$f"
            set +a
            log "Sourced: $f"
        else
            warn "env file not found: $f, falling back to Dockerfile ENV defaults"
        fi
    done
}

# ---------------------------------------------------------------------------
# Flowise 凭据准备（§4 ENABLE_FLOWISE=1 时生效）
# ---------------------------------------------------------------------------
# Flowise 默认无认证，必须注入 FLOWISE_USER/FLOWISE_PASSWORD（林深 §4 要求）。
# supervisord.conf 中 [program:flowise] 引用 %(ENV_FLOWISE_USER)s / %(ENV_FLOWISE_PASSWORD)s。
# 优先级：运行时环境变量注入 > 持久化盘已有凭据 > 自动生成强密码并落盘。
# ---------------------------------------------------------------------------
setup_flowise_credentials() {
    if [ "${ENABLE_FLOWISE:-0}" != "1" ]; then
        log "ENABLE_FLOWISE=0, skipping Flowise credentials"
        return 0
    fi

    local cred_file="${PERSIST_ROOT}/config/flowise-credentials.env"

    # 已通过 ModelScope Secrets / 环境变量注入，直接使用
    if [ -n "${FLOWISE_USER:-}" ] && [ -n "${FLOWISE_PASSWORD:-}" ]; then
        log "Flowise credentials provided via environment"
        export FLOWISE_USER FLOWISE_PASSWORD
        return 0
    fi

    # 复用持久化盘上已生成的凭据（保证重启后凭据稳定）
    if [ -f "$cred_file" ]; then
        log "Loading existing Flowise credentials from $cred_file"
        set -a
        # shellcheck disable=SC1090
        . "$cred_file"
        set +a
        return 0
    fi

    # 首次启动：自动生成强密码并落盘
    warn "FLOWISE_USER/FLOWISE_PASSWORD not set, generating strong credentials"
    FLOWISE_USER="${FLOWISE_USER:-zephyr}"
    FLOWISE_PASSWORD="$(head -c 32 /dev/urandom | base64 | tr -d '/+=' | cut -c1-24)"
    export FLOWISE_USER FLOWISE_PASSWORD

    cat > "$cred_file" <<EOF
FLOWISE_USER=${FLOWISE_USER}
FLOWISE_PASSWORD=${FLOWISE_PASSWORD}
EOF
    chmod 600 "$cred_file"
    log "Flowise credentials generated and saved to $cred_file (chmod 600)"
}

# ---------------------------------------------------------------------------
# Hermes Gateway API 密钥准备（BUG-7 修复的配套项）
# ---------------------------------------------------------------------------
# 真实机制（对照 NousResearch/hermes-agent 核实，2026-08-09）：
#   gateway 的 api_server 平台只在 API_SERVER_KEY 可用（>=16 位）时才注册启动
#   （gateway/config.py _has_usable_api_server_key → has_usable_secret min_length=16）。
#   密钥为空 = api_server 不启动 = 内部调用全部连不上 8642。
# 策略与 Flowise 凭据一致：Secret 注入 > 持久化盘复用 > 自动生成强密钥落盘。
# supervisord.conf 中 API_SERVER_KEY="%(ENV_HERMES_API_KEY)s" 消费此值。
# ---------------------------------------------------------------------------
setup_hermes_api_key() {
    local key_file="${PERSIST_ROOT}/config/hermes-api-key"

    # 用户显式注入：校验强度（api_server 拒绝 <16 位的密钥）
    if [ -n "${HERMES_API_KEY:-}" ]; then
        if [ ${#HERMES_API_KEY} -lt 16 ]; then
            fail "HERMES_API_KEY too short (${#HERMES_API_KEY} chars): gateway api_server requires >=16 chars, or leave it empty to auto-generate"
        fi
        log "Hermes API key provided via environment (${#HERMES_API_KEY} chars)"
        export HERMES_API_KEY
        return 0
    fi

    # 复用持久化盘上已生成的密钥（保证重启后密钥稳定，客户端配置不失效）
    if [ -f "$key_file" ]; then
        HERMES_API_KEY="$(cat "$key_file")"
        export HERMES_API_KEY
        log "Loaded existing Hermes API key from $key_file"
        return 0
    fi

    # 首次启动：自动生成 32 位强密钥并落盘
    warn "HERMES_API_KEY not set, generating strong key for gateway api_server"
    HERMES_API_KEY="$(head -c 48 /dev/urandom | base64 | tr -d '/+=' | cut -c1-32)"
    export HERMES_API_KEY

    printf '%s' "$HERMES_API_KEY" > "$key_file"
    chmod 600 "$key_file"
    log "Hermes API key generated and saved to $key_file (chmod 600)"
}

# ---------------------------------------------------------------------------
# A1 修复：调用首次运行初始化脚本
# ---------------------------------------------------------------------------
# 背景（云鹤-架构审计师 架构审计报告 A1）：
#   first-run-init.sh 定义了 OneDrive 备份恢复、模型检查/下载、Hermes 种子部署、
#   Open WebUI 初始化，但 entrypoint.sh main() 从未调用它，整段逻辑是死代码。
# 修复：在模型检查之后、exec supervisord 之前调用 first-run-init.sh。
# ---------------------------------------------------------------------------
run_first_run_init() {
    local init_script="/opt/scripts/first-run-init.sh"

    if [ ! -x "$init_script" ]; then
        warn "first-run-init.sh not found or not executable at $init_script, skipping"
        return 0
    fi

    log "Running first-run initialization (OneDrive restore / seeds / Open WebUI)..."
    # first-run-init.sh 内部各步骤自带容错（restore 失败降级、模型失败 return 1），
    # 这里用 || warn 包裹，避免初始化失败阻断整个容器启动。
    if ! "$init_script"; then
        warn "first-run-init.sh reported a non-fatal issue, continuing startup"
    fi
}

# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
main() {
    log "=== Zephyr AI Desktop Entry Point ==="

    # Step 0: 持久化初始化
    init_persistence

    # Step 1: 种子配置校验
    # §9.5 中风险修复：verify_seed() 已定义但 main() 未调用 → 现已调用
    verify_all_seeds

    # Step 2: 生成安全配置
    generate_htpasswd
    generate_vnc_password
    generate_rclone_config
    setup_flowise_credentials
    setup_hermes_api_key

    # Step 3: 最终权限校验
    final_permission_check

    # Step 3.5: 模型存在性检查（§8.1 极客建议集成）
    check_model_availability

    # Step 3.6: 首次运行初始化（A1 修复：接入 first-run-init.sh）
    run_first_run_init

    # Step 3.7: 统一配置源（A2 修复：source 模型层 env 文件，须在 exec supervisord 前）
    load_service_env_files

    # Step 4: 启动 supervisord（前台运行，作为 PID 1）
    log "Starting supervisord..."
    exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
}

# ---------------------------------------------------------------------------
# 执行
# ---------------------------------------------------------------------------
main "$@"
