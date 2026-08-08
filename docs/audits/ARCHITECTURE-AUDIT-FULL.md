# 架构审计报告 — Zephyr AI Desktop 完整版

> **审计人**：云鹤-架构审计师
> **日期**：2026-08-08
> **审计范围**：`shared/zephyr-configs/` 全目录文件
> **审计视角**：宏观架构合理性、模块耦合度、配置一致性、可维护性

---

## 一、高危问题

### 🔴 A1. first-run-init.sh 从未被调用 — 死代码

| | |
|---|---|
| **风险等级** | 🔴 高 |
| **位置** | `scripts/first-run-init.sh` vs `modelscope/entrypoint.sh` |
| **类型** | 死代码 / 功能缺失 |

**问题分析**：

`first-run-init.sh` 定义了4个关键初始化函数：
1. `restore_from_onedrive()` — OneDrive 加密备份恢复
2. `ensure_model()` — 模型下载
3. `ensure_hermes_seed()` — Hermes 种子配置部署
4. `ensure_open_webui()` — Open WebUI 数据目录初始化

但 `entrypoint.sh` 的 `main()` 函数 **从未调用 `first-run-init.sh`**。其执行流程为：

```
init_persistence → verify_all_seeds → generate_htpasswd →
generate_vnc_password → generate_rclone_config →
final_permission_check → check_model_availability → exec supervisord
```

**后果**：
- 🔴 **OneDrive 备份恢复逻辑完全缺失** — 容器重建后无法从云端恢复数据
- 🔴 **Hermes 种子配置不会部署到持久化目录** — 首次启动可能无配置
- ✅ 模型下载部分由 `check_model_availability()` 替代覆盖（但有重复逻辑）

`entrypoint.sh` 的 `check_model_availability()` 与 `first-run-init.sh` 的 `ensure_model()` 功能重叠，但前者缺少备份恢复和种子部署。

**修复方案**：

方案A（推荐）— 在 `entrypoint.sh` 的 `main()` 中调用 `first-run-init.sh`：

```bash
main() {
    log "=== Zephyr AI Desktop Entry Point ==="

    init_persistence

    # 首次初始化（备份恢复 + 模型 + 种子 + WebUI）
    /opt/scripts/first-run-init.sh || {
        warn "First-run init encountered errors, continuing..."
    }

    verify_all_seeds
    generate_htpasswd
    generate_vnc_password
    generate_rclone_config
    final_permission_check

    # check_model_availability 已由 first-run-init.sh 的 ensure_model 覆盖
    # 可移除或保留作为二次确认

    log "Starting supervisord..."
    exec /usr/bin/supervisord -n -c /etc/supervisor/conf.d/supervisord.conf
}
```

方案B — 将 `first-run-init.sh` 的逻辑合并进 `entrypoint.sh`，消除文件间依赖。

---

### 🔴 A2. 配置文件成为死代码 — llama-cpp.env / open-webui-models.env 从未被 source

| | |
|---|---|
| **风险等级** | 🔴 高 |
| **位置** | `modelscope/config/llama-cpp.env` / `modelscope/config/open-webui-models.env` |
| **类型** | 死配置 / 配置源分裂 |

**问题分析**：

Dockerfile 将这两个文件 COPY 到 `/opt/zephyr/config/` 目录：

```dockerfile
COPY modelscope/config/llama-cpp.env /opt/zephyr/config/llama-cpp.env
COPY modelscope/config/open-webui-models.env /opt/zephyr/config/open-webui-models.env
```

但 **没有任何脚本 source 它们**。`entrypoint.sh` 没有 `source /opt/zephyr/config/*.env`，`supervisord.conf` 也没有引用这些文件的变量。

**后果 — 配置源分裂为两套，值不一致**：

| 参数 | supervisord.conf | .env 文件 | 实际生效 |
|---|---|---|---|
| llama.cpp 二进制名 | `/opt/llama.cpp/llama-server` ✅ | `/opt/llama.cpp/server` ❌ | supervisord.conf |
| Open WebUI API Key | `sk-zephyr-local` | `sk-zephyr-local-not-needed` | supervisord.conf |
| llama.cpp --n-gpu-layers | 未设置 | `--n-gpu-layers 0` | supervisord.conf |
| llama.cpp 启动命令 | 硬编码完整命令 | `LLAMA_CPP_START_CMD` 变量 | supervisord.conf |

**核心矛盾**：极客在 `open-webui-models.env` 中明确写道"修正：原 supervisord.conf 写的 http://127.0.0.1:8642/v1 是错误的，应指向 llama.cpp"，但这个修正 **从未被应用**——supervisord.conf 当前确实是 `127.0.0.1:8081/v1`，但不是因为读了 env 文件，而是因为行者在写 supervisord.conf 时直接写了正确值。

这导致维护者修改 `.env` 文件后 **不会产生任何效果**，形成"改了以为生效但实际没有"的协作盲区（与林深 S1/S2 发现的同类问题一致）。

**修复方案**：

选择A（推荐）— 删除 `.env` 文件，仅保留 supervisord.conf 作为唯一配置源：

```bash
# 删除死配置文件
rm modelscope/config/llama-cpp.env
rm modelscope/config/open-webui-models.env
# Dockerfile 中删除对应 COPY 行
```

选择B — 让 supervisord.conf 引用 Dockerfile ENV 变量，消除硬编码：

```ini
# supervisord.conf
[program:llama-cpp]
command=/opt/llama.cpp/llama-server \
    --host 127.0.0.1 --port 8081 \
    --model %(ENV_LLAMA_CPP_MODEL_PATH)s \
    --ctx-size %(ENV_LLAMA_CPP_CTX_SIZE)s \
    --threads %(ENV_LLAMA_CPP_THREADS)s \
    --batch-size 512 \
    --alias qwen3-8b-local
```

Dockerfile 已设置 `ENV LLAMA_CPP_MODEL_PATH=...` 和 `ENV LLAMA_CPP_CTX_SIZE=8192`，supervisord 可通过 `%(ENV_*)s` 引用，实现单一数据源。

---

## 二、中风险问题

### 🟡 A3. 模型路径定义在6处 — DRY 严重违反

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **类型** | DRY 违反 / 维护风险 |

模型路径 `/mnt/workspace/zephyr/models/unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf` 出现在以下位置：

| # | 文件 | 行 | 定义方式 |
|---|---|---|---|
| 1 | `Dockerfile` | 213 | `ENV LLAMA_CPP_MODEL_PATH=...` |
| 2 | `supervisord.conf` | 137 | 硬编码在 command 中 |
| 3 | `llama-cpp.env` | 12 | `LLAMA_CPP_MODEL_PATH="..."` |
| 4 | `entrypoint.sh` | 295 | `local model_path="..."` |
| 5 | `first-run-init.sh` | 77-78 | `local model_repo=...; local model_file=...` |
| 6 | `model-download.sh` | 28-29 | `GGUF_REPO=...; GGUF_FILE=...` |

任何路径变更需同步修改6处，极易遗漏（此前已发生过 `Qwen/` vs `unsloth/` 的大小写/仓库名错误）。

**修复方案**：以 Dockerfile `ENV LLAMA_CPP_MODEL_PATH` 为唯一数据源，所有脚本和 supervisord 引用该变量：

```bash
# entrypoint.sh
check_model_availability() {
    local model_path="${LLAMA_CPP_MODEL_PATH:?LLAMA_CPP_MODEL_PATH not set}"
    # ...
}
```

```ini
# supervisord.conf
command=... --model %(ENV_LLAMA_CPP_MODEL_PATH)s ...
```

---

### 🟡 A4. 线程数配置矛盾 — 2核容器设2线程导致服务饥饿

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **类型** | 性能 / 资源竞争 |

| 来源 | LLAMA_CPP_THREADS 值 |
|---|---|
| `Dockerfile` ENV | `2` |
| `docker-compose.yml` | `"2"` |
| `.env.example` | `2` |
| `llama-cpp.env` | `${LLAMA_CPP_THREADS:-1}` (默认1) |
| `supervisord.conf` | `%(ENV_LLAMA_CPP_THREADS)s` (取Dockerfile的2) |

魔搭 Docker Space 默认 2 核 CPU。llama.cpp 占用 2 线程后，Nginx / VNC / noVNC / Hermes Gateway / Hermes Studio / Open WebUI 共享 0 核——全部被推理线程占满。

`llama-cpp.env` 的注释写 "建议 = 核数 - 1，预留 1 核"，默认值设为 1，但实际生效的 Dockerfile ENV 设为 2。

**修复方案**：统一改为 1：

```dockerfile
ENV LLAMA_CPP_THREADS=1
```

```yaml
# docker-compose.yml
LLAMA_CPP_THREADS: "1"
```

---

### 🟡 A5. Open WebUI 与 llama.cpp 之间无启动依赖协调

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `supervisord.conf` |
| **类型** | 启动顺序 / 服务依赖 |

supervisord 用 `priority` 控制启动顺序（llama.cpp priority=70, Open WebUI priority=60），但 supervisord 的 priority 只影响启动顺序，**不等待服务就绪**。

Qwen3-8B Q4_K_M GGUF 文件 ~5.2GB，首次加载到内存需 10-30 秒。Open WebUI 的 `startsecs=5` + `startretries=3` 仅给 15 秒窗口。如果 llama.cpp 加载超时，Open WebUI 会先启动并尝试连接 `127.0.0.1:8081/v1`，可能失败。

**修复方案**：在 entrypoint.sh 启动 supervisord 前加预检，或让 Open WebUI 的 startsecs 加大：

```ini
[program:open-webui]
# 等待 llama.cpp 就绪
startsecs=10
startretries=5
```

或在 entrypoint.sh 中，先同步启动 llama.cpp 加载模型，再 exec supervisord。

---

### 🟡 A6. noVNC SHA256 哈希值疑似占位符

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `Dockerfile` 第 126 行 |
| **类型** | 供应链安全 / 校验形同虚设 |

```dockerfile
ARG NOVNC_SHA256=9c1a28e5b88ae65a0850d69855a5929613c26f6a3e2c5f4fc2a0c4e3e4c5e6f7
```

该哈希值的模式 `9c1a28e5b88ae65a0850d69855a5929613c26f6a3e2c5f4fc2a0c4e3e4c5e6f7` 具有明显的顺序递增特征（...e4c5e6f7），不是真实的 SHA256 哈希。

Dockerfile 用 `|| echo "WARN: ..."` 处理了校验失败，使其不中断构建，但这也意味着 **完整性校验形同虚设**。

**修复方案**：从 noVNC v1.7.0 GitHub Release 页面获取真实 SHA256 并替换。或使用 GPG 签名验证替代哈希。

---

### 🟡 A7. Hermes 仓库 URL 为占位符 — 构建会静默回退到默认分支

| | |
|---|---|
| **风险等级** | 🟡 中 |
| **位置** | `Dockerfile` 第 69-73 行、180-184 行 |
| **类型** | 构建可靠性 |

```dockerfile
ARG HERMES_AGENT_REPO=https://github.com/NousResearch/hermes.git
ARG HERMES_AGENT_VERSION=v0.18.2
RUN git clone --branch ${HERMES_AGENT_VERSION} --depth 1 \
      ${HERMES_AGENT_REPO} /opt/hermes-src || \
    git clone --depth 1 ${HERMES_AGENT_REPO} /opt/hermes-src
```

- `https://github.com/NousResearch/hermes.git` 仓库不存在或不含 `v0.18.2` tag
- `||` 回退到 `--depth 1` 克隆默认分支，**静默忽略版本指定**
- 同样模式出现在 Hermes Studio（第 71-73 行）

**修复方案**：确认实际仓库地址和版本号后更新 ARG 值。去掉 `||` 静默回退，让构建失败暴露问题：

```dockerfile
RUN git clone --branch ${HERMES_AGENT_VERSION} --depth 1 \
      ${HERMES_AGENT_REPO} /opt/hermes-src
```

---

## 三、低风险问题

### 🟢 A8. health-check.sh 未被 Docker HEALTHCHECK 使用

`scripts/health-check.sh` 做了3级检查（Nginx响应 + supervisord + 进程存活），但 Dockerfile HEALTHCHECK 只用了 inline curl：

```dockerfile
HEALTHCHECK ... CMD curl -sf http://127.0.0.1:7860/health || exit 1
```

`health-check.sh` 被 COPY 到 `/opt/scripts/` 但从未被引用。建议统一：

```dockerfile
HEALTHCHECK ... CMD /opt/scripts/health-check.sh || exit 1
```

---

### 🟢 A9. docker-compose.yml 中 Open WebUI user 不一致

`supervisord.conf` 中 Open WebUI 以 `user=hermes` 运行，但 `open-webui-models.env` 文件中的"修正后"配置写的是 `user=root`。

虽然 env 文件是死代码（见 A2），但如果后续有人按这个文件修正 supervisord.conf，会将 Open WebUI 从非特权用户改回 root，产生安全回退。

---

## 四、架构评分总结

| 维度 | 评分 | 说明 |
|---|---|---|
| **高内聚** | ⚠️ 中 | entrypoint.sh 职责过重（初始化+安全+模型+启动），first-run-init.sh 存在但未接入 |
| **低耦合** | ⚠️ 中 | 模型路径在6处定义，配置源分裂为 supervisord + .env 两套 |
| **DRY** | ❌ 低 | 同一信息多处重复且值不一致（路径×6、线程数×4、API Key×2） |
| **可维护性** | ⚠️ 中 | 死代码文件造成"改了以为生效"的协作盲区 |
| **安全性** | ✅ 高 | 林深的5处修复已全部到位，安全基线合格 |
| **容器化** | ✅ 高 | 多阶段构建、层缓存优化、非特权用户 — 海豚做得好 |
| **CI/CD** | ✅ 高 | keepalive 修复逻辑清晰，build.yml 规范 |

---

## 五、修复优先级

| 优先级 | 编号 | 问题 | 负责方 | 修复难度 |
|---|---|---|---|---|
| P0 | A1 | first-run-init.sh 死代码 | <@6a771ccf42c89dea55fd345b> 行者 | 低（entrypoint 加一行调用） |
| P0 | A2 | .env 文件死配置 | <@6a771ccf42c89dea55fd345a> 极客 / 行者 | 低（删除或接入） |
| P1 | A3 | 模型路径 DRY 违反 | 行者 / 极客 | 中（统一为 ENV 变量） |
| P1 | A4 | 线程数矛盾 | <@6a771ccf42c89dea55fd345c> 海豚 | 低（改 Dockerfile ENV） |
| P2 | A5 | Open WebUI 启动依赖 | 行者 | 低（startsecs 加大） |
| P2 | A6 | noVNC 哈希占位符 | 海豚 | 低（查真实哈希） |
| P2 | A7 | Hermes 仓库 URL 占位符 | <@68f243b73650e783de5027ea> 用户确认 | 低（需确认实际地址） |
| P3 | A8 | health-check.sh 未使用 | 海豚 | 低（改 HEALTHCHECK CMD） |
| P3 | A9 | Open WebUI user 不一致 | 极客 | 低（改注释） |

---

## 六、与林深安全审计的交叉对照

林深在 `SECURITY-AUDIT-MODEL-LAYER.md` 中标记的 S1（模型路径未修正）**现已修复** — 当前 supervisord.conf 第 137 行已是正确路径 `unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf`。

S2（API Key 值不一致）**仍未修复** — supervisord.conf 仍为 `sk-zephyr-local`，与 env 文件的 `sk-zephyr-local-not-needed` 不一致。但因 env 文件是死代码（A2），实际不影响运行时，仅影响可维护性。

---

## 七、结论

行者的5处安全修复从安全角度确认到位。但从架构角度，当前配置体系存在**"两套配置源"**问题——supervisord.conf 实际生效，llama-cpp.env / open-webui-models.env 是死代码。这导致 DRY 违反、值不一致、协作盲区。

**建议优先处理 A1 和 A2**：将 first-run-init.sh 接入 entrypoint.sh 主流程，删除或激活 .env 文件，消除配置源分裂。
