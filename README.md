# Zephyr AI Desktop（恢复版）

容器化 AI 桌面环境，部署于魔搭（ModelScope）Docker Space：KDE Plasma 远程桌面 + Hermes Agent + Hermes Studio（仅桌面内访问），云模型推理。公网只暴露 7860，Nginx 统一入口，Authelia Cookie 登录。

本分支是[恢复版](docs/decisions/0001-cookie-auth-over-basic-auth.md)：只保留「登录 → 桌面 → Hermes → 持久化」核心链路。原版 8 服务全量架构（Open WebUI / Flowise / llama.cpp）不在本镜像中，旧实现见 `modelscope/` 目录与 git 历史。

## 架构

```
浏览器 → 魔搭空间页(iframe) → Nginx :7860（唯一公网端口）
                                ├─ /auth/    → Authelia 登录（Cookie 会话）
                                ├─ /         → 受保护入口页
                                └─ /desktop/ → noVNC :6080 → TigerVNC :5901（KDE Plasma）
                                                 └─ 桌面 Chrome → 127.0.0.1:8648 Hermes Studio
                                                                    └─ Hermes Agent → 云模型 API
```

- 所有内部服务只绑 `127.0.0.1`，仅 Nginx 对外。
- 持久化数据全部在 `/mnt/workspace/zephyr-v2/`（平台持久盘）。
- 容器启动时由 `recovery/bootstrap.py` 生成全部配置（nginx / Authelia / supervisord）到 tmpfs。

## 部署

镜像由 GitHub Actions 构建：单元测试 → 构建候选镜像 → 真实容器验收 → 发布 GHCR，产出 digest 固定的部署文件。魔搭空间仓库只放一个 2 行 Dockerfile（`FROM …@sha256:…`），不在平台侧构建。

完整步骤、Secrets 清单与回滚见 [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)。

## 安全模型

三道门：魔搭平台登录 → Authelia Cookie 会话 → VNC 密码 + 桌面锁屏密码（三层密码相互独立，不构成双因素认证）。

关键措施：

- Secret 全部运行时注入，镜像零密钥；改密码 = 改空间 Secret + 重部署，不需要重建镜像；
- 密码只存哈希或受限权限文件；entrypoint 在启动服务前 unset 所有密码环境变量；
- 内部端口不对公网路由；Gateway API 仅容器内 loopback；
- 单容器不是强隔离沙箱，不要在其中存放无关高权限凭据。

## 仓库导航

| 路径 | 职责 |
|---|---|
| [AGENTS.md](AGENTS.md) | Agent 工作入口：文档地图 + 项目硬约束 |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | 进程/端口/路由/持久化的当前真源 |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | 部署链路、Secrets 规则、密码轮换、回滚 |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | 健康检查、验收、备份、排障 |
| [docs/decisions/](docs/decisions/) | 架构决策记录（ADR） |
| [docs/archive/RECOVERY.md](docs/archive/RECOVERY.md) | 恢复版初版实施记录（已被上述文档取代，仅存档） |
| `recovery/` | 恢复层实现：bootstrap / entrypoint / 桌面与 Studio 启动 / 健康检查 |
| `tests/` | 单元 + Nginx 集成测试、真实容器冒烟验收（含 KWin 窗口管理门禁） |
| [docker-compose.yml](docker-compose.yml) | 本地预演：与生产同一 Dockerfile，跑通 healthz/readyz/登录/桌面 |
| `legacy/` | **遗留**：原版全量架构资产（旧 modelscope/ 实现、旧备份脚本、旧环境模板），当前镜像不使用 |

## 本地预演

```bash
cp .env.recovery.example .env   # 填入必填值
docker compose config && docker compose up --build
curl -fsS http://127.0.0.1:7860/healthz   # liveness
curl -fsS http://127.0.0.1:7860/readyz    # readiness（七探针）
```

## 测试

```bash
python -m unittest discover -s tests -v
python scripts/docs-audit.py         # 文档断链/漂移
python scripts/check-consistency.py  # 端口/环境变量/端点跨文件一致性
```
