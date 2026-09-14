# syntax=docker/dockerfile:1
# Recovery profile: KDE + Hermes + local-only Studio + cookie-authenticated noVNC.
# Build on GitHub Actions, then deploy the resulting image by digest to ModelScope.
FROM node:24-bookworm-slim AS studio-build
ARG STUDIO_REF=v0.7.21
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
# Build pipelines pass the source commit for the status page and diagnose.sh;
# plain local builds default to unknown.
ARG SOURCE_COMMIT=unknown
LABEL org.opencontainers.image.revision=${SOURCE_COMMIT}
ENV DEBIAN_FRONTEND=noninteractive TZ=Asia/Shanghai LANG=C.UTF-8 LC_ALL=C.UTF-8
# Do not replace Ubuntu's system Python or install agent dependencies into it.
# build-essential exists to compile sdist dependencies during the agent install
# below and is purged immediately afterwards; nothing compiles at runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl git gnupg tini nginx supervisor gosu procps \
    python3 python3-venv python3-yaml python3-argon2 build-essential rsync \
    kde-plasma-desktop kwin-x11 konsole dolphin kate dbus-x11 dbus-daemon \
    tigervnc-standalone-server tigervnc-tools novnc python3-websockify \
    xauth x11-utils x11-xserver-utils xterm fonts-noto-cjk \
    fcitx5 fcitx5-chinese-addons fcitx5-frontend-qt5 fcitx5-frontend-gtk3 \
    jq unzip \
    && rm -rf /var/lib/apt/lists/*
# Chrome's signed repository. The browser runs as hermes, not root.
RUN curl -fsSL https://dl.google.com/linux/linux_signing_key.pub \
      | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] https://dl.google.com/linux/chrome/deb/ stable main' \
      > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y --no-install-recommends google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*
# Runtime needs the node binary and the built/pruned Studio tree only: npm,
# corepack, and the rest of the build stage's /usr/local never run in prod.
COPY --from=studio-build /usr/local/bin/node /usr/local/bin/node
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

ARG HERMES_REF=v2026.9.14
# Install directly at the FINAL path; keep the editable source in the image.
RUN git clone --depth 1 --branch "$HERMES_REF" https://github.com/NousResearch/hermes-agent.git /opt/hermes \
    && python3 -m venv /opt/hermes-venv \
    && /opt/hermes-venv/bin/pip install --no-cache-dir --upgrade pip setuptools wheel \
    && /opt/hermes-venv/bin/pip install --no-cache-dir --retries 5 -e /opt/hermes \
    && /opt/hermes-venv/bin/pip check \
    && /opt/hermes-venv/bin/pip freeze > /opt/versions/hermes-requirements.txt \
    && git -C /opt/hermes rev-parse HEAD > /opt/versions/hermes.txt \
    && cd /tmp && /opt/hermes-venv/bin/hermes --help >/dev/null
# All compilation happened above (venv sdists, nothing at runtime); the
# toolchain is ~300MB of dead weight in the serving image.
RUN apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 1001 --create-home --shell /bin/bash hermes \
    && useradd --uid 1002 --system --no-create-home --shell /usr/sbin/nologin zephyr-auth \
    && mkdir -p /opt/recovery /run/dbus /var/log/supervisor /opt/home-seed/Desktop \
    && cp -a /etc/skel/. /opt/home-seed/ \
    && rm -f /etc/nginx/sites-enabled/default
ENV PATH=/opt/hermes-venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
ENV DATA_ROOT=/mnt/workspace/zephyr-v2 DESKTOP_GEOMETRY=1280x800 CHROME_NO_SANDBOX=0
RUN mkdir -p /opt/versions && printf '%s\n' "${SOURCE_COMMIT}" > /opt/versions/app.txt
COPY recovery/ /opt/recovery/
RUN chmod 755 /opt/recovery/*.sh \
    && ln -s /opt/recovery/browser.sh /usr/local/bin/zephyr-browser \
    && printf '%s\n' '#!/bin/sh' 'exec /opt/hermes-venv/bin/hermes "$@"' > /usr/local/bin/hermes \
    && chmod 755 /usr/local/bin/hermes \
    && test -f /usr/share/novnc/vnc.html \
    && node -e "require('/opt/hermes-studio/node_modules/node-pty')"
# Noble lists kwin-x11 only as a Recommends of kde-plasma-desktop, so a trimmed
# install can still build a session with no window manager: windows render but
# have no title bar and cannot be moved, maximized, or closed (2026-09 incident).
# Fail the build here instead of discovering it inside a running deployment.
RUN for binary in startplasma-x11 kwin_x11 plasmashell dbus-run-session Xtigervnc xdpyinfo xprop; do \
        command -v "$binary" >/dev/null || { echo "FATAL: required desktop binary missing: $binary" >&2; exit 1; }; \
    done \
    && test -x /usr/bin/kwin_x11
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=8s --start-period=180s --retries=3 \
    CMD /usr/bin/python3 /opt/recovery/health.py --once || exit 1
ENTRYPOINT ["/usr/bin/tini", "--", "/opt/recovery/entrypoint.sh"]
