# 模型集成选择项 — 补充选择 8~11

> 极客-AI模型通 出品
>
> 行者、云鹤、海豚的三份方案在基础设施层面已覆盖完整，但均缺少**模型选型与推理方案**相关的决策项。本文件补充 4 个选择项，与现有 7/10 项合并确认后，方可生成完整代码。

---

## 背景速览

魔搭社区当前状态（2026年8月查证）：

| 维度 | 关键事实 |
|------|----------|
| 最新旗舰模型 | Qwen3-235B-A22B、Qwen3-Next-80B-A3B-Instruct、Qwen3-Coder-480B-A35B-Instruct |
| 适合本地跑的模型 | Qwen3-8B（密集）、Qwen3-1.7B（密集）、Qwen3-4B |
| ModelScope API 免费额度 | 每日 2000 次调用，覆盖 6 万+ 模型，含 Qwen3 全系列 |
| ModelScope Docker Space | 端口必须 7860，8080 被平台占用，支持 GPU（xGPU 免费资源） |
| ModelScope SDK | `pip install modelscope`，`snapshot_download()` 下载模型，`MODELSCOPE_CACHE` 指定缓存路径 |
| API Key 格式 | `ms-xxxxxxxxxxxxxxxx`，在魔搭个人中心创建 SDK Token |

---

## 选择 8：模型来源与推理方式

这是最核心的决策——模型从哪来、怎么跑。

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| **A. 纯本地推理** | 用 `modelscope` SDK 下载 GGUF 量化模型，llama.cpp 加载推理 | 完全离线、零 API 费用、隐私好 | 模型小（8B 以下）、速度受限、占存储 |
| **B. 纯 API 调用** | 不跑本地模型，Open WebUI 直连 ModelScope API（OpenAI 兼容格式） | 模型大（可用 235B）、速度快、不占存储 | 依赖网络、每日 2000 次上限、有延迟 |
| **C. 混合模式（推荐）** | 本地放 Qwen3-8B 做日常对话，API 通道接 Qwen3-235B 做复杂任务 | 两全其美、灵活切换 | 配置稍复杂 |

> **我的建议：C（混合模式）**
>
> 理由：
> - 日常 80% 的对话用本地 Qwen3-8B-Q4_K_M（约 5GB），llama.cpp 跑 CPU 也能用
> - 复杂推理/长文/代码任务通过 API 调 Qwen3-235B，免费额度够用
> - Open WebUI 可同时配置多个模型端点，用户在下拉框切换
> - 后续加 GPU 后，本地模型可升级为 14B/32B

---

## 选择 9：本地模型选型

如果选择 8 包含 A 或 C（即有本地推理），需确认预装哪些模型。

| 模型 | 参数量 | 量化后大小（Q4_K_M） | 魔搭路径 | 适合场景 |
|------|--------|----------------------|----------|----------|
| **Qwen3-8B** | 8B | ~5.0 GB | `Qwen/Qwen3-8B` | 通用对话、中文最佳、性价比最高 |
| Qwen3-1.7B | 1.7B | ~1.2 GB | `Qwen/Qwen3-1.7B` | 极速响应、资源紧张时降级 |
| Qwen3-4B | 4B | ~2.5 GB | `Qwen/Qwen3-4B` | 中等场景平衡选择 |
| Qwen3-Coder-30B-A3B-Instruct | 30B MoE | ~18 GB | `Qwen/Qwen3-Coder-30B-A3B-Instruct` | 代码生成（需较大内存/GPU） |

> **我的建议：预装 Qwen3-8B（Q4_K_M 量化）+ Qwen3-1.7B（Q4_K_M 量化）**
>
> 理由：
> - 8B 是当前魔搭社区下载量最高的中文对话模型，中文理解力强
> - 1.7B 作为轻量备选，16GB 内存环境下也能流畅跑
> - 两个模型加起来约 6.2 GB，存储压力小
> - 构建时用 `modelscope snapshot_download` 预下载到 `/mnt/workspace/zephyr/models/`
> - 后续可随时通过 Open WebUI 界面或 entrypoint 脚本添加更多模型

> **注意：** GGUF 量化版需从魔搭下载对应的 GGUF 格式文件。目前魔搭社区部分 Qwen3 模型有官方 GGUF 版本（搜 `Qwen/Qwen3-8B-GGUF`），llama.cpp 原生支持。

---

## 选择 10：GPU 资源

海豚已问到这个问题，我从模型集成角度给出参考。

| 方案 | 说明 | 对推理的影响 |
|------|------|-------------|
| **A. CPU only（2核 16GB）** | 不开 GPU | Qwen3-8B-Q4 约 5-8 token/s，能用但慢 |
| **B. 免费 xGPU** | 魔搭提供免费 GPU 资源（需申请） | Qwen3-8B 可跑 30+ token/s，可上 14B/32B |
| **C. 付费 GPU** | 按需付费 A10/V100 | 可跑 70B+ 级别模型 |

> **我的建议：先 A（CPU only）起步，后续按需申请 B（xGPU）**
>
> 理由：
> - 你的场景是「AI 桌面 + 助手」，CPU 跑 8B 对话够用
> - 复杂任务走 API（选择 8-C 的混合模式），不依赖本地算力
> - 免费 GPU 资源需要排队申请，不影响初次部署
> - 如果后续发现本地推理太慢，再升级到 xGPU，代码只需改环境变量

---

## 选择 11：ModelScope SDK 集成方式

模型下载和管理用哪种方式。

| 方案 | 说明 | 优点 | 缺点 |
|------|------|------|------|
| **A. modelscope CLI（推荐）** | `pip install modelscope`，用 `modelscope download` 命令行下载 | 简单、脚本化、自动断点续传 | 需提前安装 SDK |
| B. modelscope Python SDK | 代码内调用 `snapshot_download()` | 可在应用中动态下载 | 过度工程化，桌面场景不需要 |
| C. git lfs clone | 直接 `git clone` 模型仓库 | 不依赖 SDK | 大文件可能超时、无断点续传 |

> **我的建议：A（modelscope CLI）**
>
> 具体实现：
> ```bash
> # entrypoint.sh 中的模型下载逻辑
> pip install modelscope
>
> # 设置缓存路径到持久化目录
> export MODELSCOPE_CACHE=/mnt/workspace/zephyr/models
>
> # 预下载模型（构建时或首次启动时）
> modelscope download --model Qwen/Qwen3-8B-GGUF
> modelscope download --model Qwen/Qwen3-1.7B-GGUF
> ```
>
> 这样容器重建后模型不丢（在持久化盘上），也不需要每次重新下载。

---

## Open WebUI 与推理后端的对接配置

无论选哪种推理方式，Open WebUI 的对接方式如下：

### 本地 llama.cpp 后端

```bash
# llama.cpp server 启动（CPU 模式）
./llama-server \
  --model /mnt/workspace/zephyr/models/Qwen3-8B-GGUF/qwen3-8b-q4_k_m.gguf \
  --host 127.0.0.1 \
  --port 8081 \
  --ctx-size 8192
```

Open WebUI 配置路径：
- Admin Settings → Connections → OpenAI → Add Connection
- URL: `http://127.0.0.1:8081/v1`
- API Key: 随意填（llama.cpp 不校验）
- 这样 Open WebUI 就能调用本地模型了

### ModelScope API 后端

```bash
# ModelScope API 是 OpenAI 兼容格式
# URL: https://api-inference.modelscope.cn/v1
# API Key: ms-xxxxxxxxxxxxxxxx（从魔搭个人中心获取，走 Secret 注入）
```

Open WebUI 配置：
- Admin Settings → Connections → OpenAI → Add Connection
- URL: `https://api-inference.modelscope.cn/v1`
- API Key: `${MODELSCOPE_API_KEY}`（环境变量注入）
- 可选模型：Qwen3-235B-A22B、Qwen3-Coder-480B-A35B-Instruct 等

### 端口分配补充（对接行者的 Nginx 路由）

| 服务 | 内部端口 | 绑定地址 |
|------|---------|---------|
| llama.cpp server | 8081 | 127.0.0.1 |
| Open WebUI | 8082 | 127.0.0.1 |
| Hermes Gateway | 8642 | 127.0.0.1 |
| Hermes Studio | 8648 | 127.0.0.1 |
| noVNC | 6080 | 127.0.0.1 |

> **注意：** 行者方案中 Open WebUI 用的是 8080，但魔搭 Docker Space 文档明确说 **8080 端口被魔搭平台自带进程占用，不可使用**。必须改用其他端口（如 8082），然后由 Nginx 统一反代。

---

## Dockerfile 模型层补充

在行者的 Dockerfile 分层基础上，增加一个模型层：

```dockerfile
# Stage 3.5: ModelScope SDK + 模型下载
RUN pip install modelscope

# 设置模型缓存路径到持久化目录
ENV MODELSCOPE_CACHE=/mnt/workspace/zephyr/models

# 构建参数（可选哪些模型预装）
ARG PRELOAD_QWEN3_8B=1
ARG PRELOAD_QWEN3_1_7B=1

# 预下载模型到镜像（首次构建时）
# 注意：这些模型也会在 /mnt/workspace 持久化，重建后不丢
RUN if [ "$PRELOAD_QWEN3_8B" = "1" ]; then \
      modelscope download --model Qwen/Qwen3-8B-GGUF; \
    fi
RUN if [ "$PRELOAD_QWEN3_1_7B" = "1" ]; then \
      modelscope download --model Qwen/Qwen3-1.7B-GGUF; \
    fi
```

---

## 环境变量/Secrets 补充

在现有 Secrets 列表基础上，增加以下与模型相关的：

```
MODELSCOPE_API_KEY        — 魔搭 API Key（ms-xxx），用于 API 调用
MODELSCOPE_CACHE          — 模型缓存路径（/mnt/workspace/zephyr/models）
LLAMA_CPP_THREADS         — llama.cpp CPU 线程数（建议=CPU核数-1）
LLAMA_CPP_CTX_SIZE        — 上下文窗口（默认8192，按需调整）
OPENWEBUI_DEFAULT_MODEL   — Open WebUI 默认模型（如 qwen3-8b-local）
```

---

## 总结：需要你确认的 4 项

| # | 选择项 | 推荐 |
|---|--------|------|
| 8 | 模型来源与推理方式 | **C. 混合模式**（本地8B + API大模型） |
| 9 | 本地模型选型 | **Qwen3-8B-Q4_K_M + Qwen3-1.7B-Q4_K_M** |
| 10 | GPU 资源 | **A. CPU only 起步**（后续按需申请 xGPU） |
| 11 | ModelScope SDK 集成 | **A. modelscope CLI**（download 命令预装模型） |

> 确认后我会配合行者、海豚把模型层代码集成进主 Dockerfile 和 entrypoint 脚本。
