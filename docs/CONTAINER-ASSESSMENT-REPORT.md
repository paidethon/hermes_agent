# 容器化评估报告 — Zephyr AI Desktop

> **编写人**：海豚-容器工程师
> **日期**：2026-08-08
> **状态**：交付件已完成，待最终联调

---

## 一、交付文件清单

| 文件 | 位置 | 职责 |
|------|------|------|
| **Dockerfile** | `zephyr-configs/Dockerfile` | 三阶段构建（llama.cpp 编译 → Hermes Studio 前端 → 最终镜像） |
| **docker-compose.yml** | `zephyr-configs/docker-compose.yml` | 本地开发/测试环境 |
| **.env.example** | `zephyr-configs/.env.example` | 环境变量模板（镜像层零密钥） |
| **.dockerignore** | `zephyr-configs/.dockerignore` | 构建上下文排除 |
| **build.yml** | `zephyr-configs/.github/workflows/build.yml` | GHCR 镜像构建 CI |
| **security-scan.yml** | `zephyr-configs/.github/workflows/security-scan.yml` | Trivy 每日漏洞扫描（§5） |
| **first-run-init.sh** | `zephyr-configs/scripts/first-run-init.sh` | 首次运行初始化（模型下载/备份恢复/种子配置） |
| **backup.sh** | `zephyr-configs/scripts/backup.sh` | rclone crypt → OneDrive 加密备份 |
| **restore.sh** | `zephyr-configs/scripts/restore.sh` | 从 OneDrive 恢复 |
| **health-check.sh** | `zephyr-configs/scripts/health-check.sh` | 容器健康检查 |
| **portal/index.html** | `zephyr-configs/portal/index.html` | Portal 导航页 |
| **hermes-seed/config.yaml** | `zephyr-configs/config/hermes-seed/config.yaml` | Hermes 种子配置 |
| **rclone.template.conf** | `zephyr-configs/config/rclone.template.conf` | rclone 模板 |

---

## 二、Dockerfile 多阶段构建设计

### Stage 1: llama.cpp 编译
- 基础镜像：`ubuntu:24.04`
- 安装 git/cmake/build-essential，编译 llama.cpp 最新 tag
- 产物：`/opt/llama.cpp/build/bin/llama-server`
- 编译工具链不进入最终镜像，减小体积

### Stage 2: Hermes Studio 前端构建
- 基础镜像：`node:22-slim`
- `npm install` + `npm run build`
- 产物：`/opt/hermes-studio/dist/`
- node_modules 不进入最终镜像

### Stage 3: 最终运行镜像
- 基础镜像：`ubuntu:24.04`
- 分层设计：

| 层 | 内容 | 预估体积 |
|---|------|---------|
| 1 | 系统基础（KDE Plasma + TigerVNC + noVNC + Chrome + fcitx5 + Nginx + Supervisor） | ~800 MB |
| 2 | 运行时（Python 3.11 + Node.js 22 + uv） | ~200 MB |
| 3 | Hermes Agent（git clone + pip install） | ~100 MB |
| 4 | Hermes Studio（从 Stage 2 拷贝） | ~50 MB |
| 5 | Open WebUI 0.11.0 | ~150 MB |
| 6 | ModelScope SDK + 模型层（默认不预下载） | ~50 MB |
| 6.5 | llama.cpp binary（从 Stage 1 拷贝） | ~5 MB |
| 7 | Nginx + Supervisord 配置 | ~1 MB |
| 8 | 入口脚本 + 工具脚本 | ~1 MB |
| 9 | 可选模块开关 | 0 |
| 10 | Portal 导航页 + 种子配置 | ~1 MB |
| 末尾 | apt upgrade 安全加固 | 0 |
| **合计** | | **~1.4 GB** |

---

## 三、路径对齐表（Dockerfile ↔ supervisord.conf）

| 组件 | supervisord.conf 中的路径 | Dockerfile 中的安装路径 | 状态 |
|------|--------------------------|----------------------|------|
| Nginx | `/usr/sbin/nginx` | apt 安装 | ✅ |
| TigerVNC | `Xvnc` | `tigervnc-standalone-server` | ✅ |
| noVNC | `/opt/novnc/utils/novnc_proxy` | 下载到 `/opt/novnc/` | ✅ |
| Hermes Agent | `/opt/hermes/gateway` | git clone 到 `/opt/hermes/` | ✅ |
| Hermes Studio | `node /opt/hermes-studio/server.js` | 从 Stage 2 拷贝到 `/opt/hermes-studio/` | ✅ |
| Open WebUI | `open-webui serve` | pip install | ✅ |
| llama.cpp | `/opt/llama.cpp/llama-server` | symlink → `bin/llama-server` | ✅ |
| 模型文件 | `/mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf` | first-run-init.sh 下载 | ✅ |
| Supervisord 配置 | `/etc/supervisor/conf.d/supervisord.conf` | COPY 到同路径 | ✅ |
| Nginx 配置 | `/etc/nginx/nginx.conf` + `/etc/nginx/conf.d/portal.conf` | COPY 到同路径 | ✅ |
| Entrypoint | `/opt/entrypoint.sh` | COPY + chmod +x | ✅ |

---

## 四、安全加固措施（§7）

| 措施 | 实现方式 | 状态 |
|------|---------|------|
| `--no-install-recommends` | 所有 apt-get install 均使用 | ✅ |
| 构建末尾 `apt upgrade` | 层 10 之后的最终 RUN | ✅ |
| 非 root 用户 | 创建 `hermes` 用户，supervisord 以 `user=hermes` 运行 Hermes/llama.cpp | ✅ |
| 镜像层零密钥 | 所有密钥通过 `.env` / ModelScope Secrets 运行时注入 | ✅ |
| noVNC SHA256 校验 | 下载后校验（hash 可更新） | ✅ |
| Trivy 漏洞扫描 | `security-scan.yml` 每日扫描 + push 触发 | ✅ |
| rclone.conf 运行时生成 | entrypoint.sh 从环境变量生成，不写入镜像 | ✅ |
| .htpasswd 运行时生成 | entrypoint.sh 从 PORTAL_USER/PORTAL_PASSWORD 生成 bcrypt | ✅ |

---

## 五、已合并的其他 Agent 交付件

| 来源 | 文件 | 合并方式 |
|------|------|---------|
| 行者-Linux专家 | `entrypoint.sh` | COPY 到 `/opt/entrypoint.sh` |
| 行者-Linux专家 | `supervisord.conf` | COPY 到 `/etc/supervisor/conf.d/supervisord.conf` |
| 行者-Linux专家 | `nginx.conf` | COPY 到 `/etc/nginx/nginx.conf` |
| 行者-Linux专家 | `portal.conf` | COPY 到 `/etc/nginx/conf.d/portal.conf` |
| 行者-Linux专家 | `keepalive.yml` | 保留在 `.github/workflows/` |
| 极客-AI模型通 | `model-download.sh` | COPY 到 `/opt/zephyr/scripts/` |
| 极客-AI模型通 | `modelscope-api-test.py` | COPY 到 `/opt/zephyr/scripts/` |
| 极客-AI模型通 | `llama-cpp.env` | COPY 到 `/opt/zephyr/config/` |
| 极客-AI模型通 | `open-webui-models.env` | COPY 到 `/opt/zephyr/config/` |
| 林深-安全合规员 | 安全加固原则 §7 | 已全部实施 |
| 林深-安全合规员 | Trivy 扫描 §5 | 已合并为 `security-scan.yml` |

---

## 六、待协调问题

| # | 问题 | 负责人 | 状态 |
|---|------|--------|------|
| 1 | Open WebUI priority=60 在 llama-cpp priority=70 之前启动 | 行者 | 已通知，建议改为 55/65 |
| 2 | S2: OPENAI_API_KEY 值不一致（`sk-zephyr-local` vs `sk-zephyr-local-not-needed`） | 极客 | 极客已认领处理中 |
| 3 | M1: API Key 可能打印到日志 | 极客 | 极客已认领处理中 |
| 4 | M2: llama.cpp 缺 `--api-key` 参数 | 极客 | 极客已认领处理中 |
| 5 | llama-cpp.env 中 `LLAMA_CPP_START_CMD` 未被 supervisord 引用 | 极客 | 极客已认领处理中 |
| 6 | M3: pip install modelscope 版本固定 | 海豚 | ✅ 已修复（`>=1.14.0`） |

---

## 七、构建与部署流程

```
GitHub Push → build.yml 触发
    ↓
Docker 多阶段构建（Stage 1-3）
    ↓
推送到 GHCR (ghcr.io/zephyr17/zephyr-ai-desktop:latest)
    ↓
Trivy 安全扫描
    ↓
ModelScope 空间 FROM ghcr.io/zephyr17/zephyr-ai-desktop:latest
    ↓
entrypoint.sh 执行
    ├── init_persistence（持久化目录初始化）
    ├── generate_htpasswd（Nginx Basic Auth）
    ├── generate_vnc_password（TigerVNC 密码）
    ├── generate_rclone_config（rclone OneDrive）
    ├── final_permission_check（权限校验）
    └── exec supervisord（启动所有服务）
         ├── Nginx :7860（唯一对外端口）
         ├── TigerVNC + noVNC（桌面）
         ├── Hermes Gateway :8642（127.0.0.1）
         ├── Hermes Studio :8648（127.0.0.1）
         ├── Open WebUI :8082（127.0.0.1）
         └── llama.cpp :8081（127.0.0.1）
```

---

## 八、本地测试

```bash
# 1. 复制环境变量模板
cp .env.example .env
# 编辑 .env 填入真实密码

# 2. 构建并启动
docker compose up --build

# 3. 访问
# http://localhost:7860 — Portal 导航页
# http://localhost:7860/desktop/ — KDE 桌面
# http://localhost:7860/chat/ — Open WebUI
```

---

## 九、注意事项

1. **Hermes Agent/Studio 仓库地址**：Dockerfile 中使用了 `https://github.com/NousResearch/hermes-agent.git` 和 `https://github.com/EKKOLearnAI/hermes-studio.git` 作为占位符。如果实际仓库地址不同，请修改 Dockerfile 中的 `git clone` 命令。

2. **模型预下载**：默认 `PRELOAD_QWEN3_8B=0`，首次启动时由 `first-run-init.sh` 下载（约 5GB，需 10-20 分钟）。如需构建时预下载，在 `build.yml` 中设置 `preload_model: true`。

3. **ModelScope 空间 Dockerfile**：ModelScope 空间只需一行 Dockerfile：
   ```dockerfile
   FROM ghcr.io/zephyr17/zephyr-ai-desktop:latest
   ```

4. **GitHub Secrets**：需要在 GitHub 仓库后台配置以下 Secrets：
   - `GITHUB_TOKEN`（自动提供）
   - `MODELSCOPE_TOKEN`
   - `SPACE_ID`（`zephyr17/hermes_agent`）
   - `ALERT_WEBHOOK`（可选）
