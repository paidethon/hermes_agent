# Zephyr AI Desktop — 魔搭空间架构方案

> **文档类型**：架构审计与方案选择书
> **作者**：云鹤-架构审计师
> **日期**：2026-08-08
> **状态**：待用户确认（确认后再生成代码与仓库）

---

## 一、现状问题总结

通过阅读完整对话和构建日志，我确认了当前 `zephyr17/hermes_agent` 空间存在的三个核心问题：

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | **Hermes 数据每次重置** | `/root/hermes-data` 和 `/root/.hermes-web-ui` 不在 ModelScope 持久化路径 `/mnt/workspace` 内 | config、sessions、memories、skills、token 全部丢失 |
| 2 | **keepalive.yml 每天强制重建容器** | 脚本无条件执行 `POST /deploy`，而 deploy API 实际是 Deploy/Restart 语义 | 即使数据做了持久化，writable layer 也被清除 |
| 3 | **Hermes Gateway 以 root 运行后崩溃** | 镜像 entrypoint 被覆盖后未正确降权，日志显示 `Refusing to run the Hermes gateway as root`，每 5 秒重启循环 | Hermes 功能不可用 |

当前镜像构建链路（从日志确认）：
```
Dockerfile:
  FROM ghcr.io/comedy1024/hermes-agent-desktop:latest
  EXPOSE 7860 3199 8642
  VOLUME ["/opt/data"]
```
这是纯转发镜像，没有做任何持久化处理。`/opt/data` 这个 VOLUME 也不是 ModelScope 的持久化路径。

---

## 二、总体架构设计

确认后的目标架构如下：

```
                    互联网 (手机/电脑)
                         │ HTTPS
                         ▼
                   ModelScope 平台
                    (Private 空间)
                         │
                    :7860 转发
                         │
                ┌────────┴────────┐
                │   Nginx Portal  │  ← 统一入口 + 路由 (0.0.0.0:7860)
                └────────┬────────┘
                         │
          ┌──────────────┼──────────────┐
          │              │              │
     /desktop/       /hermes/       /chat/
          │              │              │
    TigerVNC+noVNC   Hermes        Open WebUI
    KDE 桌面         Studio        通用聊天
    :6080           :8648         :8082

     ┄┄┄┄┄┄┄┄ 内部 loopback（不经 Nginx） ┄┄┄┄┄┄┄┄
     Hermes Studio (:8648) ──┐
                              ├──→ Hermes Gateway (:8642)
     Open WebUI (:8082) ──────┘        │
                                        │
                   ┌─────┴─────┐
                   │           │
              远程 API      (本地 GGUF)
              (OpenRouter   llama.cpp
               ModelScope   :8081
               API 等)
```

> **★架构决策：内部服务走 loopback 直连，不进 Nginx 路由**
>
> Hermes Gateway (:8642) **不暴露任何 Nginx location**。Hermes Studio 和 Open WebUI 直接用 `http://127.0.0.1:8642` 调用 Gateway，走容器内部回环，零网络开销。外部公网只能触达三条路由：`/desktop/` `/hermes/` `/chat/`。
>
> 理由：`/api/` 如果放进 Nginx 路由表，即使加 `deny all` 也增加了攻击面（路径存在性暴露、配置遗漏风险）。根本不暴露比限制访问更安全——这是架构层面的最小暴露原则。

> **★端口冲突修正（极客-AI模型通发现）**：魔搭Docker Space的8080端口被平台自带进程占用，不可使用。Open WebUI从8080改为8082，llama.cpp用8081。所有内部服务绑127.0.0.1，仅Nginx绑0.0.0.0:7860对外。

**持久化与备份层**：
```
              运行数据
                 │
                 ▼
     /mnt/workspace/zephyr/
         (ModelScope 持久化盘)
                 │
          ┌──────┴──────┐
          │             │
     日常增量        定时快照
          │             │
          │         tar.zst
          │             │
          │        rclone crypt
          │             │
          │          OneDrive
          │         (异地加密备份)
```

---

## 三、5 个决策点（请逐项选择）

### 决策点 1：基础镜像策略

| 选项 | 方案 | 优点 | 缺点 | 风险 |
|:---:|------|------|------|------|
| A | `FROM ghcr.io/tunmax/openclaw_computer:latest` 继承 TunMax 底座 | 快速、KDE/Chrome/VNC 已就绪 | 黑盒依赖，无法审计底层构建，TunMax 版本更新可能引入 breaking change | 🟡 中 |
| **B ★** | `FROM ubuntu:24.04` 完全自建 | 100% 可复现、可审计、版本锁定 | Dockerfile 长、首次构建慢 | 🟢 低 |
| C | `FROM debian:12` 完全自建 | 极稳定、TunMax 同系 | Python 3.11 需手动处理 | 🟡 中 |

**我的推荐：B（Ubuntu 24.04 LTS 完全自建）**

> 理由：你的核心诉求是"知道每个东西从哪来、版本是什么"。从 `ubuntu:24.04` 开始构建，可以完全审计 Dockerfile，锁定所有版本，未来升级可控。TunMax 底座虽然方便，但其 Dockerfile 没有完整公开构建配方，属于不可审计的黑盒依赖，不符合架构审计的基本原则。

---

### 决策点 2：服务组合方案

| 选项 | 包含组件 | 镜像预估大小 | 适用场景 |
|:---:|---------|:-----------:|---------|
| A | 桌面 + Hermes Agent + Hermes Studio | ~1.2GB | 最精简，解决持久化问题即可 |
| **B ★** | 桌面 + Hermes + Hermes Studio + Open WebUI + Nginx | ~1.8GB | 标准方案，ChatGPT 推荐 |
| C | B + llama.cpp + Flowise + (可选 AnythingLLM) | ~2.5GB | 功能最全 |

**我的推荐：B（标准方案）**

> 理由：
> - **llama.cpp / Flowise 等可以以后通过 `ENABLE_*` 开关加入**，不必第一版就塞进去。
> - Open WebUI 是必要的——它是通用聊天入口，和 Hermes Studio（管理 Hermes）分工清晰。
> - 镜像越大构建越慢、ModelScope 构建可能超时。第一版应该先跑通核心链路。
>
> 如果你需要 llama.cpp 和 Flowise，我会在 Dockerfile 中做成 `ARG ENABLE_LLAMA_CPP=0`、`ARG ENABLE_FLOWISE=0` 的开关，默认关闭，未来一行参数即可开启。

---

### 决策点 3：持久化与备份策略

| 选项 | 持久化 | 异地备份 | 加密 |
|:---:|--------|---------|:----:|
| A | `/mnt/workspace/zephyr/` | 无 | — |
| B | `/mnt/workspace/zephyr/` | rclone → OneDrive | 无 |
| **C ★** | `/mnt/workspace/zephyr/` | rclone crypt → OneDrive | ✅ XSalsa20+Poly1305 |

**我的推荐：C（rclone crypt → OneDrive）**

> 理由：
> - A 依赖 ModelScope 单一存储，平台出问题则数据全失。
> - B 不加密，Hermes 备份里的 API Key、对话记录会明文存到 OneDrive。
> - C 是最佳方案：客户端加密后上传，OneDrive 只存密文。`rclone copy`（非 sync）不会删除远端文件，更安全。
> - **注意**：不要用 WebDAV 挂载 OneDrive。Microsoft 不官方支持 OneDrive 的 WebDAV 访问。应该用 rclone 的 OneDrive OAuth 后端。

持久化目录结构：
```
/mnt/workspace/zephyr/
├── hermes/           # Hermes Agent 数据 (config/sessions/memories/skills)
├── hermes-studio/    # Hermes Studio 数据库与配置
├── open-webui/       # Open WebUI 数据库
├── models/           # GGUF 模型文件 (不备份到OneDrive)
├── desktop/          # 桌面重要文件
├── projects/         # 项目代码
├── rclone/           # rclone 配置
└── backups/          # 本地快照
    ├── hourly/
    ├── daily/
    └── manual/
```

---

### 决策点 4：安全与访问控制

| 选项 | 第一道门 | 第二道门 | 第三道门 |
|:---:|---------|---------|---------|
| A | ModelScope Private | 应用自身认证 | — |
| **B ★** | ModelScope Private | Nginx Portal 认证 | 应用自身认证 |

**我的推荐：B（三道门）**

> 理由：你的空间包含完整 Linux 桌面 + Terminal + Chrome + API Keys。如果只有应用层认证，一旦某个应用有漏洞，整个空间暴露。三道门虽然多一步操作，但安全边界清晰。
>
> **安全要点**：
> - 空间可见性设为 **Private**（非 Public）
> - 所有密钥用 **ModelScope Secrets**，不写进 Dockerfile
> - VNC 密码、Hermes Auth Token、OneDrive 凭据全部走 Secret 注入
> - **禁止运行任何内网穿透服务**（TunMax 官方明确警告可能导致账号被封）

---

### 决策点 5：保活策略

| 选项 | 方案 | 说明 |
|:---:|------|------|
| A | 保留原 keepalive.yml | 每天无条件 deploy = 每天重建容器 = 数据丢失 |
| **B ★** | 修复 keepalive.yml | 先 GET 状态，仅在 Status≠Running 时才 POST deploy |
| C | 移除 GitHub 保活 | 改用 ModelScope 内置定时器或其他机制 |

**我的推荐：B（修复 keepalive.yml）**

> 修复逻辑：
> ```yaml
> # 伪代码
> status = GET /studios/{name}
> if status != "Running":
>     POST /studios/{name}/deploy
> else:
>     # 什么都不做，空间正在运行，不需要重启
> ```
>
> 这样空间正常运行时不会被强制重启，只有在真正停止后才触发 deploy。

---

## 四、版本锁定清单

基于 ChatGPT 对话中确认的版本，我做了一些调整（标注★为我的审计修正）：

| 组件 | 版本 | 说明 |
|------|------|------|
| OS | Ubuntu 24.04 LTS | 安全维护到 2029 年 5 月 |
| 桌面 | KDE Plasma 5.27.x | Ubuntu 24.04 仓库版本 |
| ★ TigerVNC | 1.14.x（非1.16.2） | Ubuntu 24.04 仓库版本，1.16.2 需源码编译。★修正：Ubuntu 24.04 仓库的 TigerVNC 版本更稳定，不需要追新 |
| noVNC | 1.7.0 | 当前正式 release |
| Chrome | Stable | Google 官方仓库 |
| 中文输入 | fcitx5 | Ubuntu 仓库 |
| Python | 3.11 | 通过 uv 管理 venv |
| Node.js | 22 LTS | Hermes Studio 需要 |
| Hermes Agent | v2026.7.7.2 (0.18.2) | NousResearch 当前 Latest Release |
| Hermes Studio | v0.6.39 | EKKOLearnAI 当前 Latest |
| Open WebUI | v0.11.0 | 2026-07-27 发布 |
| Nginx | Ubuntu 仓库最新 | 反向代理 |
| Supervisord | Ubuntu 仓库最新 | 进程管理 |
| rclone | 最新稳定版 | OneDrive 备份 |
| uv | 最新 | Python 包管理 |

---

## 五、Dockerfile 架构设计

```
FROM ubuntu:24.04

# ===== 层 1: 系统基础 =====
# apt 更新 + 基础工具 (curl/git/rsync/jq/ripgrep/zstd/ffmpeg/build-essential)
# + KDE Plasma + TigerVNC + noVNC + Chrome + fcitx5 + Konsole + Dolphin

# ===== 层 2: 运行时 =====
# Python 3.11 (apt) + Node.js 22 LTS (NodeSource) + uv (astral.sh)

# ===== 层 3: Hermes Agent =====
# git clone NousResearch/hermes-agent → uv pip install -e ".[all]"
# 创建 hermes 用户 (非root, 解决 Gateway root 崩溃)

# ===== 层 4: Hermes Studio =====
# git clone EKKOLearnAI/hermes-studio → npm install → npm run build

# ===== 层 5: Open WebUI =====
# pip install open-webui

# ===== 层 6: Nginx + Supervisord =====
# Nginx 配置: 仅3条对外路由 — /desktop/ → noVNC, /hermes/ → Studio, /chat/ → Open WebUI
# Hermes Gateway (:8642) 不进 Nginx，内部服务通过 127.0.0.1:8642 loopback 直连
# Supervisord 配置: 管理 VNC + Nginx + Hermes + Studio + Open WebUI

# ===== 层 7: 持久化入口脚本 =====
# modelscope-entrypoint.sh:
#   1. 检查 /mnt/workspace/zephyr/ 是否有备份数据
#   2. 如有，恢复到对应路径
#   3. 建立软链接: /root/hermes-data → /mnt/workspace/zephyr/hermes
#   4. 设置 HERMES_HOME, HERMES_WEB_UI_HOME 环境变量
#   5. exec supervisord

# ===== 层 8: 可选模块 (默认关闭) =====
ARG ENABLE_LLAMA_CPP=0
ARG ENABLE_FLOWISE=0
ARG ENABLE_ANYTHINGLLM=0
ARG ENABLE_OLLAMA=0
```

---

## 六、仓库文件结构预览

```
zephyr-ai-desktop/
├── Dockerfile                    # 主 Dockerfile
├── docker-compose.yml            # 本地开发/测试用
├── README.md                     # 使用文档
├── .dockerignore
│
├── modelscope/
│   ├── entrypoint.sh             # ModelScope 持久化入口脚本 ★核心
│   ├── hermes-wrapper.sh         # Hermes 启动包装
│   ├── supervisord.conf          # 进程管理配置
│   └── nginx/
│       ├── nginx.conf            # Nginx 主配置
│       ├── portal.conf           # :7860 门户配置
│       └── htpasswd.template     # Portal 认证模板
│
├── scripts/
│   ├── backup.sh                 # rclone crypt → OneDrive 备份
│   ├── restore.sh                # 从 OneDrive 恢复
│   ├── first-run-init.sh         # 首次运行初始化
│   └── health-check.sh          # 健康检查
│
├── .github/workflows/
│   ├── keepalive.yml             # ★修复版保活 (仅空间停止时才deploy)
│   └── build.yml                 # 镜像构建 CI (可选)
│
└── config/
    ├── rclone.template.conf      # rclone 配置模板
    └── env.template              # 环境变量模板 (含 Secret 说明)
```

---

## 七、关键架构风险与对策

| 风险 | 级别 | 对策 |
|------|:----:|------|
| 单容器多服务违反微服务原则 | 🟡 | ModelScope 限制只能单容器，用 Supervisord 管理进程，做好健康检查和自动重启 |
| Nginx 子路径部署各 WebUI 兼容性不同 | 🟠 | 逐个配置 base_path / rewrite / WebSocket headers，不能简单 proxy_pass |
| Hermes 以 root 运行导致 Gateway 崩溃 | 🔴 | ★创建 hermes 用户，用 gosu 降权运行，从日志已确认这是必须修复的 |
| ModelScope 构建超时 | 🟡 | 优化 Dockerfile 层缓存，大依赖（Chrome/KDE）单独一层 |
| rclone OneDrive Token 过期 | 🟡 | 使用 rclone 配置自动刷新，定期检查 |
| 镜像体积过大 | 🟡 | 多阶段构建，清理 apt 缓存，--no-install-recommends |

---

## 八、需要你提供的信息（确认方案后）

1. **OneDrive 类型**：Personal 还是 Business？（影响 rclone 配置）
2. **你希望的空间名称**：继续用 `zephyr17/hermes_agent` 还是新名称？
3. **是否需要 Portal 登录页**：还是直接转发到桌面？
4. **你的 ModelScope 空间是否有 GPU**：决定是否预编译 llama.cpp GPU 版本
5. **OpenRouter / OpenAI API Key**：是否已有，还是需要预留 Secret 位

---

## 九、确认方式

请按以下格式回复：

```
决策点1: [A/B/C]
决策点2: [A/B/C]
决策点3: [A/B/C]
决策点4: [A/B/C]
决策点5: [A/B/C]

补充信息:
- OneDrive类型: [Personal/Business]
- 空间名称: [xxx]
- 是否需要Portal: [是/否]
- 是否有GPU: [是/否]
- 其他要求: [...]
```

确认后我将立即生成完整代码和仓库文件。
