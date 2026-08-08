# Zephyr AI Desktop — ModelScope 空间构建方案对比

> 编制：林深-安全合规员
> 日期：2026-08-08
> 状态：**待用户确认方案后再生成代码和仓库**

---

## 〇、你的需求摘要（从对话存档提炼）

| 维度 | 已确定的选择 |
|---|---|
| 基础系统 | Ubuntu 24.04 LTS（不用 Debian/OpenClaw 底座） |
| 桌面 | KDE Plasma + TigerVNC + noVNC + Chrome + fcitx5 |
| AI 核心 | Hermes Agent + Hermes Studio + Open WebUI |
| AI 可选 | llama.cpp、Flowise（AnythingLLM 备选） |
| 明确不要 | OpenClaw、LobeHub、Dify、Ollama、vLLM、ComfyUI |
| 持久化 | `/mnt/workspace/zephyr/` 统一数据目录 |
| 异地备份 | rclone → crypt → OneDrive（不用 WebDAV） |
| Web 入口 | Nginx :7860 反向代理（ModelScope 唯一公网端口） |
| 可见性 | ModelScope Private + 多层认证 |

当前 `zephyr17/hermes_agent` 空间的三个核心问题：

1. **Hermes 拒绝 root 启动** — comedy1024 镜像全 root 架构，新版 Hermes Gateway 直接退出循环
2. **持久化失效** — `VOLUME ["/opt/data"]` 不等于 ModelScope 持久化；Hermes 实际写入 `/root/hermes-data`，未映射到 `/mnt/workspace`
3. **供应链不可审计** — TunMax 和 comedy1024 的 GitHub 仓库只有 5 行 Dockerfile，真实构建配方闭源

---

## 一、三套方案对比总表

| 对比项 | 方案 A：安全优先版 | 方案 B：均衡完整版（推荐） | 方案 C：快速继承版 |
|---|---|---|---|
| 基础镜像 | `ubuntu:24.04` 官方 | `ubuntu:24.04` 官方 | `ghcr.io/tunmax/openclaw_computer:latest` |
| 供应链可审计 | ✅ 100% 可复现 | ✅ 100% 可复现 | ❌ 底层闭源，无法审计 |
| 桌面环境 | Xfce（轻量，攻击面小） | KDE Plasma（Windows 风格） | KDE Plasma（已内置） |
| 构建复杂度 | 高（从零搭桌面） | 高（从零搭桌面） | 低（继承现成） |
| 镜像体积预估 | ~1.2 GB | ~1.8 GB | ~2.5 GB（继承冗余） |
| 构建时间预估 | 25-40 min | 35-50 min | 10-15 min |
| 服务运行权限 | 全部非 root | Hermes 非 root / 桌面受控 | 沿用 TunMax 全 root |
| 核心组件 | Hermes + Hermes Studio + Open WebUI | + llama.cpp + Flowise | + Hermes + Open WebUI |
| 安全评级 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐ |
| 适合场景 | 极度重视安全、资源紧张 | 日常使用、功能与安全兼顾 | 快速验证、临时过渡 |

---

## 二、方案 A：安全优先版

### 设计理念
> **最小攻击面 + 最大可审计性。** 只装必需组件，所有服务非 root 运行，桌面选 Xfce 而非 KDE 以减少依赖包数量。

### 架构

```
┌──────────────────────────────────────┐
│  Zephyr AI Desktop (Security-First)  │
│  Ubuntu 24.04 LTS                   │
│                                      │
│  ┌── Desktop (Xfce) ──────────────┐ │
│  │ TigerVNC 1.16.2 + noVNC 1.7.0  │ │
│  │ Chrome + fcitx5                │ │
│  └────────────────────────────────┘ │
│                                      │
│  ┌── AI Core ─────────────────────┐  │
│  │ Hermes Agent (hermes 用户)    │  │
│  │ Hermes Studio (hermes 用户)   │  │
│  │ Open WebUI (hermes 用户)      │  │
│  └───────────────────────────────┘  │
│                                      │
│  ┌── Entry ───────────────────────┐ │
│  │ Nginx :7860 + Basic Auth      │ │
│  └────────────────────────────────┘ │
│                                      │
│  ┌── Storage ────────────────────┐ │
│  │ /mnt/workspace/zephyr/         │ │
│  │ rclone crypt → OneDrive       │ │
│  └───────────────────────────────┘ │
└──────────────────────────────────────┘
```

### 安全特性
- ✅ 从 `ubuntu:24.04` 官方镜像开始，每一层 Dockerfile 可审计
- ✅ 所有 AI 服务以 `hermes` 非 root 用户运行
- ✅ Xfce 桌面依赖包比 KDE 少 ~40%，减少潜在 CVE 暴露面
- ✅ Nginx Basic Auth 作为第一道门，各应用自身认证为第二道
- ✅ VNC 仅监听 localhost，通过 noVNC websockify 暴露，不直接开放
- ✅ ModelScope Private 可见性，仅自己登录后可访问
- ✅ rclone crypt 客户端加密后上传 OneDrive

### 放弃的东西
- ❌ KDE 的 Windows 风格桌面体验（改用 Xfce）
- ❌ llama.cpp / Flowise（需要时可后续追加）
- ❌ 视觉效果不如 KDE

### 安全风险点
| 风险 | 等级 | 缓解措施 |
|---|---|---|
| VNC 密码弱爆破 | 中 | Nginx Basic Auth 在 VNC 前面；VNC 密码随机 16 位 |
| OneDrive OAuth Token 泄露 | 中 | Token 文件权限 600，仅 hermes 用户可读 |
| Nginx Basic Auth 凭据传输 | 低 | ModelScope 已强制 HTTPS，Basic Auth 走加密通道 |
| Open WebUI 默认无密码 | 中 | 构建时设置 `WEBUI_SECRET_KEY` 和管理员密码 |

### Dockerfile 骨架（仅展示结构，确认后生成完整版）
```dockerfile
FROM ubuntu:24.04

# 创建非 root 用户
RUN useradd -m -s /bin/bash hermes

# 安装基础工具（最小集）
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3.11 python3.11-venv nodejs npm \
    git curl wget ffmpeg jq ripgrep rsync zstd rclone \
    && rm -rf /var/lib/apt/lists/*

# 安装 Xfce + VNC + noVNC（最小桌面）
# ...（确认方案后展开）

# 安装 Hermes Agent（非 root）
USER hermes
RUN ...

# 安装 Open WebUI（非 root）
RUN ...

# 安装 Nginx，配置反向代理
USER root
COPY nginx.conf /etc/nginx/nginx.conf
COPY entrypoint.sh /entrypoint.sh

EXPOSE 7860
ENTRYPOINT ["/entrypoint.sh"]
```

---

## 三、方案 B：均衡完整版（推荐）

### 设计理念
> **功能完整 + 安全可控 + 体验友好。** 从 Ubuntu 24.04 自建，保留 KDE 桌面体验，加入你对话中最终确定的所有组件，安全等级略低于方案 A 但日常使用更舒适。

### 架构

```
┌──────────────────────────────────────────┐
│  Zephyr AI Desktop (Balanced)           │
│  Ubuntu 24.04 LTS                       │
│                                          │
│  ┌── Desktop (KDE Plasma) ─────────────┐ │
│  │ TigerVNC 1.16.2 + noVNC 1.7.0      │ │
│  │ Chrome + fcitx5 + Konsole + Dolphin │ │
│  │ Ark                                 │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌── AI Core ─────────────────────────┐ │
│  │ Hermes Agent    (hermes 用户)      │ │
│  │ Hermes Studio   (hermes 用户)      │ │
│  │ Open WebUI 0.11 (hermes 用户)      │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌── AI Optional ─────────────────────┐ │
│  │ llama.cpp  (hermes 用户, 默认不启动) │ │
│  │ Flowise    (hermes 用户)            │ │
│  └────────────────────────────────────┘ │
│                                          │
│  ┌── Runtime ──────────────────────────┐ │
│  │ Python 3.11 venv + Node.js 22 + uv  │ │
│  │ git ffmpeg jq ripgrep rsync zstd     │ │
│  │ rclone                               │ │
│  └──────────────────────────────────────┘ │
│                                          │
│  ┌── Entry ───────────────────────────┐  │
│  │ Nginx :7860 (反向代理 + 可选 Basic) │  │
│  └────────────────────────────────────┘  │
│                                          │
│  ┌── Storage ─────────────────────────┐ │
│  │ /mnt/workspace/zephyr/              │ │
│  │ ├── hermes/                        │ │
│  │ ├── hermes-studio/                 │ │
│  │ ├── open-webui/                    │ │
│  │ ├── models/gguf/                   │ │
│  │ ├── flowise/                       │ │
│  │ ├── projects/                      │ │
│  │ ├── desktop/                       │ │
│  │ └── backups/                      │ │
│  │ rclone crypt → OneDrive            │ │
│  └────────────────────────────────────┘ │
└──────────────────────────────────────────┘
                 ↑
         ModelScope HTTPS :7860
                 ↑
        Windows / Mac / 手机
```

### Nginx 路由设计
```
https://modelscope.cn/studios/zephyr17/hermes_agent/
├── /              → Zephyr Portal（导航页）
├── /desktop/      → noVNC Web 桌面
├── /hermes/       → Hermes Studio
├── /chat/         → Open WebUI
└── /flow/         → Flowise
```

### 安全特性
- ✅ 从 `ubuntu:24.04` 官方镜像自建，供应链可审计
- ✅ Hermes Agent / Studio / Open WebUI 均以 `hermes` 非 root 用户运行
- ✅ Nginx 反向代理统一入口，内部服务端口不直接暴露
- ✅ ModelScope Private 可见性 + 应用层认证 + 可选 Nginx Basic Auth
- ✅ VNC 仅 localhost 可达，通过 noVNC websockify 代理
- ✅ rclone crypt 客户端加密备份至 OneDrive
- ✅ 持久化数据统一到 `/mnt/workspace/zephyr/`，软链接回程序期望路径

### 安全风险点
| 风险 | 等级 | 缓解措施 |
|---|---|---|
| KDE 依赖包多，CVE 暴露面大于 Xfce | 中 | 定期 `apt upgrade`；锁定基础镜像 digest |
| 多个 Web 服务同时运行 | 中 | Nginx 前置统一认证；内部端口仅 127.0.0.1 |
| Flowise 默认无认证 | 中 | 构建时设置 `FLOWISE_USERNAME` / `FLOWISE_PASSWORD` |
| llama.cpp HTTP API 无认证 | 低 | 仅监听 127.0.0.1:8080，不经过 Nginx 暴露 |
| 桌面 VNC 以 root 启动 | 中 | VNC Server 在 root 下运行但仅绑定 localhost，通过 noVNC 代理后加 Basic Auth |
| OneDrive rclone 配置泄露 | 中 | 配置文件权限 600；`rclone.conf` 不进 Git |

### 持久化目录结构
```
/mnt/workspace/zephyr/
├── hermes/
│   ├── config/
│   ├── sessions/
│   ├── memories/
│   ├── skills/
│   └── workspace/
├── hermes-studio/
│   ├── db/
│   └── logs/
├── open-webui/
│   ├── data/
│   └── uploads/
├── models/
│   └── gguf/
├── flowise/
│   └── flows/
├── projects/
├── desktop/
├── downloads/
├── rclone/
│   └── rclone.conf        # 权限 600
└── backups/
    ├── hourly/
    ├── daily/
    └── manual/
```

### 启动流程
```
容器启动
  │
  ├── 1. 检查 /mnt/workspace/zephyr/ 是否存在
  │      └── 不存在 → 创建目录结构
  │
  ├── 2. 软链接：程序路径 → /mnt/workspace/zephyr/xxx
  │      ├── /home/hermes/.hermes → /mnt/workspace/zephyr/hermes
  │      ├── /home/hermes/.hermes-studio → /mnt/workspace/zephyr/hermes-studio
  │      ├── /home/hermes/.open-webui → /mnt/workspace/zephyr/open-webui
  │      └── /home/hermes/Desktop → /mnt/workspace/zephyr/desktop
  │
  ├── 3. 首次启动恢复（如果 backups/ 有快照）
  │
  ├── 4. 启动 supervisord 管理所有进程
  │      ├── TigerVNC Server (root, localhost only)
  │      ├── noVNC websockify (root, :7860 → VNC)
  │      ├── Hermes Gateway (hermes 用户)
  │      ├── Hermes Studio (hermes 用户)
  │      ├── Open WebUI (hermes 用户)
  │      ├── Flowise (hermes 用户, 可选)
  │      └── Nginx (root, :7860 → 各服务)
  │
  ├── 5. 定时备份 cron
  │      ├── 每小时: tar.zst → backups/hourly/
  │      ├── 每天 03:00: rclone crypt → OneDrive
  │      └── 保留最近 7 个 hourly + 30 个 daily
  │
  └── 6. 启动完成
```

### 工程文件结构（确认后生成）
```
zephyr-ai-desktop/
├── Dockerfile                    # 主 Dockerfile（ModelScope 用）
├── Dockerfile.base               # 基础镜像 Dockerfile（可选 GHCR 构建）
├── docker-compose.yml            # 本地测试用
├── README.md                     # 中文部署说明
│
├── scripts/
│   ├── entrypoint.sh             # 容器入口
│   ├── setup-persistence.sh      # 持久化目录初始化
│   ├── backup-now.sh             # 手动备份
│   ├── restore.sh                # 从备份恢复
│   └── setup-rclone.sh           # rclone OneDrive 配置向导
│
├── config/
│   ├── nginx.conf                # Nginx 反向代理配置
│   ├── supervisord.conf          # 进程管理
│   ├── tigerVnc.sh               # VNC 启动
│   ├── hermes.env                # Hermes 环境变量模板
│   └── cron-backup.sh            # 定时备份脚本
│
├── portal/
│   └── index.html                # Zephyr Portal 导航页
│
└── .github/
    └── workflows/
        └── keepalive.yml         # 改进版保活 Action
```

---

## 四、方案 C：快速继承版

### 设计理念
> **最快上线，接受供应链不透明。** 继承 TunMax 镜像，叠加 Hermes 和 Open WebUI，利用 TunMax 已有的 `/mnt/workspace` 持久化机制。

### 架构
```
ghcr.io/tunmax/openclaw_computer:latest
    │
    ├── KDE + VNC + Chrome + fcitx5（已内置）
    ├── OpenClaw（你不想要，但无法移除）
    ├── /mnt/workspace 持久化机制（已有）
    │
    └── 我们叠加：
        ├── Hermes Agent（非 root 用户）
        ├── Hermes Studio（非 root 用户）
        ├── Open WebUI
        ├── Nginx :7860 反向代理
        └── rclone 备份
```

### 安全特性
- ⚠️ 基础镜像闭源，无法审计 KDE/VNC/OpenClaw 的安装过程
- ⚠️ TunMax 镜像全 root 运行，我们叠加的服务可以非 root，但底层仍是 root
- ⚠️ OpenClaw 仍然存在，增加攻击面
- ✅ Hermes / Open WebUI 可做到非 root 运行
- ✅ Nginx 反向代理统一入口
- ✅ 利用 TunMax 已有的 `/mnt/workspace` 同步机制

### 安全风险点
| 风险 | 等级 | 缓解措施 |
|---|---|---|
| **基础镜像不可审计** | **高** | 无法缓解；只能信任 TunMax 作者 |
| OpenClaw 存在已知/未知漏洞 | 高 | 无法移除；仅能通过网络层隔离 |
| 全 root 运行 | 高 | 我们叠加的服务改非 root，底层无法改变 |
| TunMax 镜像被篡改 | 中 | 锁定 digest 而非 `latest` tag |
| 体积大（~2.5 GB） | 低 | 构建时间稍长 |

---

## 五、安全合规维度对比详解

### 5.1 供应链安全

| 维度 | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| 基础镜像来源 | Docker Hub 官方 ubuntu | Docker Hub 官方 ubuntu | GHCR TunMax 个人作者 |
| 构建配方可审计 | ✅ 全部在 Dockerfile | ✅ 全部在 Dockerfile | ❌ 底层闭源 |
| 可锁定版本 | ✅ `ubuntu:24.04@sha256:...` | ✅ 同左 | ⚠️ 可锁 digest 但不知内容 |
| 供应链攻击风险 | 极低 | 极低 | 中（依赖第三方作者） |

### 5.2 运行权限

| 服务 | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| Hermes Gateway | hermes 用户 | hermes 用户 | hermes 用户（可做到） |
| Hermes Studio | hermes 用户 | hermes 用户 | hermes 用户（可做到） |
| Open WebUI | hermes 用户 | hermes 用户 | hermes 用户（可做到） |
| VNC Server | root（仅 localhost） | root（仅 localhost） | root（TunMax 默认） |
| Nginx | root（绑定 7860 需要） | root | root |
| 桌面会话 | root | root | root |

> **说明：** VNC Server 和 Nginx 绑定特权端口需要 root，但 VNC 仅监听 127.0.0.1，不直接对外。这是 ModelScope Docker Studio 的平台约束，无法完全避免。

### 5.3 网络暴露面

| 端口 | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| 7860（公网） | Nginx | Nginx | Nginx |
| VNC 5900 | 127.0.0.1 only | 127.0.0.1 only | 127.0.0.1 only |
| Hermes API 3199 | 127.0.0.1 only | 127.0.0.1 only | 127.0.0.1 only |
| Hermes Studio 8648 | 127.0.0.1 only | 127.0.0.1 only | 127.0.0.1 only |
| Open WebUI 8080 | 127.0.0.1 only | 127.0.0.1 only | 127.0.0.1 only |
| Flowise 3000 | — | 127.0.0.1 only | — |
| llama.cpp 8081 | — | 127.0.0.1 only | — |

### 5.4 数据安全

| 维度 | 方案 A | 方案 B | 方案 C |
|---|---|---|---|
| 本地持久化 | /mnt/workspace/zephyr | /mnt/workspace/zephyr | TunMax 机制 + /mnt/workspace/zephyr |
| 异地备份 | rclone crypt → OneDrive | rclone crypt → OneDrive | rclone crypt → OneDrive |
| 备份加密 | XSalsa20+Poly1305 | XSalsa20+Poly1305 | XSalsa20+Poly1305 |
| API Key 存储 | 环境变量 + 文件 600 | 环境变量 + 文件 600 | 环境变量 + 文件 600 |
| rclone.conf | 不进 Git，权限 600 | 不进 Git，权限 600 | 不进 Git，权限 600 |

### 5.5 认证层级

```
方案 A/B/C 均采用三层认证：

第一层：ModelScope 平台登录（Private 可见性）
    ↓ 只有你能看到这个 Studio URL
第二层：Nginx Basic Auth（可选，推荐开启）
    ↓ 访问任何路径前需要输入用户名密码
第三层：各应用自身认证
    ├── Hermes Studio Token
    ├── Open WebUI 管理员密码
    ├── Flowise 用户名密码
    └── VNC 密码（16 位随机）
```

---

## 六、关于 GitHub 保活 Action 的安全建议

你当前的 `keepalive.yml` 有两个问题：

### 问题 1：Token 明文在 GitHub Secrets（可接受）
```yaml
# 当前写法 — 可以接受，但建议增加状态检查
- name: Query status
  run: |
    curl -s -X GET "https://modelscope.cn/openapi/v1/studios/${{ secrets.STUDIO_NAME }}" \
      -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}"
```
**风险：** Token 在 GitHub Secrets 中是加密存储的，可接受。但 `curl -s` 静默模式如果请求失败不会报错。

### 问题 2：Deploy 操作可能导致容器重建
```yaml
- name: Deploy (start) studio
  run: |
    curl -s -X POST "https://modelscope.cn/openapi/v1/studios/${{ secrets.STUDIO_NAME }}/deploy" \
      -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}" \
      -H "Content-Type: application/json" -d '{}'
```
**风险：** `deploy` 接口如果空间正在运行，可能导致重新部署而非无操作。这会重置容器层（但不影响 `/mnt/workspace`）。

### 改进建议
```yaml
name: Keep ModelScope Studio Alive
on:
  schedule:
    - cron: "0 1 * * *"
  workflow_dispatch:

jobs:
  start-studio:
    runs-on: ubuntu-latest
    steps:
      - name: Query status first
        id: status
        run: |
          RESPONSE=$(curl -s -X GET \
            "https://modelscope.cn/openapi/v1/studios/${{ secrets.STUDIO_NAME }}" \
            -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}")
          echo "response=$RESPONSE" >> $GITHUB_OUTPUT
          # 解析状态，如果已经在运行就不 deploy
          STATUS=$(echo "$RESPONSE" | jq -r '.status // "unknown"')
          echo "status=$STATUS" >> $GITHUB_OUTPUT
          echo "Current status: $STATUS"

      - name: Deploy only if not running
        if: steps.status.outputs.status != 'Running'
        run: |
          curl -s -X POST \
            "https://modelscope.cn/openapi/v1/studios/${{ secrets.STUDIO_NAME }}/deploy" \
            -H "Authorization: Bearer ${{ secrets.MODELSCOPE_TOKEN }}" \
            -H "Content-Type: application/json" -d '{}'
```

---

## 七、我的推荐

### 第一推荐：方案 B（均衡完整版）

**理由：**
1. 你在对话中已明确要 KDE 桌面体验，方案 B 保留了这一点
2. 从 `ubuntu:24.04` 自建解决了你最初的核心痛点——供应链不透明
3. Hermes 非 root 运行解决了 Gateway 拒绝启动的循环报错
4. Nginx 统一入口让你在手机上只记一个 URL
5. 安全等级 ⭐⭐⭐⭐ 已经足够个人使用，不像方案 A 那样牺牲体验

### 如果你非常在意安全：方案 A

**理由：**
- Xfce 攻击面更小
- 无多余组件
- 但你失去了 KDE 体验和 llama.cpp/Flowise

### 不推荐方案 C 用于长期使用

**理由：**
- 底层不可审计是硬伤
- OpenClaw 无法移除
- 适合"先跑起来验证"，不适合长期稳定

---

## 八、下一步

请你选择一个方案（A / B / C），或告诉我你想在某个方案基础上调整哪些部分。

确认后我会：

1. 生成完整的 Dockerfile + 所有脚本 + 配置文件
2. 放到共享目录 `/home/z/my-project/shared/zephyr-ai-desktop/`
3. 用 `send_file` 发给你
4. 如果需要其他 Agent 协助（如极客-AI模型通审核 ModelScope 相关代码、行者-Linux专家审核 Shell 脚本、海豚-容器工程师审核 Dockerfile），我可以 @ 他们

---

## 附录：版本锁定清单（方案 B）

| 组件 | 版本 | 来源 |
|---|---|---|
| Ubuntu | 24.04 LTS | Docker Hub 官方 |
| KDE Plasma | 5.27（Ubuntu 24.04 自带） | apt |
| TigerVNC | 1.16.x | apt |
| noVNC | 1.7.0+ | apt 或 GitHub release |
| Chrome | Stable | Google 官方源 |
| fcitx5 | 系统自带 | apt |
| Hermes Agent | 最新 stable release | NousResearch GitHub |
| Hermes Studio | 最新 release | EKKOLearnAI GitHub |
| Open WebUI | 最新 release | pip 或 GitHub |
| llama.cpp | 最新 tag | GitHub |
| Flowise | 最新 | npm |
| Python | 3.11 | apt（Ubuntu 24.04 自带 3.12，需 deadsnakes 装兼容版） |
| Node.js | 22 LTS | NodeSource |
| Nginx | 系统自带 | apt |
| rclone | 最新 | apt 或 GitHub |
| supervisord | 系统自带 | apt |
