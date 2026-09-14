# Hermes Studio 上游升级调查（2026-09-14）

## 结论

| 项 | 值 |
|---|---|
| 当前钉版 | `v0.6.39` |
| 主线最新稳定 | **`v0.7.21`**（2026-09-12；main 线 tag） |
| 另一条发行线 | `v1.0.0–v1.0.3`（09-06～09-10，"HStudio" 命名；package.json version 仍标 0.7.18，是从 0.7.18 期代码切出的发行线，**不是 main 尖端**） |
| 建议 | 升级到 **v0.7.21**（不选 v1.0.x：主线更晚、包含 0.7.19–0.7.21 修复） |
| Node 兼容 | v0.6.39 与 v0.7.21/v1.0.3 的 `engines` 均为 `node >=23`；构建镜像 `node:24-bookworm-slim` 满足 |
| node-pty | v0.6.39 与 v1.0.3 处均为 `^1.1.0`，`npm rebuild node-pty` 流程不变 |

## v0.6.39 → v0.7.21 期间与本部署相关的变化

- **与 Hermes 网关/bridge 配套演进**（同仓_org 随 Hermes 主线联动）：升级 Hermes agent 必须同步升级 Studio，否则 Python bridge/IPC 存在协议错位风险（见 HERMES_UPGRADE_REPORT.md 第 2 条）。
- 近期修复主题（git log）：coding agent PATH 与缺失可执行文件处理（#3044）、DSH 插件 manifest 版本声明（#3038）、**Studio 管理的 Claude OAuth 修复**（#3033）、Ekko MCP HTTP transport 别名归一（#3031）、Chat 工具结果配对修复（#3030）、Windows DSH 启动修复（#3026）。
- 与本环境相关的部署事实不变：`NODE_ENV=production PORT=8648 BIND_HOST=127.0.0.1`、`HERMES_WEB_UI_HOME`（持久盘 `DATA_ROOT/studio`）、`HERMES_BIN=/opt/hermes-venv/bin/hermes`、`HERMES_WEB_UI_DISABLE_GATEWAY_AUTOSTART=1`（recovery/studio.sh 注入）。**Studio 侧改动为纯升版本钉，无脚本变化。**

## 风险与验证

1. **Studio 状态目录迁移**：`DATA_ROOT/studio` 由旧版写入，v0.7.21 格式兼容性未在空卷 CI 中覆盖 → 与 Hermes 升级共用「部署前快照」缓解。
2. **登录/会话**：Studio 仅桌面内 loopback 访问，无公网面；CI 门禁验证 HTTP 200 + 桌面内可达。
3. **构建失败不得硬合并**：CI 门禁红线 → 回退 Studio 钉版（保留 Hermes 调查结论），不阻塞其余工作。

## 升级步骤（本次执行）

1. `ARG STUDIO_REF=v0.7.21`（与 `ARG HERMES_REF=v2026.9.14` 同一提交）；
2. CI 构建（`npm ci --ignore-scripts` → `npm rebuild node-pty` → `npm run build` → `npm prune --omit=dev` → `dist/server/index.js` 存在性断言）+ 容器门禁全绿才保留；
3. 红线 → 依 HERMES_UPGRADE_REPORT 第 3 条的组合降级矩阵处理。
