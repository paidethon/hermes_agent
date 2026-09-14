# Hermes 上游升级调查（2026-09-14）

## 结论

| 项 | 值 |
|---|---|
| 当前钉版 | `v2026.8.3`（v0.20.x 线） |
| 最新稳定 | `v2026.9.14`（v0.21.3，2026-09-14 发布） |
| 建议 | **升级，但与 Studio v0.7.21 成对升级**（线协议配套），并在部署前做数据快照 |
| 验证方式 | Docker 构建 + 真实容器门禁（tests/smoke_container.py，含 hermes CLI/Studio/桌面全链路） |

## 版本间隔（v2026.8.3 → v2026.9.14 共 5 个 tag）

| 版本 | 日期 | 性质 |
|---|---|---|
| v2026.8.27 (v0.20.6) | 08-27 | patch，~525 PR |
| v2026.8.31 (v0.21.0) | 08-31 | **大版本 "Pantheon"**：Bot Mode、`hermes peer`、cron 持久记忆、MCP 命令中心、6 新供应商、**保护性写审批（AGENTS.md/记忆/技能防提示注入改写）与深度密钥脱敏清扫** |
| v2026.9.7 (v0.21.1) | 09-07 | patch：代码库模块化重构（5,139 commits）、文件操作与启动性能 |
| v2026.9.11 (v0.21.2) | 09-11 | **state.db 可靠性战役**（六个 PR 修根因）：第二写者消除、WAL 卡死、FTS 损伤降级、坏行容忍、跨 profile 隔离 |
| v2026.9.14 (v0.21.3) | 09-14 | **远程桌面/网关会话修复**（刷新风暴不再吊销会话）、长进程重复 state.db 写句柄泄漏修复、**跨 VM 文件系统拒绝 WAL**（自动回落） |

## 与本部署的关联（按风险排序）

1. **state.db × 网络持久盘（直接相关）**：`HERMES_HOME` 在 `/mnt/workspace`（跨 VM 网络文件系统）。v0.21.2 修的正是「多写者/锁取消导致 state.db 损坏」一类问题；v0.21.3 在跨 VM 文件系统上拒绝 WAL 并回落。**升级对该环境是净收益，但存量 state.db 的前向迁移无法在 CI 的空数据卷里验证** → 部署前必须 `recovery/backup.sh` 快照；降级路径 = 恢复快照（旧版不保证读新版库，见 DEPLOYMENT 回滚节）。
2. **Desktop 网关线协议变更**：v0.21.3 窗口引入 server→client JSON-RPC 与 Pydantic wire-contract registry（生成 TS 契约）。旧 Studio v0.6.39 的 Python agent bridge 存在协议错位风险 → **Hermes 不单独升，与 Studio 成对升**。
3. **Python 依赖**：模块化重构后 venv 安装面变化；构建期 `pip check` + `hermes --help` + 容器门禁里的 Studio bridge 启动即为回归判据。
4. **config.yaml 兼容**：发行说明无自定义 provider（`provider: custom` + `base_url`）破坏性变更记载；`HERMES_MODEL`/`OPENAI_BASE_URL` 注入方式不变。模型 ID 规则（带前缀）不变。
5. **安全净收益**：AGENTS.md 等受保护文件写审批、终端错误/.env 读取/checkpoint 的脱敏清扫——与本项目「Secret 不入日志」目标一致。
6. 行为变化：默认 reasoning 选择器、受保护文件写审批会改变桌面内交互（多一步确认），非故障。

## 升级步骤（本次执行）

1. `ARG HERMES_REF=v2026.9.14`（与 `ARG STUDIO_REF=v0.7.21` 同一提交）；
2. 推分支 → CI 静态检查 + 构建 + 真实容器门禁全绿才保留；
3. 门禁红线 → 先回退到 Studio v0.7.21 + Hermes v2026.8.3 组合再试；仍红 → 双双回退，保留本报告；
4. 部署前线上快照（backup.sh），部署后按 OPERATIONS 验收（登录/VNC/hermes 实测问答/工具执行）。
