# 入口认证用 Cookie 会话，不用 Basic Auth

状态：Accepted（2026-09-11）

## 问题

魔搭 Docker Space 的浏览器入口是空间页的跨站 iframe。平台要求应用请求不要使用 Authorization 头，而 Basic Auth 依赖 Authorization——历史版本在此链路上出现「密码正确仍反复 401」，且调 htpasswd 权限等修复均无效。

## 决定

入口认证改用 Authelia Cookie 会话（`SameSite=None; Secure`，CSP `frame-ancestors` 允许 modelscope.cn 取代 `X-Frame-Options: DENY`）。

## 原因

- Cookie 不经 Authorization 头，与平台链路无冲突；iframe 嵌入由 CSP 显式允许；
- 表单登录支持会话过期与绝对过期，比 Basic Auth 的常驻头更可控。

## 影响

- 入口认证永久绑定 Cookie 方案：任何「改回 Basic Auth 更简单」的提议都会复现 401，直接拒绝；
- 会话 Cookie 必须保持 `SameSite=None; Secure`，改为 `Lax/Strict` 会破坏 iframe 登录；
- 增加一个认证组件（Authelia，独立 uid 1002），配置由 bootstrap.py 每次启动生成与校验。
