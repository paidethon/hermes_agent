# syntax=docker/dockerfile:1
# Recovery profile: KDE + Hermes + local-only Studio + cookie-authenticated noVNC.
# Build on GitHub Actions, then deploy the resulting image by digest to ModelScope.
FROM node:24-bookworm-slim AS studio-build
ARG STUDIO_REF=v0.6.39
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates python3 make g++ \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch "$STUDIO_REF" https://github.com/EKKOLearnAI/hermes-studio.git /opt/hermes-studio
WORKDIR /opt/hermes-studio
RUN npm ci --ignore-scripts --fetch-retries=5 \
    && npm rebuild node-pty \
    && npm run build \
    && npm prune --omit=dev --ignore-scripts \
    && test -f dist/server/index.js \
    && git rev-parse HEAD > /opt/studio-source-commit.txt

FROM ubuntu:24.04
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai LANG=C.UTF-8 LC_ALL=C.UTF-8
# Do not replace Ubuntu's system Python or install agent dependencies into it.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg tini nginx supervisor gosu procps \
    python3 python3-venv python3-yaml python3-argon2 build-essential \
    kde-plasma-desktop konsole dolphin kate dbus-x11 dbus-daemon \
    tigervnc-standalone-server tigervnc-tools novnc python3-websockify \
    xauth x11-utils x11-xserver-utils xterm fonts-noto-cjk \
    fcitx5 fcitx5-chinese-addons fcitx5-frontend-qt5 fcitx5-frontend-gtk3 \
    jq rsync unzip ffmpeg rclone \
    && rm -rf /var/lib/apt/lists/*
# Chrome's signed repository. The browser runs as hermes, not root.
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main' \
      > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*
COPY --from=studio-build /usr/local/ /usr/local/
COPY --from=studio-build /opt/hermes-studio/ /opt/hermes-studio/
COPY --from=studio-build /opt/studio-source-commit.txt /opt/versions/studio.txt

# Official Linux glibc release; checksum from the v4.39.25 release asset.
ARG AUTHELIA_VERSION=4.39.25
ARG AUTHELIA_SHA256=7be84c9807186487aa7e579ba76f1674e33119e52d77a1f256165d0f346aac49
RUN curl -fSL --retry 5 \
      "https://github.com/authelia/authelia/releases/download/v${AUTHELIA_VERSION}/authelia-v${AUTHELIA_VERSION}-linux-amd64.tar.gz" \
      -o /tmp/authelia.tar.gz \
    && echo "${AUTHELIA_SHA256}  /tmp/authelia.tar.gz" | sha256sum -c - \
    && mkdir /tmp/authelia-extract \
    && tar -xzf /tmp/authelia.tar.gz -C /tmp/authelia-extract \
    && install -m 0755 "$(find /tmp/authelia-extract -type f -name authelia -print -quit)" /usr/local/bin/authelia \
    && authelia --version \
    && rm -rf /tmp/authelia*

ARG HERMES_REF=v2026.8.3
# Install directly at the FINAL path; keep the editable source in the image.
RUN git clone --depth 1 --branch "$HERMES_REF" https://github.com/NousResearch/hermes-agent.git /opt/hermes \
    && python3 -m venv /opt/hermes-venv \
    && /opt/hermes-venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/hermes-venv/bin/pip install --no-cache-dir --retries 5 -e /opt/hermes \
    && /opt/hermes-venv/bin/pip check \
    && /opt/hermes-venv/bin/pip freeze > /opt/versions/hermes-requirements.txt \
    && git -C /opt/hermes rev-parse HEAD > /opt/versions/hermes.txt \
    && cd /tmp && /opt/hermes-venv/bin/hermes --help >/dev/null
RUN useradd --uid 1001 --create-home --shell /bin/bash hermes \
    && useradd --uid 1002 --system --no-create-home --shell /usr/sbin/nologin zephyr-auth \
    && mkdir -p /opt/recovery /run/dbus /var/log/supervisor /opt/home-seed/Desktop \
    && cp -a /etc/skel/. /opt/home-seed/ \
    && rm -f /etc/nginx/sites-enabled/default
ENV PATH=/opt/hermes-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DATA_ROOT=/mnt/workspace/zephyr-v2 DESKTOP_GEOMETRY=1280x800 CHROME_NO_SANDBOX=0
COPY recovery/ /opt/recovery/
RUN chmod 755 /opt/recovery/*.sh \
    && ln -s /opt/recovery/browser.sh /usr/local/bin/zephyr-browser \
    && printf '%s\n' '#!/bin/sh' 'exec /opt/hermes-venv/bin/hermes "$@"' > /usr/local/bin/hermes \
    && chmod 755 /usr/local/bin/hermes \
    && test -f /usr/share/novnc/vnc.html \
    && node -e "require('/opt/hermes-studio/node_modules/node-pty')"
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=3 \
    CMD /usr/bin/python3 /opt/recovery/health.py --once || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/recovery/entrypoint.sh"]
