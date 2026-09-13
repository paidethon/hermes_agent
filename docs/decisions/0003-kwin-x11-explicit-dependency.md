# 窗口管理器：显式安装 kwin-x11，健康检查必须验证 WM 接管

状态：Accepted（2026-09-13）

## 问题

2026-09-13 线上（魔搭空间，镜像 digest `48811991…`）出现「桌面活着但不可用」：plasmashell 正常、任务栏可见、应用能打开，但窗口没有标题栏，不能拖动、最大化、最小化、关闭。现场证据：`kwin_x11 --replace` 返回 `command not found`（exit 127）——镜像里**根本没有**窗口管理器二进制，不是崩溃，是构建期就缺失。

根因：Ubuntu 24.04 (Noble) 的 `kde-plasma-desktop` 把 `kwin-x11`、`sddm`、`xserver-xorg` 放在 **Recommends** 而非 Depends。Dockerfile 使用 `--no-install-recommends`（这个精简本身是正确的：sddm 和完整 Xorg 在 TigerVNC 架构里确实多余），于是 kwin-x11 被连带跳过。apt 依赖解析不报错，构建与启动都「成功」，直到真的去操作窗口才暴露。

## 为什么三层防线都没拦住

1. **构建期**没有验证关键桌面二进制存在；
2. **启动期** desktop.sh 只等 X server 就绪，不验证会话完整性——起了「半套 Plasma」；
3. **运行期** health.py 的 desktop 探针只做 `pgrep plasmashell`：把「Shell 进程存活」当成了「桌面可用」。这是典型的健康检查假阳性（进程活着 ≠ 功能可用），也是本次事故能通过 `/readyz` 与 Docker HEALTHCHECK 的直接原因。

## 决定

1. **显式声明依赖**：`kwin-x11` 直接写入 apt 安装列表；保持 `--no-install-recommends`，Recommends 里真正需要的组件逐项显式列出，不放开 Recommends（否则 sddm/完整 Xorg 会进镜像）。
2. **构建期 fail-fast**：Dockerfile 末尾验证 `startplasma-x11`/`kwin_x11`/`plasmashell`/`dbus-run-session`/`Xtigervnc`/`xdpyinfo`/`xprop` 存在（`test -x /usr/bin/kwin_x11`），缺失即构建失败。
3. **启动期 preflight**：desktop.sh 在启动 Plasma 前做同样的二进制检查，缺失即 FATAL 非零退出，宁可让 supervisor 重试也不起残缺会话。
4. **运行期探针三分**：health.py 把桌面拆成 `desktop`（plasmashell 进程）、`kwin`（kwin_x11 进程）、`wm`（`xprop -root _NET_SUPPORTING_WM_CHECK`，EWMH 接管证据）三个探针；任一失败 `/readyz` 返回 503。探针内部显式设置 `DISPLAY`/`XAUTHORITY`，不依赖调用方环境。
5. **CI 真实容器门禁**：smoke_container.py 在冷启动与 `docker restart` 后都验证 kwin 进程、root 接管、`_NET_SUPPORTED` 关键原子（`_NET_WM_STATE`、`_NET_WM_STATE_MAXIMIZED_VERT/HORZ`、`_NET_CLOSE_WINDOW`、`_NET_MOVERESIZE_WINDOW`）；并启动真实 X 客户端，验证其进入 `_NET_CLIENT_LIST` 且带非零 `_NET_FRAME_EXTENTS`（被加框 = 标题栏存在的协议级证据）。锁屏/解锁不得杀死 KWin 也进入回归。

## 影响

- 镜像略增大（kwin-x11 及其 Depends）；换取「桌面可管理」这一核心功能保证。
- 未来任何「优化依赖」删掉 kwin-x11 的改动会被三层同时拦截：Dockerfile RUN、单元测试（静态 + 探针逻辑 + `/readyz` 503 负向）、CI 真实容器门禁。
- `plasmashell 存活 ≠ 桌面可用` 成为健康检查的通用判据（见 AGENTS.md 硬约束 11）。
