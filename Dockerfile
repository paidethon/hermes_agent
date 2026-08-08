# =============================================================================
# Zephyr AI Desktop — Multi-Stage Dockerfile
# =============================================================================
# 方案 B（均衡完整版）
# 基础镜像：ubuntu:24.04
# 预估镜像体积：~1.8 GB（不含 GGUF 模型）
#
# 多阶段构建：
#   Stage 1: llama.cpp 编译（仅保留 binary）
#   Stage 2: Hermes Studio 前端构建（仅保留 dist）
#   Stage 3: 最终运行镜像
#
# 安全构建原则（§7）：
#   - --no-install-recommends
#   - 构建末尾 apt upgrade
#   - binary checksum 校验
#   - 非 root 用户（hermes）
#   - 镜像层零密钥
#
# 维护者：海豚-容器工程师
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1: llama.cpp 编译
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS llama-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake build-essential wget ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# 克隆并编译 llama.cpp（CPU 模式）
RUN git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /opt/llama.cpp && \
    cd /opt/llama.cpp && \
    git fetch --tags && \
    git checkout $(git describe --tags $(git rev-list --tags --max-count=1)) && \
    mkdir build && cd build && \
    cmake .. \
        -DLLAMA_BUILD_SERVER=ON \
        -DLLAMA_BUILD_TESTS=OFF \
        -DLLAMA_BUILD_EXAMPLES=OFF \
        -DCMAKE_BUILD_TYPE=Release && \
    cmake --build . --config Release -j$(nproc) && \
    # 校验 binary 存在
    ls -la bin/llama-server && \
    # 清理 .o 文件减小体积
    find . -name "*.o" -delete

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2: Hermes Studio 前端构建
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS studio-builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Node.js 22 LTS
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

# 克隆并构建 Hermes Studio
# NOTE: 仓库地址和版本号需用户确认后替换
ARG HERMES_STUDIO_REPO=https://github.com/EKKOLearnAI/hermes-studio.git
ARG HERMES_STUDIO_VERSION=v0.6.39
RUN git clone --branch ${HERMES_STUDIO_VERSION} --depth 1 \
      ${HERMES_STUDIO_REPO} /opt/hermes-studio || \
    git clone --depth 1 ${HERMES_STUDIO_REPO} /opt/hermes-studio

WORKDIR /opt/hermes-studio
RUN npm ci --omit=dev || npm install && \
    npm run build && \
    # 清理 node_modules 中的缓存
    npm cache clean --force

# ─────────────────────────────────────────────────────────────────────────────
# Stage 3: 最终运行镜像
# ─────────────────────────────────────────────────────────────────────────────
FROM ubuntu:24.04 AS final

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

# ── 层 1: 系统基础 — KDE Plasma + TigerVNC + noVNC + Chrome + fcitx5 ────────
# 分步安装以利用层缓存，大依赖单独一层

# 1a: 基础工具 + KDE Plasma 桌面
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget git jq ripgrep rsync zstd tar gzip unzip \
    ca-certificates gnupg lsb-release software-properties-common \
    locales tzdata && \
    locale-gen en_US.UTF-8 zh_CN.UTF-8 && \
    rm -rf /var/lib/apt/lists/*

# 1b: KDE Plasma（最小安装，不含多余应用）
RUN apt-get update && apt-get install -y --no-install-recommends \
    kde-plasma-desktop \
    konsole dolphin ark kate && \
    rm -rf /var/lib/apt/lists/*

# 1c: TigerVNC + noVNC 依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    tigervnc-standalone-server tigervnc-common \
    xterm dbus-x11 x11-utils x11-xserver-utils && \
    rm -rf /var/lib/apt/lists/*

# 1d: Chrome（Google 官方源）
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
        | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] \
        http://dl.google.com/linux/chrome/deb/ stable main" \
        > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# 1e: noVNC 1.7.0（GitHub release，checksum 校验）
ARG NOVNC_VERSION=1.7.0
ARG NOVNC_SHA256=b1003a11b6e6e8d8f7f5e5586daae7f8ca651d8aee0aa155ff9ac841c48f52c6
RUN curl -fsSL "https://github.com/novnc/noVNC/archive/refs/tags/v${NOVNC_VERSION}.tar.gz" \
        -o /tmp/novnc.tar.gz && \
    echo "${NOVNC_SHA256}  /tmp/novnc.tar.gz" | sha256sum -c - && \
    mkdir -p /opt/novnc && \
    tar -xzf /tmp/novnc.tar.gz -C /opt/novnc --strip-components=1 && \
    rm /tmp/novnc.tar.gz

# 1f: fcitx5 中文输入法
RUN apt-get update && apt-get install -y --no-install-recommends \
    fcitx5 fcitx5-chinese-addons fcitx5-frontend-qt5 fcitx5-frontend-gtk3 && \
    rm -rf /var/lib/apt/lists/*

# 1g: Nginx + Supervisord + 系统工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    nginx supervisor \
    apache2-utils \
    rclone \
    ffmpeg \
    gosu && \
    rm -rf /var/lib/apt/lists/*

# ── 层 2: 运行时 — Python 3.11 + Node.js 22 + uv ───────────────────────────

# 2a: Python 3.11（deadsnakes PPA）
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv python3.11-dev \
    python3-pip python3-setuptools python3-wheel && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 && \
    ln -sf /usr/bin/python3.11 /usr/local/bin/python && \
    rm -rf /var/lib/apt/lists/*

# 2b: Node.js 22 LTS（NodeSource）
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    npm install -g npm@latest && \
    rm -rf /var/lib/apt/lists/*

# 2c: uv（Python 包管理加速器）
RUN curl -fsSL https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    mv /root/.local/bin/uvx /usr/local/bin/uvx

# ── 层 3: Hermes Agent（非 root 用户 hermes）────────────────────────────────

# 创建 hermes 用户（解决 Gateway root 崩溃问题）
RUN useradd -m -s /bin/bash hermes && \
    mkdir -p /opt/hermes && \
    chown hermes:hermes /opt/hermes

# 克隆 Hermes Agent
# NOTE: 仓库地址和版本号需用户确认后替换
# 修复 shell 优先级 bug：原写法 A || B && C 中，A 成功时 chown 会被跳过
ARG HERMES_AGENT_REPO=https://github.com/NousResearch/hermes.git
ARG HERMES_AGENT_VERSION=v0.18.2
RUN { git clone --branch ${HERMES_AGENT_VERSION} --depth 1 \
        ${HERMES_AGENT_REPO} /opt/hermes-src || \
      git clone --depth 1 ${HERMES_AGENT_REPO} /opt/hermes-src; } && \
    chown -R hermes:hermes /opt/hermes-src

# 安装 Hermes Agent 依赖
RUN cd /opt/hermes-src && \
    if [ -f requirements.txt ]; then \
        pip install --no-cache-dir -r requirements.txt; \
    fi && \
    if [ -f pyproject.toml ]; then \
        uv pip install --system --no-cache .; \
    fi && \
    # 拷贝到运行时目录
    cp -a /opt/hermes-src/. /opt/hermes/ && \
    rm -rf /opt/hermes-src && \
    chown -R hermes:hermes /opt/hermes

# ── 层 4: Hermes Studio（从 Stage 2 拷贝构建产物）──────────────────────────
COPY --from=studio-builder /opt/hermes-studio /opt/hermes-studio
RUN chown -R hermes:hermes /opt/hermes-studio

# ── 层 5: Open WebUI ────────────────────────────────────────────────────────
RUN pip install --no-cache-dir open-webui==0.11.0

# ── 层 6: ModelScope SDK + 模型层（合并极客-AI模型通的 Dockerfile.model-layer）──
# 修正：方案文档写的 Qwen/Qwen3-8B-GGUF 不存在，实际仓库是 unsloth/Qwen3-8B-GGUF
#       文件名是 Qwen3-8B-Q4_K_M.gguf（大写 Q）
RUN pip install --no-cache-dir "modelscope>=1.14.0"

ENV MODELSCOPE_CACHE=/mnt/workspace/zephyr/models
ENV LLAMA_CPP_MODEL_PATH=/mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf

# 模型预下载（默认关闭，运行时由 first-run-init.sh 下载）
# 设为 1 可在构建时预下载（镜像体积 +5GB）
ARG PRELOAD_QWEN3_8B=0
RUN if [ "$PRELOAD_QWEN3_8B" = "1" ]; then \
      mkdir -p /opt/models && \
      MODELSCOPE_CACHE=/opt/models modelscope download \
        --model unsloth/Qwen3-8B-GGUF \
        --include "Qwen3-8B-Q4_K_M.gguf" \
        --local_dir /opt/models/unsloth/Qwen3-8B-GGUF && \
      echo "Model preloaded to /opt/models/unsloth/Qwen3-8B-GGUF/"; \
    fi

# 可选：预下载 Qwen3-1.7B-Q4_K_M（轻量备用模型，~1.1 GB）
ARG PRELOAD_QWEN3_1_7B=0
RUN if [ "$PRELOAD_QWEN3_1_7B" = "1" ]; then \
      mkdir -p /opt/models && \
      MODELSCOPE_CACHE=/opt/models modelscope download \
        --model unsloth/Qwen3-1.7B-GGUF \
        --include "Qwen3-1.7B-Q4_K_M.gguf" \
        --local_dir /opt/models/unsloth/Qwen3-1.7B-GGUF; \
    fi

# COPY 模型层脚本和配置（极客-AI模型通 提供）
COPY modelscope/scripts/model-download.sh /opt/zephyr/scripts/model-download.sh
COPY modelscope/scripts/modelscope-api-test.py /opt/zephyr/scripts/modelscope-api-test.py
COPY modelscope/config/llama-cpp.env /opt/zephyr/config/llama-cpp.env
COPY modelscope/config/open-webui-models.env /opt/zephyr/config/open-webui-models.env
RUN chmod +x /opt/zephyr/scripts/model-download.sh /opt/zephyr/scripts/modelscope-api-test.py

# ── 层 6.5: llama.cpp（从 Stage 1 拷贝编译产物）────────────────────────────
# supervisord.conf 中 command=/opt/llama.cpp/llama-server
COPY --from=llama-builder /opt/llama.cpp/build/bin/ /opt/llama.cpp/bin/
RUN ln -sf /opt/llama.cpp/bin/llama-server /opt/llama.cpp/llama-server && \
    chmod +x /opt/llama.cpp/bin/llama-server

# ── 层 7: Nginx + Supervisord 配置 ──────────────────────────────────────────

# 拷贝行者提供的配置文件
COPY modelscope/nginx/nginx.conf /etc/nginx/nginx.conf
COPY modelscope/nginx/portal.conf /etc/nginx/conf.d/portal.conf
COPY modelscope/supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# 确保 Nginx 日志目录存在
RUN mkdir -p /var/log/nginx /var/log/supervisor /run/nginx

# ── 层 8: 入口脚本 + 工具脚本 ───────────────────────────────────────────────
COPY modelscope/entrypoint.sh /opt/entrypoint.sh
COPY scripts/ /opt/scripts/
RUN chmod +x /opt/entrypoint.sh /opt/scripts/*.sh

# ── 层 9: 可选模块开关 ──────────────────────────────────────────────────────
# Flowise 默认启用（用户已确认 ENABLE_FLOWISE=1）
ARG ENABLE_FLOWISE=1
ARG ENABLE_ANYTHINGLLM=0
ARG ENABLE_LLAMA_CPP=1

ENV ENABLE_FLOWISE=${ENABLE_FLOWISE}
ENV ENABLE_ANYTHINGLLM=${ENABLE_ANYTHINGLLM}
ENV ENABLE_LLAMA_CPP=${ENABLE_LLAMA_CPP}

# Flowise 条件安装（仅在构建时 ENABLE_FLOWISE=1 时装，固定版本保证可复现）
# npm 全局安装 → 二进制位于 npm 全局 bin（NodeSource 下为 /usr/bin/flowise）
# 统一软链到 /opt/flowise/flowise 供 supervisord 以绝对路径引用
RUN if [ "$ENABLE_FLOWISE" = "1" ]; then \
      npm install -g flowise@2.2.8 && \
      mkdir -p /opt/flowise && \
      ln -sf "$(command -v flowise)" /opt/flowise/flowise; \
    fi

# 模型相关环境变量（supervisord.conf %(ENV_*)s 引用，必须定义否则启动失败）
ENV LLAMA_CPP_THREADS=1
ENV LLAMA_CPP_CTX_SIZE=8192
ENV LLAMA_CPP_BATCH_SIZE=512
ENV LLAMA_CPP_NGPU_LAYERS=0
ENV LLAMA_CPP_MODEL_ALIAS=qwen3-8b-local
ENV LLAMA_CPP_API_KEY=sk-zephyr-local-internal
ENV OPENWEBUI_DEFAULT_MODEL=qwen3-8b-local

# Hermes Gateway 认证令牌（supervisord.conf %(ENV_HERMES_API_KEY)s 引用）
# 必须在此定义兜底值，否则用户未注入 HERMES_API_KEY Secret 时
# supervisord 解析 %(ENV_HERMES_API_KEY)s 失败 → hermes-gateway 无法启动。
# 空值 = 不启用令牌认证（Gateway 仅绑 127.0.0.1，安全边界由 Nginx 层把守）。
ENV HERMES_API_KEY=""

# Flowise 凭据兜底（supervisord.conf %(ENV_FLOWISE_USER)s / %(ENV_FLOWISE_PASSWORD)s 引用）
# 运行时由 entrypoint.sh setup_flowise_credentials() 注入真实值：
#   Secret 注入 > 持久化盘复用 > 自动生成强密码落盘
ENV FLOWISE_USER=zephyr
ENV FLOWISE_PASSWORD=""

# ── 层 10: Portal 导航页 + 种子配置 ─────────────────────────────────────────
COPY portal/index.html /var/www/portal/index.html
COPY config/hermes-seed/ /opt/hermes-seed/
COPY config/rclone.template.conf /opt/templates/rclone.template.conf

# ── 安全加固：构建末尾 apt upgrade ───────────────────────────────────────────
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# ── 最终配置 ────────────────────────────────────────────────────────────────

EXPOSE 7860

# 健康检查（每 30 秒检测 Nginx 是否响应）
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -sf http://127.0.0.1:7860/health || exit 1

# 持久化卷声明（仅供文档参考，实际持久化由 ModelScope /mnt/workspace 管理）
VOLUME ["/mnt/workspace"]

ENTRYPOINT ["/opt/entrypoint.sh"]
