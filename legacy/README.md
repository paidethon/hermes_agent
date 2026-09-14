# legacy/ — 原版全量架构资产（当前镜像不使用）

本目录集中存放原版 8 服务架构（Open WebUI / Flowise / llama.cpp / 自动模型下载 /
OneDrive 备份）的实现，当前恢复版镜像**不构建、不引用**它们。保留目的仅为历史
参照与个别脚本（如旧备份流程）的可恢复性。

| 路径 | 内容 | 被取代者 |
|---|---|---|
| `modelscope/` | 旧 entrypoint / supervisord / nginx / 模型下载脚本 | `recovery/bootstrap.py` + `recovery/entrypoint.sh` |
| `portal/` | 旧静态门户页 | bootstrap 生成的 `/run/zephyr/www/index.html` |
| `config/` | 旧 Hermes 种子配置、rclone 模板 | `bootstrap.initialize_model()` |
| `scripts/` | 旧备份/恢复/首启初始化/健康检查 | `recovery/backup.sh`、`recovery/health.py` |
| `.env.example` | 旧环境变量模板（PORTAL_PASSWORD 等） | `.env.recovery.example` |

不要在本目录中做改动并期望生效——构建上下文（`.dockerignore`）只发送
`Dockerfile` 与 `recovery/`。新工作一律基于 `recovery/`。
