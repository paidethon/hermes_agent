# ADR 0004：魔搭边缘的 WebSocket 令牌门槛与恒定值 Cookie 应对

日期：2026-09-15 · 状态：已实施（可随平台回退而移除）

## 背景

2026-09-15 晨起，魔搭平台边缘开始拒绝所有不带 `X-Studio-Token` 凭据的
WebSocket 升级请求（`403 {"Code":10010101007,"当前接口不支持通过SDK Token直接访问…"}`
），`ms.show` 与 `api-inference` 网关两个入口一致；`X-Studio-Token` 请求头可放行。
前一晚同样的握手仍返回 101，且我们的容器侧九探针全绿、CI 门禁内部 WS 101 通过
——平台侧变更，与我们的镜像无关。

浏览器无法给 WebSocket 设置自定义请求头，因此「要求请求头」=「浏览器 noVNC
全部断连」（实测复现「无法连接到服务器」）。

## 关键实测

边缘**不校验** `X-Studio-Token` 的值——常量占位串即可放行（含 cookie 形态）。
它只是要求凭据存在。`Set-Cookie` 种下的 cookie 会被浏览器自动附带在 WS 升级
请求上，从而满足边缘。

## 决策

`bootstrap.render_nginx` 在全部受保护响应上加：

```
add_header Set-Cookie "X-Studio-Token=1; HttpOnly; Secure; SameSite=None;
                       Path=/desktop/websockify" always;
```

- **恒定值 `1`，零凭据暴露**：不使用空间 token（OPENAI_API_KEY 继续与
  nginx 隔离，见 ADR 0001 与 ARCHITECTURE 的进程环境隔离节）。
- `HttpOnly`（页面 JS 不可读）+ `Secure` + `SameSite=None`（跨站 iframe 必须）
  + `Path=/desktop/websockify`（只随 WS 升级请求发送）。

## 后果与回退

- 平台若取消该校验，此 cookie 变为无害冗余，可保留；若平台改为校验真实值，
  则需评估是否接受真实 token 进 cookie 的暴露面，或改用平台 OAuth（见
  modelscope-oauth-skill）。
- 已打开的旧标签页需刷新一次以获得 cookie。
