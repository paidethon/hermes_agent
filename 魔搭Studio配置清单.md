# Zephyr AI Desktop — 魔搭 Studio 配置清单

> 生成时间：2026-08-09  
> Studio 地址：https://www.modelscope.cn/studios/zephyr17/hermes_agent  
> 所有者：zephyr17  
> GitHub 仓库：https://github.com/paidethon/hermes_agent  
> **可见性：公开（public）** — 2026-08-09 转公开，访问实际服务仍需 Basic Auth  
> **备份加密：已移除** — 2026-08-09 起移除 rclone crypt 加密层，备份明文写入 OneDrive

---

## 一、Secrets（密钥，平台不返回明文）

以下密钥通过魔搭 OpenAPI `POST /studios/{owner}/{repo}/secrets` 配置，平台只存储不返回。

| 序号 | 密钥名称 | 用途 | 值 | 来源 |
|------|----------|------|-----|------|
| 1 | `PORTAL_PASSWORD` | Nginx Basic Auth 登录密码（门户第一道门） | `ngix45153593` | 用户手动设置 |
| 2 | `VNC_PASSWORD` | TigerVNC 桌面连接密码（第二道门，≥8位含字母+数字） | `vnc45153593` | 用户手动设置 |
| 3 | `ONEDRIVE_TOKEN` | OneDrive OAuth 访问令牌（JSON 格式，含 access_token/refresh_token） | 见下方完整 JSON | `rclone authorize "onedrive"` 生成 |
| 4 | `ONEDRIVE_DRIVE_ID` | OneDrive 驱动器 ID | `6AB528CE6CFDB5E1` | `rclone config` 中 onedrive remote 的 drive_id |
| 5 | `MODELSCOPE_API_KEY` | 魔搭 API 令牌（云端推理 + keepalive 保活） | `ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384` | https://modelscope.cn/my/myaccesstoken |

> ~~`RCLONE_CRYPT_PASSWORD` / `RCLONE_CRYPT_PASSWORD2`~~ 已于 2026-08-09 删除（不再使用加密备份）。

### ONEDRIVE_TOKEN 完整值

```json
{
  "access_token": "EwBIBMl6BAAU9BatlgMxts2T1B5e3Mucgfs4jcAAAQ2ARvTUbxZn7M/thzMnqU+huF/b58CgkDH7igrkBRcVd1PCYo4Zai49QOo16oHh1xEt8TD7w8c1PcHqp6Kde4lALAfdtNa0jusO6UtYdgYuJBxwTVM3V7szUkR417GKwmdYzmEPIJd+etYhvfvdvEeJzPbtesBDkMZL83RwjtPb2TQX8y5nPfAgDFikn3rIIPJ/3Sskj8e/9WVgh6ilrOZgXUdOpk0rBya9QvsOPW1L2EvO6OKmycHNkF8uul6JMhE4SscLlsJ9sX6zIdczM4u6qKzCn2IVH80uuMkUxUd/6gnj4RqQ/AtwP5WF3nSWHBivF13Z2We8xr89Rh+PacYQZgAAEKdPy6JZH4A9pQp4/+rpewYQA8ZFAdomqazEePqs87a3GkWGcMo8isYu432pW5Em1MyZhEZZf+23by+UZYci2YLww+9RDd7rk1v+ylp4SrDe/bxZYLmIsQC7pRXftkkNENIDp11CRVrvrpjsEyAkduDJ8uNXAXhYMRGgx5ZiRaZPHdizduP30grYh5HUfVuIHRzlWSKhncYbF9uQY6djatpLujFg3Hq/j7LOEsIhUmFdhN3jqSLK0eUkwRGM2N9LhUPQOQZr69ohpEMlf6Qut3PxcCQ/84gA7Eu/SMKuiL0gxCDt5sC3HNBus+fnyzRov7FNkaIQPDHW/RNgBImH9nKfl0nkXyFDBV+L8+2BQQ6T0m+OgVnheyfdjlvHE/BeQBWecD7hM2QbFmliAzmNtdZTvnrUxeoKBzbViXElZMQD7opUfMyoFJpYZvXTuLoE8DIIHhE74Xh+ISeTrIeIzjooPh/H6swUFLjt9uxfDdiVzRmfcRbMwmhbFaVrFzQfvTG9zn1aDTnF1b7GYtK7L3QSN4jg/qPMcNcXvlwjVeSB0x7ctTsm9OF0XefYlcnRAQDnmeNgaTBkF7xqJNqHes+amgb7ks5ar928AKdOHj2g9FUYITOGky4f6LkPpxd2C8qQPt+yZGJ5XaEOLi+oOnvkLWZ/Vz5XUw7Db4IOn1dRXkLCssKpwJjZ3Bpv/X1qywtCj7xarilO9F7oim5exWwILDVae2JGjr8EePLMX1128VS/mDOIfzWRDFodlNeKhT0p2G9CRUTs73Uzt39ju3sKCkeQaf0wX45yKrG96GU7B/yFns5c+0lrMfCG1RwhGGGju+EsQiXvu+qJd6BNBzu/PD+FDvskf64LnlonA/zfpZNtdQx8eTMJyOACtxW+TbpM/hJOqnzJRND6hKWWsb+oDQipVomgmGeZyVXVs/Yh1BGe2HbB2Wzj0/xdhTeRUKF+86VDqiePoeLMbd/EYJRnq9/1xdgWrRkFLQ9eH7IvahTRc+OhExtwbZ8+Z9M958f9y4W645dLkBsyukuKLpb1YxPD8/ZKSeS0htUkgKg86N1CAw==",
  "token_type": "Bearer",
  "refresh_token": "M.C508_BL2.0.U.MsaArtifacts.-CnpDh!8KBQvj8I1g6!iMwBri5J9bY4VAA2dDAx!3hO1XkV2lF2NQ6uZBBJ0aU1!aFrjzA!L5E5jH5fFQyba47bmJkThz0y17KAQBWZOZ0a8wVKsi6KC9730FU4yvNaRvimDNxLngBuLh1YnbpjEQjNGSosj2AEoAzmWvluiU5deJMCmNoAEvvj39VABpdXiQcX623E6Cz!bm4TS9swMz*GmQ2BDzA4jw0hVsrd529mYySDvdWsxcq*20oQ!S30HEp*d*j!2urL2Tuf7GK4228maxxeyvLt1Tr*acWJUC5YfIQPHPyTqzwGcBbR9pQMJY13qSVWr!ssi0l6W7tyRg02ez8kouy!u8vM3kSDVrc1iRnaQjq1APJ*EaaJvwVGMS0r3CvcM7EW9a*b6rzpnwvsmSH!6txEMeVts1epcHeFpP",
  "expiry": "2026-08-09T01:49:59.9532694+08:00",
  "expires_in": 3599
}
```

> ⚠️ access_token 有效期仅 1 小时，但 rclone 会自动使用 refresh_token 续期。

---

## 二、Variables（明文变量，平台返回明文）

| 序号 | 变量名称 | 用途 | 值 | 来源 |
|------|----------|------|-----|------|
| 1 | `PORTAL_USER` | Nginx Basic Auth 用户名 | `zephyr` | 用户手动设置 |

---

## 三、自动生成的密钥（无需手动配置）

以下密钥由 `entrypoint.sh` 在容器首次启动时自动生成并持久化到 `/mnt/workspace/zephyr/config/`：

| 密钥名称 | 生成位置 | 用途 | 生成规则 |
|----------|----------|------|----------|
| `HERMES_API_KEY` | `/mnt/workspace/zephyr/config/hermes-api-key` | Hermes Gateway API 认证（≥16位） | 32位随机字符串（`/dev/urandom`） |
| `FLOWISE_USER` | `/mnt/workspace/zephyr/config/flowise-credentials.env` | Flowise 登录用户名 | 固定 `zephyr` |
| `FLOWISE_PASSWORD` | `/mnt/workspace/zephyr/config/flowise-credentials.env` | Flowise 登录密码 | 24位随机字符串（`/dev/urandom`） |

---

## 四、GitHub Actions Secrets（keepalive 保活用）

以下密钥配置在 GitHub 仓库 Settings → Secrets and variables → Actions：

| 序号 | 密钥名称 | 用途 | 值 |
|------|----------|------|-----|
| 1 | `MODELSCOPE_TOKEN` | 调用魔搭部署 API | 同 `MODELSCOPE_API_KEY` |
| 2 | `SPACE_ID` | 魔搭空间标识 | `zephyr17/hermes_agent` |
| 3 | `ALERT_WEBHOOK` | 部署失败告警（可选） | 钉钉/飞书机器人 webhook URL |

---

## 五、登录信息汇总

| 服务 | 地址 | 用户名 | 密码 |
|------|------|--------|------|
| **魔搭 Studio** | https://www.modelscope.cn/studios/zephyr17/hermes_agent | — | — |
| **门户 Basic Auth** | 访问 Studio 时弹出 | `zephyr` | `ngix45153593` |
| **VNC 桌面** | 门户登录后 /desktop/ | — | `vnc45153593` |
| **Hermes Studio** | 门户登录后 / （根路径） | `admin` | `123456`（首次登录后强制改密） |
| **Flowise** | 门户登录后 /flow/ | `zephyr` | 自动生成（见第三节） |

---

## 六、rclone 备份配置摘要

| 项目 | 值 |
|------|-----|
| **备份目标** | OneDrive Personal |
| **驱动器 ID** | `6AB528CE6CFDB5E1` |
| **加密方式** | 无（2026-08-09 起移除 crypt 加密层，明文写入） |
| **备份路径** | `onedrive:zephyr-backup` |

> ⚠️ **注意**：备份为明文，任何能访问该 OneDrive 的人均可读取备份内容（含 Hermes 会话、聊天记录、配置）。请确保 OneDrive 账户安全。

---

## 七、API 调用示例

```bash
# 查询所有 secrets（只返回 key 列表）
curl "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/secrets" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384"

# 查询所有 variables（返回 key + value）
curl "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/variables" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384"

# 添加/更新 secret
curl -X POST "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/secrets" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384" \
  -H "Content-Type: application/json" \
  -d '{"key":"PORTAL_PASSWORD","value":"ngix45153593"}'

# 添加/更新 variable
curl -X POST "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/variables" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384" \
  -H "Content-Type: application/json" \
  -d '{"key":"PORTAL_USER","value":"zephyr"}'

# 触发部署
curl -X POST "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/deploy" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384"

# 查看运行日志
curl "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/logs/run" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384"

# 查看构建日志（Docker 类型）
curl "https://modelscope.cn/openapi/v1/studios/zephyr17/hermes_agent/logs/build" \
  -H "Authorization: Bearer ms-f40dd4cf-651c-4b0c-9dab-64e414bcd384"
```

---

## 八、Git 仓库信息

| 项目 | 值 |
|------|-----|
| **GitHub 仓库** | https://github.com/paidethon/hermes_agent |
| **魔搭 Git Remote** | `https://oauth2:ms-f40dd4cf-...@www.modelscope.cn/studios/zephyr17/hermes_agent.git` |
| **默认分支** | `master`（魔搭）/ `main`（GitHub） |
| **推送命令** | `git push modelscope main:master` |

---

*本文档包含敏感信息，请勿公开分享。*
