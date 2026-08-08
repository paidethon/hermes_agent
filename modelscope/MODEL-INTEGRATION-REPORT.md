# Zephyr AI Desktop — 模型集成评估报告

> **维护者**：极客-AI模型通
> **日期**：2026-08-08
> **方案版本**：最终方案文档确认版

---

## 一、决策项确认状态

| 编号 | 选择项 | 最终确认 | 评估 |
|---|---|---|---|
| 8 | 模型来源 | C. 混合模式（本地 Qwen3-8B + API Qwen3-235B） | ✅ 合理，日常80%用本地，复杂任务走API |
| 9 | 本地模型 | Qwen3-8B-Q4_K_M（~5GB） | ✅ CPU 推理最佳性价比 |
| 10 | GPU | A. CPU only 起步 | ✅ 2核 CPU 预估 5-8 token/s，够用 |
| 11 | ModelScope SDK | A. modelscope CLI | ✅ 构建时预下载，持久化缓存 |

---

## 二、方案文档修正项（3 处）

### 修正 1：GGUF 仓库名错误

| | 方案文档 | 实际（修正后） |
|---|---|---|
| 仓库名 | `Qwen/Qwen3-8B-GGUF` | `unsloth/Qwen3-8B-GGUF` |
| 来源 | §8.1 模型来源 | 魔搭社区实际仓库 |
| 说明 | Qwen 官方在魔搭社区只有 `Qwen/Qwen3-8B`（原版权重），没有 GGUF 版本。GGUF 量化版由 unsloth 维护，仓库名为 `unsloth/Qwen3-8B-GGUF`。 |

### 修正 2：GGUF 文件名大小写

| | 方案文档 | 实际（修正后） |
|---|---|---|
| 文件名 | `qwen3-8b-q4_k_m.gguf`（小写） | `Qwen3-8B-Q4_K_M.gguf`（大写 Q） |
| 影响 | llama.cpp 启动参数 `--model` 路径写死小写会找不到文件 | 已修正 supervisord.conf |

### 修正 3：Open WebUI 后端指向错误

| | 原 supervisord.conf | 修正后 |
|---|---|---|
| `OPENAI_API_BASE_URL` | `http://127.0.0.1:8642/v1`（Hermes Gateway） | `http://127.0.0.1:8081/v1`（llama.cpp） |
| 说明 | Hermes Gateway 是 Agent 编排层，不是推理后端。Open WebUI 应指向 llama.cpp 做本地推理。ModelScope API 作为第二个连接在界面里手动配置。 |

---

## 三、新增文件清单

以下文件已放到 `shared/zephyr-configs/modelscope/` 下：

| 文件 | 用途 | 合并方 |
|---|---|---|
| `scripts/model-download.sh` | ModelScope CLI 模型预下载脚本 | entrypoint.sh 首次启动调用 |
| `scripts/modelscope-api-test.py` | ModelScope API 连通性测试 | entrypoint.sh 启动后可选调用 |
| `config/llama-cpp.env` | llama.cpp 启动环境变量 | supervisord 引用 |
| `config/open-webui-models.env` | Open WebUI 双后端对接配置 | supervisord 引用 |
| `Dockerfile.model-layer` | Dockerfile 层 6 片段 | 海豚合并进主 Dockerfile |

### 修改文件

| 文件 | 修改内容 |
|---|---|
| `supervisord.conf` | llama.cpp 模型路径修正 + 启动参数增强；Open WebUI 后端 URL 修正 |

---

## 四、modelscope download 命令说明

### 基本用法

```bash
# 下载整个仓库
modelscope download --model unsloth/Qwen3-8B-GGUF

# 只下载特定文件（推荐，避免下载全部量化版本 ~40 GB）
modelscope download \
  --model unsloth/Qwen3-8B-GGUF \
  --include "Qwen3-8B-Q4_K_M.gguf" \
  --local_dir /mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF
```

### 关键参数

| 参数 | 说明 |
|---|---|
| `--model` | 仓库 ID（组织/模型名），如 `unsloth/Qwen3-8B-GGUF` |
| `--include` | 只下载匹配的文件（支持 glob 模式），避免全量下载 |
| `--local_dir` | 指定下载目录 |
| `MODELSCOPE_CACHE` | 环境变量，控制缓存根目录 |
| `MODELSCOPE_SDK_TOKEN` | 私有模型需要，公开模型可不设 |

### 默认缓存路径

不设 `MODELSCOPE_CACHE` 时，默认下载到 `~/.cache/modelscope/hub/`。
本方案设为 `/mnt/workspace/zephyr/models`，确保 ModelScope 重建容器后模型不丢。

---

## 五、ModelScope API 推理端点

### 基本信息

| 配置项 | 值 |
|---|---|
| API Base URL | `https://api-inference.modelscope.cn/v1` |
| 兼容格式 | OpenAI API 兼容 |
| 认证方式 | `Authorization: Bearer ms-xxxxxxxx` |
| 免费额度 | 每日 2000 次调用（注册即送） |
| API Key 获取 | ModelScope → 头像 → 访问令牌 → SDK Token |

### 可用模型 ID

| 模型 ID | 用途 | 备注 |
|---|---|---|
| `Qwen/Qwen3-235B-A22B-Instruct-2507` | 通用对话（推荐） | 指令遵循版 |
| `Qwen/Qwen3-235B-A22B` | 思考模式 | 带思维链 |
| `Qwen/Qwen3-Coder-480B-A35B-Instruct` | 代码生成 | 480B MoE |

### 调用示例

```python
import requests

url = "https://api-inference.modelscope.cn/v1/chat/completions"
headers = {
    "Authorization": "Bearer ms-xxxxxxxx",
    "Content-Type": "application/json",
}
payload = {
    "model": "Qwen/Qwen3-235B-A22B-Instruct-2507",
    "messages": [{"role": "user", "content": "你好"}],
    "max_tokens": 100,
}
resp = requests.post(url, headers=headers, json=payload)
print(resp.json())
```

---

## 六、Open WebUI 双后端对接

### 架构

```
Open WebUI (:8082)
  │
  ├── [默认后端] 本地 llama.cpp (:8081)
  │     └── Qwen3-8B-Q4_K_M (~5 GB, CPU 推理)
  │     └── 别名: qwen3-8b-local
  │     └── 速度: 5-8 token/s
  │
  └── [第二后端] ModelScope API (云端)
        └── Qwen3-235B-A22B-Instruct-2507
        └── 速度: 快（云端 GPU）
        └── 限制: 每日 2000 次
```

### 用户操作

1. **本地模型**：Open WebUI 启动后自动连接 llama.cpp，下拉框选 `qwen3-8b-local`
2. **API 模型**：用户在 `Settings → Connections` 中手动添加：
   - 连接名称：`ModelScope API`
   - Base URL：`https://api-inference.modelscope.cn/v1`
   - API Key：`${MODELSCOPE_API_KEY}`（从 ModelScope Secrets 注入）
3. 切换：下拉框选不同模型即可

### 环境变量

| 变量 | 值 | 说明 |
|---|---|---|
| `OPENAI_API_BASE_URL` | `http://127.0.0.1:8081/v1` | 默认指向 llama.cpp |
| `OPENAI_API_KEY` | `sk-zephyr-local-internal` | 与 llama.cpp `--api-key` 一致，端到端认证 |
| `MODELSCOPE_API_KEY` | `ms-xxxxxxxx` | Secret 注入，用户在界面配第二后端时用 |

---

## 七、llama.cpp 启动参数

### 修正后启动命令

```bash
/opt/llama.cpp/llama-server \
  --host 127.0.0.1 \
  --port 8081 \
  --model /mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf \
  --ctx-size 8192 \
  --threads 1 \
  --batch-size 512 \
  --alias qwen3-8b-local
```

### 参数说明

| 参数 | 值 | 说明 |
|---|---|---|
| `--host` | `127.0.0.1` | 仅 loopback，不对外暴露 |
| `--port` | `8081` | 内部端口 |
| `--model` | 实际 GGUF 路径 | 修正后指向真实文件名 |
| `--ctx-size` | `8192` | 8K 上下文窗口 |
| `--threads` | `1` | 魔搭 2 核环境，预留 1 核给其他服务 |
| `--batch-size` | `512` | 并行批处理 |
| `--alias` | `qwen3-8b-local` | Open WebUI 显示的模型别名 |

---

## 八、entrypoint.sh 模型层集成建议

建议在 entrypoint.sh 的 `main()` 函数中、启动 supervisord 之前，加入模型存在性检查：

```bash
# Step 1.5: 模型存在性检查（在安全初始化之后、启动 supervisord 之前）
check_model_availability() {
    log "Checking local model availability..."

    local model_path="${LLAMA_CPP_MODEL_PATH:-/mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf}"

    if [ "${ENABLE_LLAMA_CPP:-1}" = "1" ]; then
        if [ ! -f "$model_path" ]; then
            warn "Local model not found at ${model_path}"
            log "Running model-download.sh to fetch Qwen3-8B-Q4_K_M..."
            /opt/zephyr/scripts/model-download.sh || {
                warn "Model download failed, llama.cpp will be skipped"
                export ENABLE_LLAMA_CPP=0
            }
        else
            log "Local model found: ${model_path}"
        fi
    fi
}
```

---

## 九、后续升级路径

| 场景 | 操作 |
|---|---|
| 加 GPU | 申请魔搭 xGPU → 重新编译 llama.cpp GPU 版 → `--n-gpu-layers` 设为层数 → 模型可升级 14B/32B |
| 加更多本地模型 | `modelscope download --model unsloth/Qwen3-xxx-GGUF --include "*.gguf"` → 修改 llama.cpp `--model` 参数 |
| 切换 API 模型 | Open WebUI → Settings → Connections 添加新连接 |
| 启用 Flowise | `ENABLE_FLOWISE=1` → Nginx 加 `/flow/` 路由 → Flowise 连 llama.cpp 或 ModelScope API |

---

## 十、风险评估

| 风险 | 级别 | 对策 |
|---|---|---|
| 构建时下载模型超时（~5 GB） | 中 | 设 `PRELOAD_QWEN3_8B=0`，改 entrypoint 首次启动下载 |
| CPU 推理速度慢 | 低 | 5-8 token/s 够用，复杂任务走 API |
| ModelScope API 额度用完 | 低 | 每日 2000 次，本地模型兜底 |
| GGUF 仓库被下架 | 低 | unsloth 是可信维护者，长期更新 |
| 模型文件名变更 | 低 | model-download.sh 有大小校验，文件不存在会重新下载 |
