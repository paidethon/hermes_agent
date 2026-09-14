# 运维

> 本文回答"怎么检查、怎么验收、怎么备份、常见故障怎么办"。

## 健康检查

```bash
curl -fsS http://127.0.0.1:7860/healthz   # Nginx 活着（无鉴权）
curl -fsS http://127.0.0.1:7860/readyz    # 全部就绪才 200（无鉴权）
python3 /opt/recovery/health.py --once    # 容器内分层健康七项探针
```

`/readyz` 聚合七项探针：`auth`（Authelia）、`novnc`、`studio`、`vnc`（5901 可达）、
`desktop`（plasmashell 进程）、`kwin`（kwin_x11 进程）、`wm`（EWMH root 接管，
`xprop -root _NET_SUPPORTING_WM_CHECK`）。**`plasmashell` 存活 ≠ 桌面可用**：
没有窗口管理器时窗口没有标题栏、不能拖动/最大化/关闭，所以 kwin 与 wm 任一为 false
即 503。探针不测试付费模型调用。容器内桌面终端用不了 `supervisorctl`
（`/run/zephyr/supervisord.conf` 为 root 0600），服务状态一律走 health.py 或 `/readyz`。

## 验收流程

1. **免进容器快验**：浏览器打开应用的 `/readyz`，应返回 `{"ready": true}`；
2. **三层密码实测**：Authelia 表单登录 → VNC 密码进桌面 → 桌面空闲锁屏后用 `DESKTOP_PASSWORD` 解锁；
3. **桌面可管理**：打开 Konsole 等窗口，确认有标题栏，且拖动、最大化、还原、最小化、关闭全部可用；锁屏解锁后与重部署后再各验证一遍（KWin 必须存活，见 ADR 0003）；
4. **容器内功能**：`hermes --help` 正常；`python3 /opt/recovery/model_probe.py` 确认云 API 连通（`--chat` 会真实消耗额度，手工执行）；让 Agent 在 `DATA_ROOT/work` 下写读一个测试文件，验证真实工具执行；
5. **持久化**：文件写入 `/mnt/workspace` 后重部署，确认仍在；重启后浏览器会话、模型配置可恢复。

验收边界（哪些不在保证范围）见 `docs/recovery/VERIFICATION.md`。

## 统一诊断

`bash /opt/recovery/diagnose.sh`（管理员终端 root 运行；`--save` 写入
`DATA_ROOT/diagnostics/diagnose-<时间戳>.txt`，保留最新 10 份）：一次性输出版本标识
（app/hermes/studio commit、镜像构建时间）、healthz/readyz、supervisor 服务状态、
桌面九探针细节（plasmashell/kwin/wm/watchdog 状态）、内存、磁盘、监听端口、
按内存排序的进程表。全部输出经过密钥脱敏（sk-/ghp_/ms-/Bearer 模式替换），
不 dump 任何进程环境。watchdog 自身的修复历史与诊断包也在
`DATA_ROOT/diagnostics/watchdog-*`（同样保留 10 份）。

## 桌面自愈

`recovery/desktop-watchdog.py`（supervisor 程序 `watchdog`，root）处理「活着但坏掉」
的桌面：KWin 死亡/未接管 root → `kwin_x11 --replace` → 仍失败 → 重启整个桌面会话；
X 挂死 → 重启 VNC；冻结（T 态）进程 → SIGCONT；FATAL 程序 → 拉起。每个问题梯级
只走一遍，全局修复预算默认 4 次/30 分钟，超出后只记录不再动手（禁止无限重启）。
预算与宽限可用 `WATCHDOG_BUDGET_MAX` / `WATCHDOG_BUDGET_WINDOW` /
`WATCHDOG_STARTUP_GRACE` / `WATCHDOG_LOOP_SECONDS` 调整（空间 Variables 注入）。

## 旧数据迁移

`bash scripts/migrate-data.sh --dry-run`（宿主或容器管理员终端）：列出旧
`/mnt/workspace/zephyr` 树中可迁移内容；`--apply` 复制到
`DATA_ROOT/import/zephyr-legacy/` 并以 sha256 清单校验。**绝不覆盖/删除任何已有
数据**；幂等可重复；合并进活动目录是最后一步显式手工操作（脚本末尾打印命令）。

## 备份

`bash /opt/recovery/backup.sh`（**必须管理员终端 root 运行**）：

- 会停止桌面/Studio/Auth 并终止用户进程——先保存工作、结束 Agent 任务，备份期间应用不可访问；
- 产出 `DATA_ROOT` 同级的 `recovery-backups/*.tar.gz` + SHA256 校验，打包前停写、打包后验证可读；
- **这不是异地备份**：归档可能含浏览器登录状态与凭据，须用自有加密通道（如 rclone crypt）复制到外部存储，加密密钥保存在空间之外；恢复演练在隔离环境做。

## 常见故障

| 症状 | 原因 / 处理 |
|---|---|
| 窗口无标题栏、不能拖动/最大化/关闭 | 窗口管理器缺失或死亡：`/readyz` 的 `kwin`/`wm` 探针为 false；容器内查 `pgrep -a kwin_x11` 与 `xprop -root _NET_SUPPORTING_WM_CHECK`（需 `DISPLAY=:1 XAUTHORITY=/run/user/1001/.Xauthority`）。watchdog 应在数分钟内自愈（`DATA_ROOT/diagnostics/watchdog-*` 留有诊断）；若反复复发，把诊断包交给维护者——镜像层修复见 ADR 0003，不要用运行时 apt install 兜底 |
| 登录后又弹回登录页 | `PUBLIC_ORIGIN` 与实际域名不一致，或 Cookie 的 Secure/Domain/Set-Cookie 被入口改写；不要回退 Basic Auth |
| noVNC 打开但连不上 | 浏览器 Network 查 `/desktop/websockify` 是否 101、Origin 是否正确，再查 5901 与桌面进程 |
| Auth/桌面目录 permission denied | 用管理员终端核对挂载属主与 uid 写权限；不要盲目 chmod 777，也不要把整套服务切到 root |
| Chrome 报 No usable sandbox | 默认保留沙箱；`CHROME_NO_SANDBOX=1` 是显式风险开关，仅用于受控的本机 Studio 页面 |
| Studio 打开但回答失败 | 查 Agent 安装路径、模型配置与供应商响应；Nginx 200 不代表 Agent 健康 |
| 改了 Secret 密码没变 | 环境变量只在容器创建时注入 → 必须重部署（见 DEPLOYMENT） |
| 容器启动即退出 | 核对必填 Secret：`AUTH_PASSWORD` ≥16 字符、`VNC_PASSWORD` 8-64 可打印 ASCII、`DESKTOP_PASSWORD` 已配置 |
| 锁屏进不去 | 输入 `DESKTOP_PASSWORD` 解锁；彻底死锁则重部署重置会话 |
| TigerVNC 连续认证失败 | 触发黑名单约 2 小时；重试要克制 |
| 云模型 HTTP 400 | 模型 ID 必须带前缀（如 `Qwen/Qwen3-235B-A22B`） |
| 构建失败 | 保留第一处失败命令与版本信息；不要以删除测试的方式绕过 |

## 扩展边界

给恢复版加回服务（聊天前端、工作流引擎、本地推理）时的边界：

- 每个服务需要独立依赖环境、数据目录、版本与验收；直接把 `/xxx/` 前缀从请求里剥掉**不会**改写前端硬编码的绝对路径与 WebSocket；
- 公网暴露前实测该版本的 base path、认证与平台请求头限制；
- 本地推理先独立评估 CPU/内存/量化/速度；平台休眠与回收政策决定能否承载 24/7 任务；
- 无法适配平台限制的服务更适合放在自有 VPS 的 HTTPS 入口之后。
