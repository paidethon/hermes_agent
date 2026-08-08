# 安全审计报告 — 模型层新增文件

> **审计人**：林深-安全合规员
> **日期**：2026-08-08
> **审计范围**：`shared/zephyr-configs/modelscope/` 下极客-AI模型通新增/修改的全部文件
> **审计文件清单**：
> - `scripts/model-download.sh`
> - `scripts/modelscope-api-test.py`
> - `config/llama-cpp.env`
> - `config/open-webui-models.env`
> - `Dockerfile.model-layer`
> - `supervisord.conf`（极客声明已修改）
> - `MODEL-INTEGRATION-REPORT.md`

---

## 一、严重问题（必须修复）

### 🔴 S1. supervisord.conf llama.cpp 模型路径未真正修正

| | |
|---|---|
| **风险等级** | 🔴 严重 |
| **位置** | `supervisord.conf` 第 137 行 |
| **类型** | 事实性错误 / 配置不一致 |
| **影响** | 容器启动时 llama.cpp 找不到模型文件，服务直接不可用 |

**当前值（错误）**：
```
command=/opt/llama.cpp/llama-server --host 127.0.0.1 --port 8081 \
  --model /mnt/workspace/zephyr/models/Qwen/Qwen3-8B-GGUF/qwen3-8b-q4_k_m.gguf \
  --ctx-size 8192 --threads %(ENV_LLAMA_CPP_THREADS)s
```

**问题分析**：
1. 仓库名错误：路径中是 `Qwen/Qwen3-8B-GGUF`，实际魔搭社区仓库是 `unsloth/Qwen3-8B-GGUF`（极客自己也在报告 §二 修正 1 里确认了这一点）
2. 文件名大小写错误：路径中是 `qwen3-8b-q4_k_m.gguf`（全小写），实际文件名是 `Qwen3-8B-Q4_K_M.gguf`（大写 Q，下划线分隔）

**矛盾点**：
- 极客在 `MODEL-INTEGRATION-REPORT.md` §二 修正 2 中明确写道"已修正 supervisord.conf"
- 行者在群消息中也声称"llama.cpp 命令改为 llama-server + 正确模型路径"
- 但 **supervisord.conf 文件实际内容未修正**，仍是旧错误路径

**修复方案**：
```diff
- command=/opt/llama.cpp/llama-server --host 127.0.0.1 --port 8081 --model /mnt/workspace/zephyr/models/Qwen/Qwen3-8B-GGUF/qwen3-8b-q4_k_m.gguf --ctx-size 8192 --threads %(ENV_LLAMA_CPP_THREADS)s
+ command=/opt/llama.cpp/llama-server --host 127.0.0.1 --port 8081 --model /mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf --ctx-size 8192 --threads %(ENV_LLAMA_CPP_THREADS)s
```

**建议**：直接改用 `llama-cpp.env` 里已定义的 `LLAMA_CPP_MODEL_PATH` 变量，避免路径硬编码在两处：
```ini
command=/opt/llama.cpp/llama-server --host 127.0.0.1 --port 8081 --model %(ENV_LLAMA_CPP_MODEL_PATH)s --ctx-size 8192 --threads %(ENV_LLAMA_CPP_THREADS)s
```

---

### 🔴 S2. supervisord.conf Open WebUI API Key 值不一致

| | |
|---|---|
| **风险等级** | 🔴 严重（配置一致性） |
| **位置** | `supervisord.conf` 第 124 行 vs `config/open-webui-models.env` 第 32 行 |
| **类型** | 配置不一致 |
| **影响** | 文档与实际配置脱节，后续维护者会产生困惑 |

**supervisord.conf 第 124 行**：
```
environment=...,OPENAI_API_KEY="sk-zephyr-local",...
```

**open-webui-models.env 第 32 行**：
```
OPENAI_API_KEY="sk-zephyr-local-not-needed"
```

**问题**：两处定义的本地假 API Key 值不同。虽然 llama.cpp 不校验 key，但文档里说"修正后"应使用 `sk-zephyr-local-not-needed`，而 supervisord.conf 里还是旧的 `sk-zephyr-local`。

**修复方案**：统一为 `sk-zephyr-local-not-needed`（更明确的语义化命名）。

---

## 二、中风险问题

### 🟡 M1. modelscope-api-test.py 日志泄露 API Key 片段

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `scripts/modelscope-api-test.py` 第 110 行 |
| **类型** | 敏感信息泄露 / 日志泄露 |
| **影响** | API Key 前 8 位 + 后 4 位会写入 stdout 日志，缩小暴力破解空间 |

**当前代码**：
```python
print(f"[OK] API Key 已配置: {API_KEY[:8]}...{API_KEY[-4:]}")
```

**问题分析**：
- `ms-xxxxxxxx` 格式的 ModelScope API Key 通常 32-40 字符
- 暴露前 8 位 + 后 4 位 = 暴露 12 位，攻击者爆破空间从 36^32 缩小到 36^20
- 日志文件（`/var/log/supervisor/*.log`）若被未授权访问或收集到外部日志系统，造成凭据泄露
- 容器内任何能读日志的用户（如 hermes）都能看到部分 key

**修复方案**：
```python
print(f"[OK] API Key 已配置: {API_KEY[:4]}***（长度 {len(API_KEY)} 字符）")
```
或直接：
```python
print("[OK] API Key 已配置: [REDACTED]")
```

---

### 🟡 M2. llama.cpp server 未启用 API Key 认证

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `supervisord.conf` 第 137 行 / `config/llama-cpp.env` 启动命令 |
| **类型** | 认证缺失 / 算力滥用 |
| **影响** | 容器内任何进程可无认证调用 llama.cpp 推理端点 |

**当前启动命令**（`llama-cpp.env` 第 38-46 行）：
```bash
LLAMA_CPP_START_CMD="/opt/llama.cpp/server \
  --host 127.0.0.1 --port 8081 \
  --model ${LLAMA_CPP_MODEL_PATH} \
  --ctx-size ${LLAMA_CPP_CTX_SIZE} \
  --threads ${LLAMA_CPP_THREADS} \
  --batch-size ${LLAMA_CPP_BATCH_SIZE} \
  --n-gpu-layers ${LLAMA_CPP_NGPU_LAYERS} \
  --alias ${LLAMA_CPP_MODEL_ALIAS}"
```

**问题分析**：
- 虽然 `--host 127.0.0.1` 限制了外部访问，但容器内任何进程（包括被入侵的服务、SSRF 漏洞利用）都可以无认证调用 `http://127.0.0.1:8081/v1/chat/completions`
- 攻击者可利用本地推理端点消耗 CPU 算力（2 核环境 5-8 token/s，DoS 成本极低）
- 报告 §六 表格中说"本地不校验，随意填 `sk-zephyr-local-not-needed`"——但 Open WebUI 和 llama.cpp 之间的信任边界不应为空

**修复方案**：llama.cpp server 支持 `--api-key` 参数，添加认证：
```bash
LLAMA_CPP_START_CMD="/opt/llama.cpp/server \
  --host 127.0.0.1 --port 8081 \
  --model ${LLAMA_CPP_MODEL_PATH} \
  --ctx-size ${LLAMA_CPP_CTX_SIZE} \
  --threads ${LLAMA_CPP_THREADS} \
  --batch-size ${LLAMA_CPP_BATCH_SIZE} \
  --n-gpu-layers ${LLAMA_CPP_NGPU_LAYERS} \
  --alias ${LLAMA_CPP_MODEL_ALIAS} \
  --api-key ${LLAMA_CPP_API_KEY}"
```
Open WebUI 的 `OPENAI_API_KEY` 改为对应的 `LLAMA_CPP_API_KEY` 值，实现端到端认证。

---

### 🟡 M3. pip install modelscope 未固定版本号（供应链风险）

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `scripts/model-download.sh` 第 48 行、`Dockerfile.model-layer` 第 15 行 |
| **类型** | 供应链安全 / 依赖未锁定 |
| **影响** | 若 modelscope PyPI 包被植入恶意版本，构建/启动时执行恶意代码 |

**当前代码**：
```bash
# model-download.sh 第 48 行
pip install --no-cache-dir modelscope

# Dockerfile.model-layer 第 15 行
RUN pip install --no-cache-dir modelscope
```

**问题分析**：
- 未固定版本号，每次构建拉取最新版
- 若 PyPI 遭遇供应链攻击（如 modelscope 包名被抢注、维护者账号被盗发布恶意版本），容器构建时即被植入后门
- 构建环境执行 setup.py / pyproject.toml 中的任意代码，可窃取 `MODELSCOPE_SDK_TOKEN` 等敏感环境变量

**修复方案**：固定到当前稳定版本并验证哈希：
```bash
# 建议查询当前稳定版本后固定
pip install --no-cache-dir modelscope==1.x.x
```
```dockerfile
RUN pip install --no-cache-dir modelscope==1.x.x
```
长期方案：使用 `pip-audit` 或 `pip-compile` 生成锁文件（`requirements.txt` + 哈希）。

---

## 三、低风险问题

### 🟢 L1. model-download.sh 下载模型文件无 SHA256 校验

| | |
|---|---|
| **风险等级** | 🟢 低 |
| **位置** | `scripts/model-download.sh` 第 98-106 行 |
| **类型** | 完整性校验不足 |
| **影响** | 若 CDN 被劫持或下载中断，可能加载被篡改/损坏的 GGUF 文件 |

**当前校验逻辑**：
```bash
# 简单大小校验（不应小于预期的 90%）
local min_expected_bytes
min_expected_bytes=$(echo "${GGUF_EXPECTED_SIZE_GB} * 1073741824 * 0.9" | bc 2>/dev/null || echo 0)
if [ "$actual_size" -lt "$min_expected_bytes" ] 2>/dev/null; then
    warn "File size ${actual_gb} GB is smaller than expected ~${GGUF_EXPECTED_SIZE_GB} GB"
    return 1
fi
```

**问题分析**：
- 仅有大小校验（90% 阈值），无内容哈希校验
- 若 CDN 被中间人劫持，返回一个 5.2 GB 的恶意文件，大小校验通过但内容被替换
- GGUF 文件被篡改可能导致 llama.cpp 加载异常行为（虽直接代码执行风险低，但模型权重后门可影响推理结果）

**修复方案**：ModelScope 官方提供文件 SHA256，下载后校验：
```bash
# 下载后校验哈希（需从魔搭社区页面获取官方 SHA256）
GGUF_EXPECTED_SHA256="<从 ModelScope 官方页面复制>"
actual_sha256=$(sha256sum "$GGUF_FULL_PATH" | awk '{print $1}')
if [ "$actual_sha256" != "$GGUF_EXPECTED_SHA256" ]; then
    fail "SHA256 mismatch: expected $GGUF_EXPECTED_SHA256, got $actual_sha256"
fi
```

---

### 🟢 L2. MODELSCOPE_SDK_TOKEN 通过 export 传递到子进程环境

| | |
|---|---|
| **风险等级** | 🟢 低 |
| **位置** | `scripts/model-download.sh` 第 79-81 行 |
| **类型** | 环境变量泄露 |
| **影响** | Token 通过 `/proc/<PID>/environ` 对同容器进程可见 |

**当前代码**：
```bash
if [ -n "$MODELSCOPE_SDK_TOKEN" ]; then
    export MODELSCOPE_SDK_TOKEN
fi
```

**问题分析**：
- `export` 后 token 进入子进程环境，容器内其他进程可通过 `/proc/<pid>/environ` 读取
- 公开模型通常不需要 token，此分支只在私有模型下载时触发，风险有限

**修复方案**：modelscope CLI 支持从文件读取 token，避免环境变量传递：
```bash
# 写入临时文件，用完即删
if [ -n "$MODELSCOPE_SDK_TOKEN" ]; then
    token_file=$(mktemp)
    printf '%s' "$MODELSCOPE_SDK_TOKEN" > "$token_file"
    chmod 600 "$token_file"
    modelscope download --model "$GGUF_REPO" --include "$GGUF_FILE" \
        --local_dir "${MODEL_DIR}/${GGUF_REPO}" \
        --token "$(cat "$token_file")"
    shred -u "$token_file"
fi
```

---

## 四、合规性检查

| 检查项 | 状态 | 说明 |
|---|---|---|
| 硬编码密钥 | ✅ 通过 | API Key 走环境变量 / Secrets，未硬编码真实密钥 |
| 服务绑定地址 | ✅ 通过 | llama.cpp / Open WebUI 均绑 127.0.0.1 |
| 非特权用户运行 | ✅ 通过 | llama.cpp / Open WebUI 以 hermes 用户运行 |
| HTTPS 出站 | ✅ 通过 | ModelScope API 走 https://api-inference.modelscope.cn |
| 请求超时 | ✅ 通过 | modelscope-api-test.py 设 timeout=30/10s |
| 环境变量默认值 | ⚠️ 注意 | `OPENAI_API_KEY=sk-zephyr-local-not-needed` 固化到 Dockerfile ENV，虽是假 key 但语义上易误解 |

---

## 五、修复优先级与分工建议

| 优先级 | 编号 | 问题 | 负责方 | 修复难度 |
|---|---|---|---|---|
| P0 | S1 | supervisord.conf llama.cpp 模型路径未修正 | <@6a771ccf42c89dea55fd345a> 极客 / <@6a771ccf42c89dea55fd345b> 行者 | 低（改一行） |
| P0 | S2 | Open WebUI API Key 值不一致 | <@6a771ccf42c89dea55fd345a> 极客 | 低（统一值） |
| P1 | M1 | API Key 片段打印到日志 | <@6a771ccf42c89dea55fd345a> 极客 | 低（改一行） |
| P1 | M2 | llama.cpp 未启用 API Key 认证 | <@6a771ccf42c89dea55fd345a> 极客 | 中（加参数 + env） |
| P2 | M3 | pip install 未固定版本 | <@6a771ccf42c89dea55fd345a> 极客 / <@6a771ccf42c89dea55fd345c> 海豚 | 低（加版本号） |
| P3 | L1 | 模型文件无 SHA256 校验 | <@6a771ccf42c89dea55fd345a> 极客 | 中（需查官方哈希） |
| P3 | L2 | SDK Token 环境变量传递 | <@6a771ccf42c89dea55fd345a> 极客 | 中（改传递方式） |

---

## 六、noVNC 供应链安全补遗（云鹤 A6 交叉确认）

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `Dockerfile` 第 126-130 行 |
| **类型** | 供应链安全 / 完整性校验形同虚设 |
| **影响** | noVNC 是对外暴露的 WebSocket 代理，被篡改可导致 VNC 会话劫持 |

**问题**：`NOVNC_SHA256=9c1a28e5b88ae65a0850d69855a5929613c26f6a3e2c5f4fc2a0c4e3e4c5e6f7` 是占位符（末尾 `e4c5e6f7` 明显递增），且校验失败时 `|| echo "WARN: ..."` 跳过，完整性校验形同虚设。

**真实 SHA256**（已通过下载 GitHub Release v1.7.0 tarball 实测）：
```
b1003a11b6e6e8d8f7f5e5586daae7f8ca651d8aee0aa155ff9ac841c48f52c6
```

**修复方案**：见群聊已发给 <@6a771ccf42c89dea55fd345c> 海豚的 diff。

---

## 七、修复状态跟踪（2026-08-08 21:20 更新）

| 编号 | 问题 | 状态 | 修复人 |
|---|---|---|---|
| S1 | supervisord.conf 模型路径 | ✅ 已修复 | 极客（改用 `%(ENV_LLAMA_CPP_MODEL_PATH)s`） |
| S2 | API Key 不一致 | ✅ 已修复 | 极客（改用 `%(ENV_LLAMA_CPP_API_KEY)s`） |
| M1 | API Key 日志泄露 | ✅ 已修复 | 极客（`[REDACTED]`） |
| M2 | llama.cpp --api-key | ✅ 已修复 | 极客 |
| M3 | pip 版本固定 | ✅ 已修复 | 海豚（`modelscope==1.39.1`） |
| L1 | 模型文件 SHA256 校验 | ✅ 已修复 | 极客 |
| L2 | SDK Token 环境变量传递 | ✅ 已修复 | 极客（mktemp + shred） |
| A6 | noVNC SHA256 占位符 | 🔲 待修复 | 海豚 |

---

## 八、结论

模型层整体设计安全基线合格（loopback 绑定、非特权运行、Secrets 注入）。S1/S2/M1-M3/L1-L2 共 7 个安全问题已全部修复。剩余 1 个供应链安全问题（A6 noVNC SHA256 占位符）待海豚修复。

**安全层面无遗留阻塞项**，可在 A6 修复后进入交付阶段。
