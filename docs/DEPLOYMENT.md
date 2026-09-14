# 部署

> 本文回答"怎么部署、怎么换密码、怎么回滚"。变量定义的真源是 `.env.recovery.example`；校验规则在 `recovery/bootstrap.py`。

## 部署链路

```
push main 或 push recovery/modelscope-cookie-auth（触及 Dockerfile / recovery/ / tests/ / workflow 自身）
  或手动 workflow_dispatch（任意分支）
  → GitHub Actions recovery-image 工作流：
      单元测试 + Nginx 集成测试 → 构建候选镜像（不发布）
      → tests/smoke_container.py 真实容器验收（登录/桌面/Studio/窗口管理器/锁屏/持久化哨兵）
      → 验收通过才发布 GHCR → 生成部署文件（digest 固定 Dockerfile）
  → 魔搭空间仓库（master）只含 2 行 Dockerfile：FROM ghcr.io/…@sha256:<digest>
  → 平台拉取镜像部署（平台侧不构建）
```

两个分支都在 push 触发列表里：recovery 分支是历史发布分支，main 是集成分支——两者任一触及运行时路径都会构建发布，杜绝「代码已合 main 但生产镜像没更新」的漂移。文档类改动（不含上述路径）不触发构建。

验收失败时工作流不发布镜像、不产出部署文件；不要跳过门禁强行发布。

## 空间配置

**Variables / Secrets 一律在魔搭 Space 设置页配置，不得写入 Dockerfile、构建参数或仓库。**

| 变量 | 必填 | 规则（bootstrap.py 校验） |
|---|---|---|
| `PUBLIC_ORIGIN` | ✅ | 实际应用的 HTTPS 源地址，仅 origin、无路径/凭据/查询串；不要从空间标识猜测域名 |
| `DATA_ROOT` | 默认 | `/mnt/workspace` 下的单层目录名；保持 `zephyr-v2`，不要指回旧 `zephyr` |
| `AUTH_USERNAME` | 默认 `zephyr` | 小写标识符，1-32 字符 |
| `AUTH_PASSWORD` | 首启必填 | 16-256 字符，无控制字符；仅存 argon2 哈希 |
| `VNC_PASSWORD` | 首启必填 | 8-64 可打印 ASCII；协议只取前 8 位；不要与其他密码相同 |
| `DESKTOP_PASSWORD` | ✅ | 8-256 字符，无控制字符；每次启动重写，用于解锁 KDE 锁屏 |
| `OPENAI_BASE_URL` | 可选 | OpenAI 兼容 HTTPS 端点 |
| `OPENAI_API_KEY` | 可选 | 对应供应商密钥；未配置时界面就绪但 Agent 无法回答 |
| `HERMES_MODEL` | 可选 | 完整模型 ID，必须带前缀（如 `Qwen/Qwen3-235B-A22B`） |
| `CHROME_NO_SANDBOX` | 默认 0 | 仅在确认平台阻止 Chrome 沙箱且接受风险时设 1 |

模型配置只在首次启动（无现存 config.yaml）时初始化；已有配置优先，切换模型用 `hermes model`，不要靠改 `HERMES_MODEL` 强行覆盖。

GitHub Actions 侧需要 `MODELSCOPE_TOKEN` / `SPACE_ID` 两个 Secrets，供发布流水线与 keepalive 使用；token 只经 `GIT_ASKPASS`/请求头进入请求，绝不写入 URL 或日志。

## 自动发布流水线（deploy-modelscope）

```
push main（触及运行时路径）
  → recovery-image：静态检查 → 单测 → 构建候选镜像 → 真实容器门禁 → 发布 GHCR
  → deploy-modelscope（workflow_run 自动接续，仅 main、仅构建成功时）：
      下载该次运行的 deployment artifact
      → 空间仓库产生且仅产生一个部署 commit（digest 固定 Dockerfile + deploy-metadata.json）
      → POST /deploy 触发一次（不用它轮询——那是重启型接口）
      → GET status 轮询 Building→Running（无副作用）
      → 公网 /healthz + /readyz + 受保护入口行为三重验收
      → 连续 3 次验收失败：git revert 该部署 commit → 重新部署 → 验证旧版恢复
      → revert 也失败：停止自动操作，工作流标红，输出需人工介入的原因
```

发布 commit 形如 `deploy: sync paidethon/hermes_agent <github-sha>`；`deploy-metadata.json`
记录 GitHub SHA、镜像 digest、Hermes/Studio 版本钉与构建时间（无任何 Secret）。
平台 master 有分支保护：流水线只做正常 commit + revert，**绝不 force push**。

## Keepalive（每 6 小时）

判断不再是单一平台状态，而是「平台状态 + HTTP 健康 + readiness」：

| 观测 | 动作 |
|---|---|
| Running + `/readyz` 200 | 不干预 |
| Stopped | deploy（重试上限 3） |
| Running + readiness 连续 3 次失败 | 恢复性 deploy 一次：4 小时 cooldown + 24 小时上限 3 次（状态经 actions/cache 传递） |
| Building / Deploying | 不干预 |

readiness 探针即线上九探针聚合，因此桌面侧故障（kwin/kded5 类）与空间停止走同一条自动恢复路径。

## 密码轮换（不重建镜像）

三个密码全部由环境变量注入、容器启动时写入生效位置：

1. 更新空间 Secret（新 key 必须先创建再更新——`PUT` 无 upsert 语义）；
2. 触发重部署（推送空间仓库或平台 deploy 接口）——**只改 Secret 不重部署不生效**，环境变量仅在容器创建时注入；
3. 等 Running 后实测登录。

重部署会重置桌面会话（锁屏死锁的兜底手段）。只有改 `bootstrap.py` 等代码/模板才需要走 CI 重建镜像。

## 首次部署清单

1. Fork/推送本仓库，确认 `recovery-image` 工作流全绿；
2. 从工作流 artifact `modelscope-deployment` 取真正生成的 `Dockerfile`（digest 固定），不要手抄文档中的占位 digest；
3. 首次发布检查 GHCR 包可匿名拉取（仓库公开 ≠ 镜像公开）；若平台构建网络不可达 GHCR，将镜像复制到自有阿里云仓库并使用**该仓库实际生成的 digest**（跨仓库 manifest digest 不同）；
4. 建议先建测试空间验证；用原空间则先备份旧数据与旧 Dockerfile；
5. 空间仓库替换根 Dockerfile 为 digest 固定版，不追加 CMD/ENTRYPOINT；通过网页提交可避免 GitHub/魔搭分支混淆；
6. 配置 Variables/Secrets → 部署 → 按 `docs/OPERATIONS.md` 验收。

## 回滚

把空间仓库的 Dockerfile 换回记录的原镜像 digest（或原 Dockerfile）并重部署。新旧环境使用不同数据目录，回滚不自动删除新数据；迁移后产生的新数据要先导出——旧版本不保证能读新数据库。
