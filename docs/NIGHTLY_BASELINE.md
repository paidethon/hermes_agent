# Nightly Optimization Baseline（2026-09-14）

> 本次整夜优化的起点快照。只记录后续工作需要引用的事实。

## Git / 部署状态

| 项 | 值 |
|---|---|
| 工作分支起点 | `nightly/systematic-optimization` = `8ff34fc`（origin/fix/kde-kwin-window-manager 尖端，含 PR#6 之后 4 个 CI 测试修复） |
| origin/main | `890087b`（PR#6 merge，落后工作分支 4 个提交，可 fast-forward） |
| 线上镜像 | `ghcr.io/paidethon/hermes_agent@sha256:980ecf6e…` = tag `recovery-890087b` = main 尖端构建 |
| ModelScope 空间 | zephyr17/hermes_agent，master = `4254aaf`，Dockerfile 钉上述 digest |
| 已知线上问题 | 2026-09-14 体检：`/readyz` ready:false（503）三连复测，`/healthz` 200；desktop/kwin/wm 探针失败，kded5 疑持久盘旧配置；处置 = 重部署重置会话 |
| 本地环境 | Windows + Git Bash，**无 docker**；真实容器验证依赖 GitHub Actions（recovery-image 的真实容器门禁） |
| 测试基线 | `python -m unittest discover -s tests` = 40 tests OK（16 个 POSIX 专属在 Windows 跳过） |

## 当前生产架构（唯一真源）

进程链（supervisord，配置由 `recovery/bootstrap.py` 生成到 `/run/zephyr/`）：

```
dbus(root) → auth=Authelia 9091(1002) → vnc=Xtigervnc :1→5901(1001)
  → desktop=startplasma-x11(KWin) → novnc=websockify 6080 → studio=Node 8648
  → health=health.py(9092) → nginx 0.0.0.0:7860（唯一公网端口）
```

- 入口：Nginx 7860；`/healthz`=liveness（无鉴权恒 200）、`/readyz`=readiness（七探针聚合：auth/novnc/studio/vnc/desktop/kwin/wm）。
- 认证：Authelia Cookie（SameSite=None，魔搭 iframe 约束）；VNC 密码；DESKTOP_PASSWORD→/etc/shadow 每次启动重写。
- entrypoint：bootstrap.py 生成配置 → validate → **unset 全部密码/TOKEN** → supervisord。
- 持久化：`DATA_ROOT=/mnt/workspace/zephyr-v2`（auth/home/hermes/studio/work）；锁/socket/生成配置一律 tmpfs。
- 构建：多阶段（node:24 构建 Studio v0.6.39 → ubuntu:24.04 运行时拷 `/usr/local/` 全量）+ Hermes v2026.8.3 venv + Authelia 4.39.25（SHA256 校验）。

## 运行路径 vs legacy（本次核对结论）

| 路径 | 状态 |
|---|---|
| `Dockerfile`、`recovery/*`、`tests/*` | **生产运行路径** |
| `.github/workflows/recovery-image.yml` | 生产 CI（单测→构建→真实容器验收→GHCR 发布） |
| `legacy/`（modelscope/ portal/ config/ 旧 scripts .env.example） | **legacy 归位**（2026-09-14 夜）：原版资产，不参与构建（.dockerignore 只发 Dockerfile + recovery/） |
| `docker-compose.yml` | 已重写为生产镜像本地预演（同一 Dockerfile、/healthz+/readyz、recovery 变量集） |
| `.github/workflows/keepalive.yml` | 仍在运行：每 6h GET status，仅 Stopped 时 POST deploy（无健康/readiness 判断） |
| `docs/`（ARCHITECTURE/DEPLOYMENT/OPERATIONS/decisions/） | PR#5 治理后与代码一致，作为文档真源维护 |

## 本次已识别的问题清单（后续批次逐一处理）

1. compose/legacy 入口漂移（上表）→ 归位 `legacy/` + 重写 compose 为生产镜像预演。
2. KWin 无自愈：supervisor 只在进程退出时重启；「进程在但未接管 root」「X 挂死」无人处理，/readyz 只报病不治病。
3. supervisor 子进程按段继承 supervisord 全量环境（`environment=` 只增不减），OPENAI_API_KEY 等被 nginx/health/novnc 等无谓继承。
4. health.py 缺 X server 探针（xdpyinfo）；/readyz 只回 `{"ready":bool}`，状态页无从展示分项。
5. 无统一诊断命令；无迁移脚本；无数据化性能基线。
6. keepalive 不看健康；无 deploy-modelscope 发布流水线（同步/验收/回滚）。
7. 镜像可减重：runtime 拷贝整个构建阶段 `/usr/local/`（含 npm 等）；build-essential 装入 runtime 层且安装后不清理。

## 硬约束备忘（改架构前核对，源自 AGENTS.md）

单端口 7860；入口禁 Basic Auth；iframe 约束（CSP frame-ancestors + SameSite=None）；持久盘网络文件系统（锁放 tmpfs）；不碰旧 `/mnt/workspace/zephyr`；Secret 零镜像；uid 1001/1002；模型 ID 带前缀；平台 WAF 拦 curl 默认 UA；单容器非隔离沙箱；kwin-x11 必须显式安装 + 七探针。
