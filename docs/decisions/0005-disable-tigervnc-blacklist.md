# ADR 0005：回环 VNC 关闭认证（SecurityTypes None）

日期：2026-09-15 · 状态：已实施（取代同日早先的 `-BlacklistThreshold=0` 尝试）

## 背景

所有浏览器到桌面的连接都经 websockify 中转，源地址恒为 `127.0.0.1`。
2026-09-15 实测：几次错误密码后，TigerVNC 对 `127.0.0.1` 全体连接在安全
协商阶段直接回类型 0 + `Too many security failures`——**正确密码也被拒**，
noVNC 呈现「无法连接到服务器」，且每次连接尝试都会延长拉黑。先尝试的
`-BlacklistThreshold=0` 在 Xtigervnc（Noble）上未能阻止该拒绝（新 pod 数分钟内
复发，命令行确认已带该参数）。

## 决策

回环 VNC 使用 `-SecurityTypes None`：

- 5901 只绑 `127.0.0.1`（`-localhost=1` + `-nolisten tcp`），容器外不可达；
- 浏览器路径的认证由 **魔搭平台登录 → Authelia 会话（nginx 强制）** 承担；
- 无认证即无「安全失败」概念，黑名单类锁死从机制上不可能再发生；
- 副产品：用户少输一次 VNC 密码，直连 5901 的残余风险仅剩容器内
  uid 1001 自身进程（等价于已拥有桌面）。

`VNC_PASSWORD` Secret 与 `.vnc/passwd` 写入流程暂时保留（不再被 VNC 进程
消费），以便未来需要时一键恢复 `SecurityTypes VncAuth`。

## 后果与回退

- 恢复认证：把命令行改回 `-SecurityTypes VncAuth -rfbauth /home/hermes/.vnc/passwd`
  即可（密码写入流程未删）。
- 文档同步：ARCHITECTURE 认证链表、OPERATIONS、DEPLOYMENT 变量表已更新。
