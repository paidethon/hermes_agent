# Agent Guide

容器化 AI 桌面（KDE + Hermes Agent + Studio），部署于魔搭 Docker Space，单端口 7860，Authelia Cookie 认证。架构与部署细节见 `docs/`。

## 开始工作

1. `git status` 确认干净；
2. 按下方地图只读本次任务需要的文档；
3. 修改行为前先读对应实现（`recovery/bootstrap.py` 是运行时配置的机器真源）；
4. 改完运行 `python -m unittest discover -s tests -v` 和 `python scripts/docs-audit.py`。

## 文档地图

| 任务 | 读 | 不要读 |
|---|---|---|
| 改服务/端口/路由/持久化 | `docs/ARCHITECTURE.md` → `recovery/bootstrap.py` | `docs/archive/` |
| 改部署/CI/Secrets | `docs/DEPLOYMENT.md` → `.github/workflows/recovery-image.yml` | `docs/archive/` |
| 排障/健康/备份 | `docs/OPERATIONS.md` → `recovery/health.py` | `docs/archive/` |
| 理解"为什么这样设计" | `docs/decisions/` | — |
| 新增环境变量 | `.env.recovery.example`（真源）+ `recovery/bootstrap.py`（校验规则） | 不要在 README 重复全表 |

**遗留目录**（当前镜像不使用，勿在其中改动后误以为生效）：`legacy/`（原版全量架构：`modelscope/`、`portal/`、`config/`、旧 scripts、`.env.example`）、`docs/archive/`。

## 硬约束（改架构前逐条核对）

1. **单端口**：魔搭 Docker Space 只暴露 7860；8080 被平台占用。新增服务一律挂到 Nginx 子路径之后。
2. **入口不能用 Basic Auth**：平台对入口请求的 Authorization 头与跨站 iframe 会话冲突（历史 401 根因）。入口认证只能用 Cookie 会话（Authelia）。容器向模型供应商发出的出站请求不受此限制。
3. **iframe 入口**：浏览器入口是魔搭空间页的 iframe——禁止 `X-Frame-Options: DENY`，须 CSP `frame-ancestors` 允许 modelscope.cn；会话 Cookie 必须 `SameSite=None; Secure`。
4. **持久盘是网络文件系统**：`/mnt/workspace` 上文件锁会超时（xauth 教训）。锁文件、socket、运行时配置一律放 tmpfs（`/run/zephyr`、`/run/user/1001`）。
5. **数据目录**：`DATA_ROOT=/mnt/workspace/zephyr-v2`。旧目录 `/mnt/workspace/zephyr` 属于原版部署，任何代码不得写入或删除。
6. **Secret 零镜像**：所有密码/密钥运行时经环境变量注入，镜像与仓库不得含真实值；改密码 = 改空间 Secret + 重部署，不需要重建镜像。
7. **运行用户**：Hermes/桌面 uid 1001（hermes），Authelia uid 1002（zephyr-auth）；上游 Hermes 拒绝以 root 运行。supervisord 配置在 `/run/zephyr/`（root 0600），容器内桌面终端用不了 `supervisorctl`，服务状态走 `health.py` 或 `/readyz`。
8. **模型 ID 必须带前缀**：如 `Qwen/Qwen3-235B-A22B`，缺前缀 HTTP 400。
9. **平台 WAF** 拦截默认 curl UA，脚本探活须带浏览器 UA。
10. **单容器不是隔离沙箱**：不要在其中保存无关高权限凭据，不要假设容器间强隔离。
11. **桌面三道防线**：`kwin-x11` 必须显式安装（Noble 把它放在 `kde-plasma-desktop` 的 Recommends，`--no-install-recommends` 会静默漏掉）；健康检查不能只看进程存活——**plasmashell 存活 ≠ 桌面可用**，`/readyz` 必须验证 kwin 进程与 EWMH root 接管；真实容器门禁会验证窗口确实被加框（见 ADR 0003）。

## 完成定义

- 单元测试通过（`python -m unittest discover -s tests -v`）；
- 变更涉及的事实在唯一真源更新（配置值改机器配置，不复制进多个 Markdown）；
- `python scripts/docs-audit.py` 无新增断链；
- 不引入真实 Secret（文件名、内容、commit message 均不得出现）。
