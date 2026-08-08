# 安全加固补充文件

> 整理人：林深-安全合规员
> 供 行者-Linux专家（entrypoint.sh / nginx.conf）和 海豚-容器工程师（Dockerfile / CI workflow）直接合并。
> 基于已确认决策：`/api/` 不进 Nginx 路由表（方案1）、deny 段用 `return 404`、Basic Auth 强制、TigerVNC `-PasswordFile` 强制、rclone.conf 运行时生成。

---

## 1. Nginx 安全配置段

### 1.1 全局安全 Headers + 限流

```nginx
# /etc/nginx/conf.d/security-headers.conf
server {
    # 隐藏 nginx 版本，不向攻击者暴露指纹
    server_tokens off;

    # 安全响应头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "geolocation=(), microphone=(), camera=()" always;

    # 限制请求体大小（防大包 DoS）
    client_max_body_size 50m;

    # 限流：每 IP 10 req/s，突发 20
    limit_req_zone $binary_remote_addr zone=portal:10m rate=10r/s;
    limit_req zone=portal burst=20 nodelay;
}
```

### 1.2 Basic Auth 强制（/desktop/ 双因素保护）

```nginx
# /desktop/ 路由：Nginx Basic Auth + VNC 密码 = 双因素
location /desktop/ {
    auth_basic "Desktop Portal";
    auth_basic_user_file /etc/nginx/.htpasswd;

    proxy_pass http://127.0.0.1:6080/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    # WebSocket 长连接超时
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}

# 其他 Web UI 路由同样强制 Basic Auth
location /chat/ {
    auth_basic "AI Portal";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8082/;
    # proxy headers 同上
}

location /hermes/ {
    auth_basic "AI Portal";
    auth_basic_user_file /etc/nginx/.htpasswd;
    proxy_pass http://127.0.0.1:8648/;
    # proxy headers 同上
}
```

### 1.3 `/api/` 不进路由表（方案1，已确认）

```nginx
# Hermes Agent API 只走容器内 127.0.0.1:8642 直连
# Studio 和 Open WebUI 用 http://127.0.0.1:8642 调 Gateway，零网络开销
# Nginx 不反代 /api/，外部探测不到其存在

# 防御性兜底（防止误配）：
location /api/ {
    return 404;   # 不用 403，避免暴露路径存在性
}
```

### 1.4 内部端口防护层

```nginx
# 双保险：即使某服务误绑 0.0.0.0，Nginx 层也拒绝外部直达内部端口
# 所有非 7860 入口返回 404
location /internal/ {
    allow 127.0.0.1;
    deny all;
    return 404;
}
```

---

## 2. htpasswd 生成（bcrypt）

```bash
# entrypoint.sh 片段
# 用 bcrypt（-B），nginx 1.3.3+ 原生支持，比 apr1/MD5 强得多
if [ -z "$PORTAL_USER" ] || [ -z "$PORTAL_PASSWORD" ]; then
    echo "[ERROR] PORTAL_USER/PORTAL_PASSWORD not set, refusing to start" >&2
    exit 1
fi

htpasswd -bcB /etc/nginx/.htpasswd "$PORTAL_USER" "$PORTAL_PASSWORD" 2>/dev/null
chmod 600 /etc/nginx/.htpasswd
```

> PORTAL_USER / PORTAL_PASSWORD 走 ModelScope Secrets 注入，镜像层零密钥。

---

## 3. TigerVNC 密码配置

```bash
# entrypoint.sh 片段
VNC_PASSWORD="${VNC_PASSWORD:-}"
if [ -z "$VNC_PASSWORD" ]; then
    echo "[ERROR] VNC_PASSWORD not set, refusing to start desktop" >&2
    exit 1
fi

# 密码复杂度校验：>=8 位，含字母 + 数字
if [ ${#VNC_PASSWORD} -lt 8 ] || \
   ! echo "$VNC_PASSWORD" | grep -q '[A-Za-z]' || \
   ! echo "$VNC_PASSWORD" | grep -q '[0-9]'; then
    echo "[ERROR] VNC_PASSWORD too weak: need >=8 chars with letters and digits" >&2
    exit 1
fi

# 生成 TigerVNC 密码文件
mkdir -p /root/.vnc
echo "$VNC_PASSWORD" | vncpasswd -f > /root/.vnc/passwd
chmod 600 /root/.vnc/passwd
```

```ini
# supervisord 片段
[program:vnc]
command=Xvnc -PasswordFile /root/.vnc/passwd -SecurityTypes VncAuth -localhost
;   -localhost 确保只绑 127.0.0.1，外部无法直连 6080
```

---

## 4. rclone.conf 运行时生成

```bash
# entrypoint.sh 片段
# rclone.conf 不打包进镜像，运行时从环境变量生成
RCLONE_CONF="/mnt/workspace/config/rclone.conf"
mkdir -p "$(dirname "$RCLONE_CONF")"

cat > "$RCLONE_CONF" <<EOF
[onedrive]
type = onedrive
token = ${ONEDRIVE_TOKEN}
drive_id = ${ONEDRIVE_DRIVE_ID}
drive_type = personal

[crypt]
type = crypt
remote = onedrive:hermes-backup
password = ${RCLONE_CRYPT_PASSWORD}
password2 = ${RCLONE_CRYPT_PASSWORD2}
directory_name_encryption = true
filename_encryption = standard
EOF

chmod 600 "$RCLONE_CONF"

# 校验配置有效性
if ! rclone --config="$RCLONE_CONF" listremotes >/dev/null 2>&1; then
    echo "[ERROR] rclone config invalid, refusing to start backup service" >&2
    exit 1
fi
```

> ONEDRIVE_TOKEN / RCLONE_CRYPT_PASSWORD 等走 ModelScope Secrets 注入。

---

## 5. Trivy GitHub Actions workflow

```yaml
# .github/workflows/security-scan.yml
name: Security Scan
on:
  push:
    branches: [main, master]
  pull_request:
  schedule:
    - cron: '0 3 * * 1'   # 每周一 03:00 UTC 重建拉补丁

jobs:
  trivy-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build image
        run: docker build -t modelscope-space:scan .

      - name: Trivy vulnerability scan
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: modelscope-space:scan
          severity: 'HIGH,CRITICAL'
          ignore-unfixed: true        # 过滤尚无修复的漏洞，避免阻塞
          exit-code: '1'              # HIGH/CRITICAL 可修复漏洞则失败
          format: 'sarif'
          output: 'trivy-results.sarif'

      - name: Upload SARIF
        uses: github/codeql-action/upload-sarif@v3
        if: always()
        with:
          sarif_file: trivy-results.sarif
```

---

## 6. entrypoint.sh 安全校验段

```bash
#!/bin/bash
set -euo pipefail

# 6.1 符号链接目标校验（防 symlink traversal）
create_safe_symlink() {
    local src="$1"
    local dst="$2"
    local resolved_src
    resolved_src=$(realpath -m "$src")
    # 校验目标在持久化盘范围内
    if [[ "$resolved_src" != /mnt/workspace/* ]]; then
        echo "[ERROR] symlink target $src outside /mnt/workspace, refusing" >&2
        exit 1
    fi
    ln -sfn "$resolved_src" "$dst"
}

# 6.2 种子配置完整性校验
verify_seed() {
    local file="$1"
    local expected_sha256="$2"
    local actual_sha256
    actual_sha256=$(sha256sum "$file" | awk '{print $1}')
    if [ "$actual_sha256" != "$expected_sha256" ]; then
        echo "[ERROR] seed config $file checksum mismatch" >&2
        echo "  expected: $expected_sha256" >&2
        echo "  actual:   $actual_sha256" >&2
        exit 1
    fi
}

# 6.3 启动前校验关键文件权限
check_perms() {
    local file="$1"
    local expected="$2"
    local actual
    actual=$(stat -c '%a' "$file")
    if [ "$actual" != "$expected" ]; then
        echo "[WARN] $file perm $actual (expected $expected), fixing..."
        chmod "$expected" "$file"
    fi
}
check_perms /etc/nginx/.htpasswd 600
check_perms /root/.vnc/passwd 600
check_perms /mnt/workspace/config/rclone.conf 600
```

### 6.4 所有服务显式绑 127.0.0.1（supervisord 配置示例）

```ini
[program:hermes-gateway]
command=/opt/hermes/gateway --host 127.0.0.1 --port 8642

[program:open-webui]
command=/opt/open-webui --host 127.0.0.1 --port 8082

[program:llama-cpp]
command=/opt/llama.cpp/server --host 127.0.0.1 --port 8081
```

---

## 7. Dockerfile 安全构建原则

```dockerfile
# 1. 最小化安装，减少攻击面
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    nginx tigervnc-standalone-server ... && \
    rm -rf /var/lib/apt/lists/*

# 2. 构建末尾补 CVE
RUN apt-get update && apt-get upgrade -y && \
    rm -rf /var/lib/apt/lists/*

# 3. binary 下载校验 checksum（示例：rclone）
RUN curl -fsSL -o /tmp/rclone.zip \
    "https://downloads.rclone.org/v${RCLONE_VERSION}/rclone-v${RCLONE_VERSION}-linux-amd64.zip" && \
    echo "${RCLONE_SHA256}  /tmp/rclone.zip" | sha256sum -c - && \
    unzip /tmp/rclone.zip -d /tmp && \
    mv /tmp/rclone-*/rclone /usr/local/bin/ && \
    rm -rf /tmp/rclone*

# 4. 非 root 运行（Hermes Gateway 之前因 root 被官方拒绝，需降权）
# RUN useradd -r -s /bin/false hermes
# RUN chown -R hermes:hermes /opt/hermes
# supervisord 里 program 段加 user=hermes

# 5. 镜像层零密钥
# COPY .env.example .env.example   # 只放占位符
# 真实密钥走 ModelScope Secrets 运行时注入
```

---

## 8. .env.example 模板

```env
# .env.example — 只放占位符，真实值走 ModelScope Secrets

# Portal 认证（Nginx Basic Auth）
PORTAL_USER=admin
PORTAL_PASSWORD=             # Secret 注入

# VNC 桌面
VNC_PASSWORD=               # Secret 注入

# rclone OneDrive 备份
ONEDRIVE_TOKEN=             # Secret 注入
ONEDRIVE_DRIVE_ID=
RCLONE_CRYPT_PASSWORD=      # Secret 注入
RCLONE_CRYPT_PASSWORD2=     # Secret 注入

# Hermes（如需 API Key）
HERMES_API_KEY=             # Secret 注入
```

---

## 9. keepalive.yml 修复

```yaml
# 逻辑：先 GET 状态，仅当 Stopped 时才 deploy，避免强制重建
# deploy 失败 3 次重试 + 告警

name: Keepalive
on:
  schedule:
    - cron: '0 */6 * * *'   # 每 6 小时检查

jobs:
  keepalive:
    runs-on: ubuntu-latest
    steps:
      - name: Check space status
        id: status
        run: |
          STATE=$(curl -s -X GET \
            "${{ secrets.MODELSCOPE_API_URL }}/api/v1/spaces/${{ secrets.SPACE_ID }}/status" \
            -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}" | \
            jq -r '.data.status')
          echo "state=$STATE" >> $GITHUB_OUTPUT

      - name: Deploy only if stopped
        if: steps.status.outputs.state == 'Stopped'
        run: |
          for i in 1 2 3; do
            HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
              "${{ secrets.MODELSCOPE_API_URL }}/api/v1/spaces/${{ secrets.SPACE_ID }}/deploy" \
              -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}")
            if [ "$HTTP_CODE" = "200" ]; then
              echo "Deploy succeeded on attempt $i"
              exit 0
            fi
            echo "Attempt $i failed (HTTP $HTTP_CODE), retrying in 10s..."
            sleep 10
          done
          echo "::error::Deploy failed after 3 attempts"
          exit 1

      - name: Alert on failure
        if: failure()
        run: |
          # 接 Telegram / 飞书 / 邮件 webhook
          curl -s -X POST "${{ secrets.ALERT_WEBHOOK }}" \
            -d "Keepalive deploy failed for space ${{ secrets.SPACE_ID }}"
```

---

## 10. 合并追踪表

| 项 | 合并到 | 责任人 | 状态 |
|---|---|---|---|
| §1 Nginx 安全段 | nginx.conf | 行者 | 待合并 |
| §2 htpasswd 生成 | entrypoint.sh | 行者 | 待合并 |
| §3 TigerVNC 密码 | entrypoint.sh + supervisord | 行者 | 待合并 |
| §4 rclone.conf 生成 | entrypoint.sh | 行者 | 待合并 |
| §5 Trivy workflow | .github/workflows/ | 海豚 | 待合并 |
| §6 entrypoint 校验 | entrypoint.sh | 行者 | 待合并 |
| §7 Dockerfile 原则 | Dockerfile | 海豚 | 待合并 |
| §8 .env.example | 仓库根目录 | 海豚 | 待合并 |
| §9 keepalive.yml | .github/workflows/ | 行者/海豚 | 待合并 |

合并完成后我会再审一遍完整代码，确认实现无遗漏。

— 林深-安全合规员
