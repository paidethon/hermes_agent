# Zephyr AI Desktop — 魔搭空间构建方案

> 基于你与 ChatGPT 的 6 轮对话整理，去除了 OpenClaw / LobeHub / Dify / Ollama / vLLM / ComfyUI，保留：云桌面 + Hermes + Open WebUI + 持久化 + OneDrive 加密备份。

---

## 一、核心问题回顾

你现在遇到的问题有三个根因：

| 问题 | 根因 | 本方案如何解决 |
|------|------|----------------|
| Hermes 每次重启被重置 | 数据在 `/root/hermes-data`（容器可写层，不持久） | 所有数据软链接到 `/mnt/workspace/zephyr/` |
| Hermes Gateway 无限崩溃 | 以 root 用户运行，触发安全拒绝 | 以非 root 用户（hermes）运行 |
| GitHub Action "保活"导致重建 | `POST /deploy` 实际是"重启/重新部署" | 保留保活但数据已持久化，重启不丢 |

---

## 二、需要你确认的选择方案

### 选择 1：基础操作系统

| 方案 | 说明 | 推荐度 |
|------|------|--------|
| **A. Ubuntu 24.04 LTS** | AI 生态最成熟，支持到 2029 年，Python 3.11/3.12 兼容性好 | ⭐⭐⭐⭐⭐ |
| B. Debian 13.6 | 更精简，但部分 AI 软件需手动处理 Python 版本 | ⭐⭐⭐⭐ |
| C. 继承 TunMax Debian 12 | 兼容性已验证，但底层构建不透明 | ⭐⭐⭐ |

> **我的建议：A（Ubuntu 24.04 LTS）** — 从官方 `ubuntu:24.04` 开始构建，完全可控、可复现。

---

### 选择 2：桌面环境

| 方案 | 说明 | 资源占用 |
|------|------|----------|
| **A. KDE Plasma** | 类 Windows 体验，功能丰富 | 中等 |
| B. Xfce | 轻量级，省内存给 AI 服务 | 低 |
| C. KDE 精简配置 | KDE 但关闭部分特效 | 中低 |

> **我的建议：A（KDE Plasma）** — 你已习惯 TunMax 的类 Windows 体验。

---

### 选择 3：Hermes 版本组合

| 方案 | Hermes Agent | Hermes Studio | 说明 |
|------|-------------|---------------|------|
| **A. 最新稳定** | 0.18.2 | 0.6.39 | 当前官方 Latest |
| B. 保守稳定 | 0.18.1 | 0.6.38 | 出问题时回滚选择 |
| C. TunMax 自带 | 0.15.2 | — | 版本偏旧，不推荐 |

> **我的建议：A（Hermes 0.18.2 + Studio 0.6.39）**

---

### 选择 4：Web 管理界面

| 方案 | 说明 | Star |
|------|------|------|
| **A. Open WebUI 0.11.0** | 通用 AI 聊天界面，官方支持 Hermes 集成 | 148k |
| B. Open WebUI + AnythingLLM | 额外加文档知识库/RAG | 148k + 64.5k |
| C. Open WebUI + Flowise | 额外加可视化 AI 工作流 | 148k + 55.2k |

> **我的建议：A 起步，后续按需开启 B/C** — 镜像里做成可选模块（`ENABLE_ANYTHINGLLM=0`、`ENABLE_FLOWISE=1`）。

---

### 选择 5：持久化与备份方案

| 方案 | 本地持久化 | 异地备份 | 加密 |
|------|-----------|---------|------|
| **A. 推荐** | `/mnt/workspace/zephyr/` | rclone → OneDrive API | rclone crypt |
| B. 简单 | `/mnt/workspace/zephyr/` | 无 | 无 |
| C. 双备份 | `/mnt/workspace/zephyr/` | OneDrive + WebDAV | rclone crypt |

> **关键提醒：** OneDrive 不走 WebDAV（微软已不正式支持），走 rclone 的 OneDrive OAuth 后端更稳定。
> **备份策略：** 用 `rclone copy`（不删远端文件）而非 `rclone sync`（可能删数据）。
> **我的建议：A**

---

### 选择 6：公网访问与安全

| 方案 | 空间可见性 | 入口认证 | 风险 |
|------|-----------|---------|------|
| **A. 推荐** | Private | Nginx Portal 登录 + 各 App 自身认证 | 🟢 低 |
| B. 中等 | Private | 仅各 App 自身认证 | 🟡 中 |
| C. 不推荐 | Public | 仅各 App 自身认证 | 🔴 高 |

> **三道门设计：**
> 1. ModelScope Private（需登录你的账号）
> 2. Nginx Portal（独立用户名+强密码）
> 3. 各 App 自身认证（VNC 密码 / Hermes Token / Open WebUI 登录）
>
> **我的建议：A**

---

### 选择 7：Nginx 路由设计

所有服务通过 ModelScope 唯一公网端口 7860 进入，Nginx 按路径分流：

| 路径 | 指向 | 内部端口 |
|------|------|---------|
| `/` | Zephyr Portal 首页（导航页） | Nginx 本地 |
| `/desktop/` | KDE 桌面 noVNC | 6080 |
| `/hermes/` | Hermes Studio | 8648 |
| `/chat/` | Open WebUI | 8080 |
| `/flow/` | Flowise（可选） | 3000 |
| `/api/hermes/` | Hermes Gateway API（内部） | 8642 |

> **注意：** 每个服务的子路径（base_path）、WebSocket、静态资源需要分别配置。不是简单写几行 `proxy_pass` 就行。
>
> **这是本方案最复杂的工程点之一。**

---

## 三、最终架构总览

```
┌──────────────────────────────────────────────┐
│           Zephyr AI Desktop                  │
│                                              │
│  Ubuntu 24.04 LTS                            │
│  ├── KDE Plasma 桌面                         │
│  │   ├── Chrome 浏览器                       │
│  │   ├── fcitx5 中文输入                     │
│  │   ├── Konsole / Dolphin / Ark             │
│  │   └── TigerVNC + noVNC                    │
│  │                                           │
│  ├── AI 核心                                 │
│  │   ├── Hermes Agent 0.18.2 (非 root)       │
│  │   ├── Hermes Studio 0.6.39 (非 root)      │
│  │   └── Open WebUI 0.11.0                   │
│  │                                           │
│  ├── 可选 AI（构建时开关）                    │
│  │   ├── llama.cpp (ENABLE_LLAMA_CPP=1)      │
│  │   └── Flowise (ENABLE_FLOWISE=1)          │
│  │                                           │
│  ├── 运行环境                                │
│  │   ├── Python 3.11 venv                    │
│  │   ├── Node.js 22 LTS                      │
│  │   ├── uv / git / ffmpeg / jq / ripgrep    │
│  │   └── rclone                              │
│  │                                           │
│  ├── 存储                                    │
│  │   └── /mnt/workspace/zephyr/              │
│  │       ├── hermes/         (配置/记忆/会话) │
│  │       ├── hermes-studio/  (Studio DB)     │
│  │       ├── open-webui/     (WebUI DB)      │
│  │       ├── models/         (GGUF 模型)     │
│  │       ├── desktop/        (桌面文件)      │
│  │       ├── projects/       (项目代码)      │
│  │       ├── rclone/         (rclone 配置)   │
│  │       └── backups/        (本地快照)      │
│  │                                           │
│  ├── 备份                                    │
│  │   └── rclone crypt → OneDrive             │
│  │       (每日定时 copy，不删远端)            │
│  │                                           │
│  ├── 入口                                    │
│  │   └── Nginx :7860 (唯一公网端口)           │
│  │                                           │
│  └── 安全                                    │
│      ├── ModelScope Private                  │
│      ├── Portal 登录认证                      │
│      ├── VNC 强密码                           │
│      ├── Hermes AUTH_TOKEN                   │
│      └── 所有密钥走 ModelScope Secrets        │
└──────────────────────────────────────────────┘
                    ↑
                    │ HTTPS
                    │
          ModelScope 公网入口 (7860)
                    │
           手机 / Windows / Mac / iPad
```

---

## 四、数据持久化细节

### 软链接映射

程序看到的路径 → 实际持久化路径：

```
/root/hermes-data          → /mnt/workspace/zephyr/hermes
/root/.hermes-web-ui       → /mnt/workspace/zephyr/hermes-studio
/app/backend/data          → /mnt/workspace/zephyr/open-webui  (Open WebUI)
/root/.flowise             → /mnt/workspace/zephyr/flowise
/root/Desktop              → /mnt/workspace/zephyr/desktop
```

### 启动时自动恢复逻辑

```bash
# 容器启动时执行：
# 1. 检查 /mnt/workspace/zephyr/ 是否有备份数据
# 2. 有 → 软链接到程序期望路径
# 3. 无 → 首次初始化，创建默认配置
# 4. 启动所有服务
```

### OneDrive 加密备份

```
每日 03:00 执行：
  /mnt/workspace/zephyr/
      ↓ tar + zstd 压缩
  zephyr-2026-08-09.tar.zst
      ↓ rclone crypt 加密
  OneDrive /zephyr-backups/
      ↓ copy（不删除远端文件）

保留策略：
  - 本地 backups/：最近 7 天
  - OneDrive：最近 30 天
```

---

## 五、Dockerfile 构建策略

### 分层构建

```dockerfile
# Stage 1: 基础桌面环境
FROM ubuntu:24.04
# 安装 KDE / VNC / noVNC / Chrome / fcitx5

# Stage 2: AI 运行环境
# Python 3.11 venv + Node.js 22 + uv + 工具链

# Stage 3: Hermes Agent + Studio
# 非 root 用户 hermes 安装

# Stage 4: Open WebUI
# 从官方镜像或源码构建

# Stage 5: Nginx Portal
# 反向代理配置

# 最终：supervisord 统一管理所有进程
```

### 构建参数（可选模块）

```dockerfile
ARG ENABLE_LLAMA_CPP=1
ARG ENABLE_FLOWISE=1
ARG ENABLE_ANYTHINGLLM=0
ARG ENABLE_OLLAMA=0
ARG HERMES_VERSION=0.18.2
ARG HERMES_STUDIO_VERSION=0.6.39
ARG OPENWEBUI_VERSION=0.11.0
```

---

## 六、ModelScope 空间配置

### 空间设置

| 配置项 | 值 |
|--------|-----|
| 空间类型 | Custom Docker |
| 可见性 | **Private** |
| 对外端口 | 7860（固定） |
| 硬件 | 至少 2 核 / 16GB 内存 |

### Secrets（不写入 Dockerfile）

```
ROOT_PASSWD        — root 强密码
VNC_PASSWD         — VNC 强密码
ZEPHYR_USERNAME    — Portal 登录用户名
ZEPHYR_PASSWORD    — Portal 登录密码
HERMES_AUTH_TOKEN  — Hermes 认证 Token
HERMES_JWT_SECRET  — Hermes JWT 密钥
OPENWEBUI_SECRET_KEY — Open WebUI 密钥
MODELSCOPE_API_KEY — 模型 API Key
RCLONE_ONEDRIVE_CLIENT_ID    — OneDrive OAuth
RCLONE_ONEDRIVE_CLIENT_SECRET — OneDrive OAuth
RCLONE_ONEDRIVE_TOKEN        — OneDrive Token
BACKUP_ENC_PASS    — 备份加密密码
```

### GitHub Actions 保活

```yaml
# 保留你现有的 keepalive.yml
# 但理解：POST /deploy = 重启，不是 ping
# 数据已持久化到 /mnt/workspace，重启不丢
```

---

## 七、魔搭空间仓库文件结构

```
zephyr-ai-desktop/
├── Dockerfile                 # 主构建文件
├── docker-compose.yml         # 本地测试用
├── README.md                  # 中文部署文档
├── .github/
│   └── workflows/
│       └── keepalive.yml      # 保活 Action
├── scripts/
│   ├── entrypoint.sh          # 容器入口
│   ├── init-persist.sh        # 持久化初始化
│   ├── start-services.sh      # 启动所有服务
│   ├── backup.sh              # OneDrive 备份脚本
│   └── zephyr-status.sh       # 状态检查命令
├── configs/
│   ├── nginx.conf             # Nginx 反向代理配置
│   ├── supervisord.conf       # 进程管理配置
│   └── desktop/
│       ├── tigervnc.conf      # VNC 配置
│       └── kde-profile/       # KDE 默认配置
└── modelscope/
    └── Dockerfile             # ModelScope 部署用 Dockerfile
```

---

## 八、实施步骤（你确认后执行）

1. **生成完整代码** — Dockerfile + 所有脚本 + 配置文件
2. **生成 README** — 中文部署文档
3. **打包发送** — 将完整工程发送到群聊
4. **你上传到 GitHub** — 新建仓库并推送
5. **ModelScope 创建空间** — Custom Docker，Private
6. **配置 Secrets** — 在 ModelScope 后台添加所有密钥
7. **部署** — 空间自动构建并启动
8. **验证** — 检查持久化、备份、各服务状态

---

## 九、需要你确认的 7 个选择

请逐项回复你的选择（或直接说"全部按推荐"）：

| # | 选择项 | 推荐方案 |
|---|--------|---------|
| 1 | 基础操作系统 | A. Ubuntu 24.04 LTS |
| 2 | 桌面环境 | A. KDE Plasma |
| 3 | Hermes 版本 | A. 0.18.2 + Studio 0.6.39 |
| 4 | Web 管理界面 | A. Open WebUI 0.11.0（+可选 Flowise） |
| 5 | 持久化与备份 | A. /mnt/workspace + rclone crypt → OneDrive |
| 6 | 公网访问与安全 | A. Private + Portal 认证 + 三道门 |
| 7 | Nginx 路由 | 按推荐路径分流 |

---

> **确认后我会立即开始生成完整的 Docker 工程代码。**
