# ADR 0005：noVNC 断连事件 —— 平台边缘 VNC 网关拦截（根因记录）

日期：2026-09-15 · 状态：平台侧故障，容器侧已加固并留有诊断通道

## 事件与证据链

2026-09-15 晨起浏览器 noVNC 全量报「无法连接到服务器」。逐层定位（隧道内
协议级抓取 + 真实浏览器复现 + /readyz vncCmd 诊断）：

1. 容器内九探针全绿；CI 门禁内部 WS 101 通过——服务端健康。
2. 公网 WS 升级可到 101，但后续 RFB 字节为 `RFB 003.003` + 安全类型 0 +
   `Too many security failures`——被拒绝在协议协商阶段。
3. 对照实验：容器 VNC 先后以 `VncAuth`（原样）、`VncAuth+Blacklist双零`、
   `SecurityTypes None` 三种配置部署，**拒绝行为完全不变**。
4. `None` 配置的服务器在协议上不可能产生「安全失败」消息 ⇒ 发出拒绝的
   不是我们的 Xtigervnc，而是平台边缘新插入的 VNC 网关（同日上线的
   `X-Studio-Token` 体系；其代理层黑名单已饱和，对所有连接回放该拒绝）。

结论：**平台侧变更/故障**，影响所有经浏览器访问 noVNC 的创空间；容器侧
任何配置都无法修复（拦截发生在 nginx 之前）。

### 绕行尝试的最终排除（2026-09-15 深夜）

| 尝试 | 结果 |
|---|---|
| 换路径 `/desktop/stream`（nginx 改写到 websockify） | 仍被拦截（101 后收到平台代理的横幅/拒绝） |
| 根命名空间 `/vnc-stream` | 同样被拦截——**网关按「指向创空间应用的 WS 升级」拦截，与路径无关** |
| 容器 VNC 配置三变（VncAuth / 双零参数 / None） | 拒绝行为不变（请求根本到不了容器） |
| 附带发现：Noble 构建 `SecurityTypes None` 不可用 | 广告空安全类型列表（连接必死），已回退 VncAuth |

最终容器形态：`/desktop/stream` 与 `/vnc-stream` 两个别名并存（均改写到
websockify，Authelia 门禁），VNC 为 `VncAuth`。平台网关恢复透传后两个路径
都可用；noVNC 需输 VNC 密码（Secret `VNC_PASSWORD`，前 8 位生效）。

## 期间落地的容器侧加固（独立有效，保留）

- keepalive 盲点修复（PR#17）：runner 连不上 ms.show 不再触发恢复性重部署。
- 恒定值 `X-Studio-Token` cookie（PR#18，ADR 0004）：满足边缘新门禁。
- `/readyz` 暴露 `vncCmd`/`vncDiag` 诊断字段（PR#22/25）：远程即可确认
  实际 VNC 命令行与 5901 连接方。
- VNC 配置现状：`-SecurityTypes None`（回环、无认证）——在平台网关透传后
  无需密码即可进桌面；`VNC_PASSWORD` Secret 保留未消费，可随时回退
  `-SecurityTypes VncAuth -rfbauth …`。

## 平台恢复的验证方法

```bash
curl -A 'Mozilla/5.0' https://zephyr17-hermes-agent.ms.show/readyz   # 应 ready:true
# 浏览器刷新空间页 → 登录 → Open KDE desktop
# None 配置下无需 VNC 密码；若出现密码框属异常
```
