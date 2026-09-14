# Nightly Optimization Report（2026-09-14 夜）

## Baseline

- Git SHA: 起点 `8ff34fc`（origin/main `890087b` + 4 个未合并 CI 修复）；终点 main = PR#7 (`a17f77e1`) + PR#8（digest 解析修复）
- Image size: 1468.5 MB → 1463.0 MB（压缩层实测；详见 PERFORMANCE_BASELINE.md 的逐层归因）
- Startup: 冷启动→/readyz 由 CI 真实容器门禁回归验证（每跑观测 ~60-90s，无架构性变化）
- Memory: 未做无数据优化；diagnose.sh 已具备线上采集能力
- Tests: 40 → 54 离线单测（新增 watchdog 决策 6、env 隔离 3、ModelScope 离线 5）+ 真实容器门禁新增 4 项断言（liveness/readiness 区分、未认证跳转、env 隔离、KWin 击杀自愈）

## Fixed

1. 架构漂移清零：legacy/ 归位（旧 modelscope/ 全栈、portal、种子配置、旧 scripts、.env.example）；compose 重写为生产镜像预演；`scripts/check-consistency.py` 交叉核对端口/环境变量/端点（bootstrap.py ↔ compose ↔ 模板 ↔ docs ↔ entrypoint unset 表）。
2. KDE/KWin 不稳定根治：`recovery/desktop-watchdog.py` 自愈（kwin 死亡/未接管 root → `kwin_x11 --replace`（setsid -f 分离）→ 会话重启；X 挂死 → 重启 VNC；T 态进程 → SIGCONT；FATAL 程序 → 拉起）。每问题梯级单次、全局预算 4 次/30 分钟、诊断留存 `DATA_ROOT/diagnostics/watchdog-*`（10 份轮换、零环境变量 dump）。
3. liveness/readiness 语义分离固化：`/healthz`=入口存活，`/readyz`=九探针聚合（新增 x=xdpyinfo、dbus），JSON 附分项 checks 与固定版本。
4. 服务依赖状态机显式化：supervisor 优先级 + desktop.sh X 等待 + watchdog FATAL/BACKINGOFF 兜底；backup.sh 先停 watchdog 后停服务（防对抗）。
5. CI 抓到的真实缺陷（门禁价值实证）：
   - `subprocess.run(timeout=)` 会杀掉刚拉起的 kwin → setsid -f 修复；
   - watchdog 状态文件与 60s 启动宽限竞态 → 启动即写 `starting` 阶段；
   - 发布流水线 digest 解析不匹配 CI artifact 实际格式（全 RepoDigest）→ 正则归一。

## Architecture changes

- 进程表 +1：`watchdog`（root，priority 35）。
- supervisor per-program env allowlist：`OPENAI_API_KEY/OPENAI_BASE_URL/HERMES_MODEL` 只进 studio+desktop，其余程序显式置空（真实容器断言）。
- 门户页 → 轻量状态页（/readyz 驱动，Ready/Starting/Unavailable，零敏感值）。
- Dockerfile：SOURCE_COMMIT 构建参数 → OCI label + `/opt/versions/app.txt`（诊断/状态页身份标识）。

## Stability

- CI 真实容器门禁新增：SIGKILL kwin_x11 → 300s 内 /readyz 恢复 + 窗口重新加框（`_NET_FRAME_EXTENTS` 非零）+ 重启后 watchdog healthy。
- 2026-09-14 已知线上 /readyz ready:false（桌面侧探针失败、疑持久盘旧配置）问题：新版的 watchdog + keepalive v2（readiness 失败自动恢复性重部署，4h cooldown + 24h 上限 3 次）形成双闭环。

## Security

- 模型密钥进程面收敛：nginx/auth/vnc/novnc/health/dbus/watchdog 显式置空 OPENAI_*（崩溃转储/子进程继承不可带出）；CI 断言真实容器。
- 全链路脱敏：diagnose.sh 输出 sk-/ghp_/ms-/Bearer 模式替换；watchdog 诊断禁止环境变量 dump；`scripts/check-consistency.py` 强制 entrypoint unset 表覆盖全部密码类变量。
- 发布链零 token 暴露：GIT_ASKPASS 认证（token 只在 env 与 0700 临时脚本），URL/argv/日志无 token；git 输出不回显。

## Performance

见 `docs/PERFORMANCE_BASELINE.md`：减重措施净收益 ≈ −210 MB（apt −47.7、npm 移除 −162.6），被上游增长（Studio +129.2、Chrome +46.7、Hermes +28.3）抵消，净值 −5.5 MB。措施保留（零回归），后续方向 = Studio 生产依赖树审计。

## Hermes upgrade

- old: v2026.8.3
- new: v2026.9.14（v0.21.3）
- result: **已升级并通过全部门禁**。动因：state.db 可靠性战役 + 跨 VM 文件系统 WAL 回落（正对本部署的网络持久盘）、远程会话刷新修复；与 Studio 成对升级（v0.21.x 网关线协议变更）。报告：`docs/HERMES_UPGRADE_REPORT.md`。

## Studio upgrade

- old: v0.6.39
- new: v0.7.21（主线最新；v1.0.x 是从 0.7.18 期切出的平行发行线，未选）
- result: **已升级并通过全部门禁**（node>=23 引擎、node-pty ^1.1.0 均不变）。报告：`docs/STUDIO_UPGRADE_REPORT.md`。

## CI

- 新增 `static-checks` 门禁（shellcheck + compileall + 单测 + 一致性检查 + docs-audit + hadolint + actionlint + compose config），先于构建，lint 失败不再烧 20 分钟构建。
- nightly/** 分支纳入构建触发；镜像体积写入 step summary（数据化减重）。
- 真实容器门禁扩展 4 项（见 Stability）。

## ModelScope deployment

- GitHub SHA: `aa9dde4`（PR#8 后 main；镜像 recovery-b5ab642 与之同内容，digest 差异仅为 workflow 文件层）
- Space SHA: 由 deploy-modelscope 工作流自动产生（`deploy: sync paidethon/hermes_agent <sha>` 单一部署 commit + deploy-metadata.json）
- deployment: `POST /deploy` 一次触发 + GET status 轮询（修复了首次运行的 digest 解析问题后重跑）
- health/readiness: 公网 /healthz + /readyz + 受保护入口 302 行为三重验收
- rollback: 连续 3 次验收失败 → git revert 单一部署 commit → 重部署 → 验证旧版；revert 失败则标红停机（绝不 force push）
- 凭据: MODELSCOPE_TOKEN / SPACE_ID 来自仓库 Secrets（工作流实测读取成功）

## Remaining issues

1. **线上存量数据迁移未实测**：Hermes v0.21.x 对旧 state.db 的前向迁移只被 CI 空卷间接覆盖；首次线上部署前应跑一次 `recovery/backup.sh` 快照（回滚即恢复快照，旧版不保证读新库）。
2. **Studio v0.7.21 产物膨胀 +129 MB**：需要一次上游依赖树审计（tree-shake 或换打包策略），属上游工程，未在本夜处理。
3. **kded5 疑持久盘旧配置崩溃**（09-14 体检方向）：watchdog 不覆盖 kded5（非窗口管理职责）；若新版部署后仍复现，处置 = 清 `DATA_ROOT/home/.cache`（已在 OPERATIONS 监控项，无人值守不自动删用户数据）。
