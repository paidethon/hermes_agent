# Zephyr AI Desktop — 魔搭空间构建方案（供确认）

> 以下是基于你在 ChatGPT 对话中确认的全部需求，整理出的**完整选择清单与架构方案**。  
> 请逐项确认或修改，你确认后我再生成代码和仓库。

---

## 一、当前问题回顾（为什么需要重建）

| 问题 | 原因 |
|---|---|
| Hermes 每次打开被重置 | 数据存在 `/root/hermes-data`（容器层），不在 `/mnt/workspace` 持久化盘 |
| Hermes Gateway 崩溃循环 | 镜像以 root 运行，Hermes 官方拒绝 root 启动 |
| 保活只保空间状态 | GitHub keepalive 只是调用 ModelScope API 重启空间，不备份数据 |
| 不清楚哪些文件保留 | 只有 `/mnt/workspace` 下的内容在容器重建后保留 |

---

## 二、核心设计原则

1. **所有运行数据 → `/mnt/workspace/zephyr/`**（ModelScope 唯一持久化路径）
2. **Hermes 以非 root 用户运行**（解决 Gateway 拒绝启动问题）
3. **单一入口 Nginx :7860**（ModelScope Custom Docker 唯一对外端口）
4. **从 `ubuntu:24.04` 官方镜像自建**（不依赖 TunMax/comedy1024 封闭镜像）
5. **rclone + OneDrive 异地加密备份**（非 WebDAV，OneDrive 官方已弃用 WebDAV）

---

## 三、需要你逐项确认的选择

### 选择 1：操作系统

| 选项 | 系统 | 说明 |
|---|---|---|
| **A ★推荐** | Ubuntu 24.04 LTS | 支持到 2029 年，社区文档丰富，KDE Plasma 5.27 稳定 |
| B | Debian 13 (Trixie) | 当前 stable，Plasma 6.3，更轻量但生态略少 |
| C | Ubuntu 26.04 LTS | 最新 LTS（如已发布），但镜像兼容性未充分验证 |

> **推荐理由**：Ubuntu 24.04 LTS 生命周期长、PPA 生态成熟、ModelScope 社区案例多。

---

### 选择 2：桌面环境

| 选项 | 桌面 | 内存占用 | 说明 |
|---|---|---|---|
| **A ★推荐** | KDE Plasma 5.27 | ~800MB | 类 Windows 体验，含 Dolphin 文件管理器、Konsole 终端、Ark 压缩工具 |
| B | Xfce 4.18 | ~400MB | 轻量级，适合内存受限空间，但功能较少 |
| C | GNOME 46 | ~1.2GB | 现代风格，但触控导向，不如 KDE 适合服务器远程桌面 |

> **推荐理由**：你之前使用 TunMax 的 KDE 体验已经习惯，继续 KDE 过渡成本最低。

---

### 选择 3：远程桌面方案

| 选项 | VNC 服务 | noVNC 版本 | 说明 |
|---|---|---|---|
| **A ★推荐** | TigerVNC 1.16.2 | noVNC 1.7.0 | TigerVNC 性能最好，noVNC 1.7 支持移动端触控 |
| B | x11vnc | noVNC 1.7.0 | x11vnc 可共享已有 X session，但性能略差 |
| C | TurboVNC | noVNC 1.7.0 | TurboVNC 针对图像压缩优化，但配置更复杂 |

> **推荐理由**：TigerVNC 是性能与稳定性的最佳平衡。

---

### 选择 4：AI Agent 核心（必选，确认版本）

| 组件 | 推荐版本 | 说明 | 许可证 |
|---|---|---|---|
| Hermes Agent | **v0.20.0 (v2026.8.3)** | NousResearch 最新稳定版，5 小时前刚更新 | MIT |
| Hermes Studio | **v0.6.39** | EKKOLearnAI 最新版，4 小时前刚更新 | BSL-1.1 |
| Open WebUI | **最新 main 分支** | Open WebUI 持续滚动更新 | MIT |

> **注意**：Hermes Studio 是 BSL-1.1 许可证，个人使用没问题，但**不能商业再分发**。  
> 如果你介意，可以改用 `nesquena/hermes-webui`（MIT 许可，但功能较少）。

**子选择**：Hermes Studio WebUI 方案
- **A ★推荐**：EKKOLearnAI/hermes-studio v0.6.39（功能全，活跃维护）
- B：nesquena/hermes-webui（MIT 许可，轻量）

---

### 选择 5：AI 扩展应用（可多选）

| 选项 | 项目 | Stars | 说明 | 是否默认启用 |
|---|---|---|---|---|
| **✅ 必选** | Open WebUI | ~80k+ | 最流行的自托管 AI 界面，支持 OpenAI API / Ollama / Hermes | ✅ |
| **A ★推荐** | llama.cpp | ~70k+ | C/C++ LLM 推理引擎，CPU 可跑小模型，以后有 GPU 直接用 | ✅ 默认装 |
| **B ★推荐** | Flowise | ~35k+ | 可视化 AI Agent 工作流构建器，拖拽式，部署简单 | ✅ 默认装 |
| C | AnythingLLM | ~40k+ | 本地优先 RAG + 文档对话 | ⬜ 可选，默认不装 |
| D | ComfyUI | ~125k+ | 图像/视频生成工作流 | ⬜ 仅 GPU 空间推荐 |
| E | Ollama | ~130k+ | 本地模型管理 | ⬜ 与 llama.cpp 功能重叠，不推荐同装 |
| F | vLLM | ~88k+ | 高吞吐推理服务 | ⬜ 仅多 GPU 服务器推荐 |
| G | LocalAI | ~48k+ | 全能本地 AI 引擎 | ⬜ 与 llama.cpp/ollama 重叠 |

> **推荐组合**：Open WebUI + llama.cpp + Flowise（三个互补，覆盖聊天/推理/工作流）  
> AnythingLLM 做成可选模块（`ENABLE_ANYTHINGLLM=1`），需要时再启用。

---

### 选择 6：备份方案

| 选项 | 方案 | 说明 |
|---|---|---|
| **A ★推荐** | rclone + OneDrive API + crypt 加密 | OneDrive 官方已弃用 WebDAV，rclone 走 Graph API 最稳；crypt 层加密后上传，API Key 不裸传 |
| B | rclone + 其他云盘（如阿里云盘/WebDAV 自建） | 如果你已有其他云存储 |
| C | 仅 ModelScope `/mnt/workspace` 持久化，无异地备份 | 最简单但无异地灾备 |

> **推荐理由**：你提到想挂载 OneDrive，rclone + Graph API 是官方推荐路径。  
> **注意**：OneDrive WebDAV 已被微软官方弃用，rclone 使用的是 OneDrive Graph API，完全不同。

**备份策略**：

| 数据类型 | /mnt/workspace | OneDrive 加密备份 |
|---|---|---|
| Hermes 配置 (config.yaml, .env) | ✅ | ✅ |
| Hermes Memory / Sessions / Skills | ✅ | ✅ |
| Hermes Studio 数据库 | ✅ | ✅ |
| Open WebUI 数据库 | ✅ | ✅ |
| Flowise 数据 | ✅ | ✅ |
| 桌面重要文件 | ✅ | ✅ |
| API Keys | ✅ | ✅（crypt 加密后） |
| 模型文件 (GGUF) | ✅ | ❌（太大，可重新下载） |
| 代码仓库 | ✅ | ✅ |

---

### 选择 7：构建与部署策略

| 选项 | 方案 | 说明 |
|---|---|---|
| **A ★推荐** | GitHub Actions → GHCR → ModelScope 拉取 | 在 GitHub 构建镜像推送到 GHCR，ModelScope 空间配置 `FROM ghcr.io/你的用户名/zephyr-desktop:latest`；构建可缓存层，速度快 |
| B | ModelScope 原地构建 | 直接在 ModelScope 空间放 Dockerfile，平台自行构建；简单但每次重建慢，无法缓存 |
| C | 本地构建 → 推送到 Docker Hub → ModelScope 拉取 | 需要本地 Docker 环境，你当前没有 |

> **推荐理由**：方案 A 利用 GitHub Actions 免费额度构建，GHCR 免费私有镜像，ModelScope 只需一行 `FROM` 即可拉取。你已有 GitHub 账号和 keepalive workflow，基础设施现成。

---

### 选择 8：Web 入口架构

ModelScope Custom Docker **只允许对外暴露 7860 端口**，因此所有服务通过 Nginx 反代：

```
https://你的ModelScope空间/
         │
         ▼
    Nginx :7860
         │
    ┌────┼────────┬──────────┬───────────┐
    │    │        │          │           │
    ▼    ▼        ▼          ▼           ▼
/desktop/  /hermes/  /chat/  /flow/    /api/
  │         │         │        │         │
  noVNC   Hermes    Open    Flowise   Hermes
  桌面    Studio    WebUI              API(内部)
```

| 路径 | 服务 | 内部端口 |
|---|---|---|
| `/desktop/` | noVNC KDE 桌面 | 6080 |
| `/hermes/` | Hermes Studio | 8648 |
| `/chat/` | Open WebUI | 3000 |
| `/flow/` | Flowise | 3001 |
| `/api/` | Hermes Agent API（仅内部） | 8642 |

> **确认**：这个入口架构是否符合你的使用习惯？

---

### 选择 9：进程管理

| 选项 | 方案 | 说明 |
|---|---|---|
| **A ★推荐** | Supervisord | Python 生态，配置简单，支持自动重启、日志轮转 |
| B | s6-overlay | 更轻量，Alpine Linux 常用，但 Ubuntu 下配置较繁琐 |
| C | systemd | 在容器中不推荐，需要 `--privileged` |

> **推荐理由**：Supervisord 与 Python/Hermes 生态一致，配置直观。

---

### 选择 10：安全策略

| 层级 | 措施 |
|---|---|
| 平台层 | ModelScope 空间设为 Private |
| 入口层 | Nginx 门户可选加 Basic Auth |
| 应用层 | 各应用自身认证（Open WebUI / Hermes Studio / Flowise 各自有登录） |
| 用户层 | Hermes 以 `hermes` 非 root 用户运行 |
| 备份层 | rclone crypt 加密后上传 OneDrive |
| 敏感信息 | API Key 通过环境变量注入，不硬编码到镜像 |

---

## 四、最终推荐架构总览

```
┌──────────────────────────────────────────────────┐
│ ModelScope Studio (Private)                      │
│                                                  │
│  ┌─ Nginx :7860 (唯一公网入口) ──────────────┐  │
│  │                                            │  │
│  │  /desktop/ → noVNC → TigerVNC → KDE Plasma │  │
│  │              ├── Chrome + fcitx5           │  │
│  │              ├── Konsole + Dolphin + Ark  │  │
│  │                                            │  │
│  │  /hermes/  → Hermes Studio v0.6.39        │  │
│  │  /api/     → Hermes Agent v0.20.0 (内部)  │  │
│  │  /chat/    → Open WebUI (latest)          │  │
│  │  /flow/    → Flowise (latest)             │  │
│  │                                            │  │
│  │  Supervisord 管理所有进程                  │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─ Runtime ──────────────────────────────────┐  │
│  │ Python 3.11 venv + uv                     │  │
│  │ Node.js 22 + npm                          │  │
│  │ git / curl / ffmpeg / jq / ripgrep        │  │
│  │ rsync / zstd / rclone                     │  │
│  └────────────────────────────────────────────┘  │
│                                                  │
│  ┌─ 持久化存储 ───────────────────────────────┐  │
│  │ /mnt/workspace/zephyr/                    │  │
│  │ ├── hermes/         (Agent 数据)          │  │
│  │ ├── hermes-studio/  (Studio 数据库)       │  │
│  │ ├── open-webui/     (WebUI 数据库)        │  │
│  │ ├── flowise/        (Flowise 数据)        │  │
│  │ ├── desktop/        (桌面文件)           │  │
│  │ ├── models/         (GGUF 模型)           │  │
│  │ └── backup/         (本地快照)            │  │
│  └────────────────────────────────────────────┘  │
│                       │                          │
│              ┌────────┴────────┐                 │
│              │  rclone crypt    │                 │
│              │  → OneDrive API  │                 │
│              └─────────────────┘                 │
└──────────────────────────────────────────────────┘
         ↑
    ModelScope HTTPS :7860
         │
   Windows / Mac / 手机 浏览器
```

---

## 五、镜像构建关键策略

| 策略 | 说明 |
|---|---|
| 多阶段构建 | Builder 阶段编译 Hermes / Flowise，Runtime 阶段只拷贝产物，减小镜像体积 |
| 非 root 用户 | 创建 `hermes` 用户，Hermes / Studio / Open WebUI 均以该用户运行 |
| 层缓存优化 | 先拷贝 requirements/package.json，再拷贝源码，利用 Docker 缓存 |
| 可选模块 | `ENABLE_FLOWISE=1` / `ENABLE_LLAMA_CPP=1` / `ENABLE_ANYTHINGLLM=0` 通过 ARG 控制 |
| 预估镜像体积 | ~3.5-4.5 GB（含 KDE + 所有 AI 应用） |
| 启动脚本 | `entrypoint.sh`：首次启动检测 `/mnt/workspace/zephyr` 是否为空 → 空则从镜像内种子配置初始化 → 非空则直接使用已有数据 |

---

## 六、自动恢复机制（解决"每次打开被重置"问题）

```
容器启动
   │
   ▼
entrypoint.sh
   │
   ├── 检查 /mnt/workspace/zephyr/hermes/config.yaml 是否存在
   │
   ├── [存在] → 符号链接 /mnt/workspace/zephyr/* → 各应用数据目录 → 启动服务
   │
   └── [不存在] → 首次初始化：
         ├── 从镜像内置种子配置拷贝到 /mnt/workspace/zephyr/
         ├── 生成默认 config.yaml / .env
         ├── 创建 hermes 用户目录结构
         └── 启动服务
```

**这样无论 ModelScope 重建多少次容器，只要 `/mnt/workspace` 还在，所有配置和数据都会自动恢复。**

---

## 七、仓库结构（确认后生成）

```
zephyr-ai-desktop/
│
├── .github/workflows/
│   ├── build.yml          # GitHub Actions 构建镜像 → GHCR
│   └── keepalive.yml      # ModelScope 保活（复用你现有的）
│
├── docker/
│   ├── Dockerfile          # 多阶段构建主文件
│   ├── entrypoint.sh       # 启动入口脚本
│   └── supervisord.conf   # 进程管理配置
│
├── config/
│   ├── nginx.conf          # Nginx 反代配置
│   ├── hermes-seed/        # Hermes 初始种子配置
│   │   ├── config.yaml
│   │   └── SOUL.md
│   └── rclone.conf.template  # OneDrive 备份配置模板
│
├── scripts/
│   ├── backup.sh           # rclone 加密备份到 OneDrive
│   ├── restore.sh          # 从 OneDrive 恢复
│   └── healthcheck.sh      # 健康检查
│
├── modelscope/
│   └── Dockerfile          # ModelScope 空间用（FROM ghcr.io/...）
│
├── README.md
└── .env.example
```

---

## 八、你需要确认的清单

请回复以下确认项（可以简写如 "1A 2A 3A 4A 5:ABC装 6A 7A 8OK 9A 10OK"）：

| 编号 | 选择项 | 我的推荐 | 你的选择 |
|---|---|---|---|
| 1 | 操作系统 | A: Ubuntu 24.04 LTS | ? |
| 2 | 桌面环境 | A: KDE Plasma 5.27 | ? |
| 3 | 远程桌面 | A: TigerVNC + noVNC | ? |
| 4 | Hermes Studio 许可 | A: EKKOLearnAI (BSL-1.1) | ? |
| 5 | AI 扩展应用 | llama.cpp + Flowise 默认装 | ? |
| 6 | 备份方案 | A: rclone + OneDrive crypt | ? |
| 7 | 构建策略 | A: GitHub Actions → GHCR | ? |
| 8 | Web 入口 | Nginx 7860 多路径反代 | ? |
| 9 | 进程管理 | A: Supervisord | ? |
| 10 | 安全策略 | Private + 各应用认证 + crypt | ? |

**额外问题**：
1. 你的 ModelScope 空间是否有 GPU？（影响是否预装 ComfyUI / vLLM）
2. OneDrive 账号是什么类型？（个人版 5GB 免费 / M365 1TB / 教育/企业版）
3. 你希望备份频率是？（每天 / 每次退出前手动 / 每周）

---

> **确认后我会立即开始生成完整代码和仓库结构。**  
> 如有任何选项想调整或有新需求补充，直接告诉我即可。
