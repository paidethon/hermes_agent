# 架构

> 本文回答"现在是什么"。机器真源：`Dockerfile`（构建）、`recovery/bootstrap.py`（运行时配置生成）。历史与原因见 `docs/decisions/`。

## 总览

```
浏览器
  └→ 魔搭空间页（iframe，CSP frame-ancestors 允许 modelscope.cn）
       └→ 容器 :7860  Nginx（唯一公网端口）
            ├─ /auth/    → Authelia（Cookie 登录）
            ├─ /         → 受保护入口页
            ├─ /desktop/ → noVNC → TigerVNC → KDE Plasma
            │               └─ 桌面 Chrome → 127.0.0.1:8648（Hermes Studio）
            │                               └─ Hermes Agent → 云模型 API（出站）
            └─ /readyz /healthz → 健康检查（免认证）

supervisord（root）编排 8 个进程；配置生成到 /run/zephyr/（tmpfs）
持久化：/mnt/workspace/zephyr-v2/（平台网络持久盘）
```

## 进程表（supervisord，由 bootstrap.py 生成）

| 进程 | 运行用户 | 监听 | 优先级 | 说明 |
|---|---|---|---|---|
| dbus | root | — | 5 | 系统总线 |
| auth | zephyr-auth (1002) | 127.0.0.1:9091 | 10 | Authelia 4.39，Cookie 会话认证 |
| vnc | hermes (1001) | 127.0.0.1:5901 | 20 | Xtigervnc `:1`，VncAuth，`-nolisten tcp` |
| desktop | hermes | — | 30 | KDE Plasma 会话（desktop.sh：preflight 校验 + `startplasma-x11`；KWin 为窗口管理器） |
| watchdog | root | — | 35 | `desktop-watchdog.py`：桌面自愈（KWin 替换→会话重启梯级，修复预算上限，诊断留存） |
| novnc | hermes | 127.0.0.1:6080 | 40 | websockify，`/desktop/websockify` 校验 Origin |
| studio | hermes | 127.0.0.1:8648 | 50 | Hermes Studio（Node 24，`dist/server/index.js`） |
| health | hermes | 127.0.0.1:9092 | 60 | health.py 常驻，对外暴露 `/readyz` |
| nginx | root | **0.0.0.0:7860** | 70 | 唯一入口 |

Hermes Agent 本体（venv `/opt/hermes-venv`，`hermes` CLI）不在路由表中；Studio 通过 Python agent bridge（IPC）连接 Agent，不占端口。原版架构中的 Gateway API（8642）在恢复版中不启用。

## Nginx 路由

| 路径 | 行为 | 认证 |
|---|---|---|
| `/healthz` | 返回 `alive`（**liveness**：入口进程活着） | 无 |
| `/readyz` | 转发到 health 服务（**readiness**：用户真的可用），JSON 含 `checks` 九探针与 `versions` 固定版本 | 无 |
| `/auth/` | Authelia 登录门户 | 无（本身即认证） |
| `/` | 受保护入口页（状态徽章 + 提示桌面内打开 Studio） | Authelia |
| `/desktop/`、`/desktop/websockify` | noVNC（WebSocket 校验 Origin） | Authelia |
| 其余 | 404 | — |

内部端口（9091/9092/6080/5901/8648）均不在路由表中，公网不可达。

## 九探针 readiness

`/readyz` 聚合九项，任一为 false 即 503：`auth`（Authelia）、`novnc`、`studio`、
`vnc`（5901 TCP）、`x`（xdpyinfo，X 服务器真的响应协议）、`dbus`（会话总线进程）、
`desktop`（plasmashell）、`kwin`（kwin_x11）、`wm`（EWMH root 接管）。
进程级存活探不出的故障由 `x`/`wm` 兜底：X 挂死时进程都在但无人能画；
WM 死了窗口没有标题栏。

## 桌面自愈（watchdog）

supervisord 只重启「退出」的进程；watchdog（`recovery/desktop-watchdog.py`，root）
处理「活着但坏掉」的状态：KWin 死亡/未接管 root、X 挂死、T（冻结）态进程、
FATAL 程序。修复梯级每个 issue 最多走一遍：`kwin_x11 --replace`（会话内）→
`supervisorctl restart desktop`（整会话）→ 之后只写诊断不再动手。全局修复预算
（默认 4 次/30 分钟滚动窗口）防无限重启；诊断包（进程表/X 属性/会话变量/dbus/端口，
无任何环境变量全量 dump）存 `DATA_ROOT/diagnostics/watchdog-*`，保留最新 10 份。
状态文件 `/run/zephyr/watchdog-status.json`（tmpfs，无敏感值）。

## 进程环境隔离

supervisor 子进程默认按段继承 supervisord 全量环境。恢复版改为 per-service
allowlist：`OPENAI_API_KEY`/`OPENAI_BASE_URL`/`HERMES_MODEL` 只进入消费者
（studio、desktop 会话），其余程序（nginx/auth/vnc/novnc/health/dbus/watchdog）
在配置里显式置空——任何服务崩溃转储或子进程继承都不可能带出模型密钥。
三套密码在 entrypoint 启动服务前已 unset。

## 认证链

密码层（2026-09-15 起 VNC 层并入 Authelia 门，见 ADR 0005）：

| 层 | 验证什么 | 存储位置 | 注入方式 |
|---|---|---|---|
| AUTH | 网页登录（Authelia Cookie） | `DATA_ROOT/auth/users.yml`（argon2 哈希，uid 1002 私有） | 环境变量 `AUTH_PASSWORD`，启动时与存量哈希比对，不一致才重写 |
| VNC | ~~桌面连接~~ 已并入第二道门（2026-09-15） | —（`VNC_PASSWORD` 保留但不再消费） | 回环 VNC 改 `SecurityTypes None`（仅 127.0.0.1，浏览器路径由 Authelia 把守），见 ADR 0005 |
| 桌面锁屏 | 会话内解锁 | `/etc/shadow`（容器可写层，不持久） | 环境变量 `DESKTOP_PASSWORD`，每次启动 `chpasswd` 写入 |

会话 Cookie：`Secure` + `SameSite=None`（适配魔搭 iframe 嵌入）；30 分钟不活动过期、12 小时绝对过期。

entrypoint 在生成配置后、启动服务前 `unset` 全部密码环境变量，密码不进入服务进程环境。

## 数据与持久化

```
/mnt/workspace/zephyr-v2/        DATA_ROOT（平台持久盘，网络文件系统）
├── auth/      Authelia 哈希、密钥、数据库（uid 1002）
├── home/      KDE、Chrome、用户配置（/home/hermes 软链至此，uid 1001）
├── hermes/    Hermes 配置与会话（HERMES_HOME 软链至此）
├── studio/    Studio 状态
└── work/      用户工作文件
```

- 锁文件、socket、运行时生成配置放 tmpfs（`/run/zephyr/`、`/run/user/1001/`），不放持久盘（网络文件系统文件锁会超时）。
- 旧目录 `/mnt/workspace/zephyr/` 属于原版部署，本实现不读写。

## 配置生成流程（bootstrap.py）

1. 校验环境变量（`PUBLIC_ORIGIN` 必须 HTTPS、`DATA_ROOT` 必须 `/mnt/workspace` 下单层目录且无 symlink 逃逸、密码长度/字符集规则）；
2. 创建 `DATA_ROOT` 子目录并设置属主/权限；
3. 写入密码生效位置（argon2 / vncpasswd / chpasswd）；
4. 渲染 Authelia、Nginx、supervisord 配置到 `/run/zephyr/`（0600）；
5. entrypoint 校验配置（`authelia validate-config`、`nginx -t`）后交给 supervisord。

## 构建与版本固定

多阶段 `Dockerfile`：Studio 构建（Node 24，`v0.6.39`）→ Ubuntu 24.04 运行时（KDE + TigerVNC + noVNC + Nginx + Authelia 4.39.25）→ Hermes Agent 独立 venv（`v2026.8.3`，装在最终路径并在 `/tmp` 验证可导入）。依赖版本由 `ARG` 固定，Authelia 下载带 SHA256 校验。KDE 安装保持 `--no-install-recommends`，窗口管理器 `kwin-x11` 必须显式列出（Noble 把它放在 Recommends，见 [ADR 0003](decisions/0003-kwin-x11-explicit-dependency.md)）；构建末尾 fail-fast 验证桌面关键二进制存在。

## 明确不包含（相对原版）

Open WebUI、Flowise、llama.cpp 本地推理、模型自动下载、消息渠道 Gateway 均不在恢复版镜像中。原版实现保留在 `legacy/` 目录（遗留，不参与当前构建）与 git 历史。扩展方式见 `docs/OPERATIONS.md` 末节。
