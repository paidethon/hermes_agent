# Zephyr AI Desktop

容器化 AI 桌面环境，部署于魔搭（ModelScope）Docker Space。Ubuntu 24.04 + KDE 桌面 + Hermes Agent + Open WebUI + llama.cpp 本地推理 + Flowise 工作流，全部收敛在单端口 7860 之后，通过 Nginx 统一路由与认证。

## 架构概览

```
公网 :7860 (Nginx, Basic Auth)
├── /desktop/  → noVNC :6080  → TigerVNC :5901 (KDE Plasma)
├── /hermes/   → Hermes Studio :8648  ←→ Hermes Gateway :8642 (仅 loopback)
├── /chat/     → Open WebUI :8082  → llama.cpp :8081 (本地) / ModelScope API (云端)
├── /flow/     → Flowise :8083
└── /api/      → 404（不暴露，Gateway 仅容器内直连）
```

所有内部服务绑 `127.0.0.1`，仅 Nginx 对外。持久化数据全部落在 `/mnt/workspace/zephyr/`（魔搭持久化盘），可选 rclone crypt 加密备份到 OneDrive。

## 服务与端口

| 服务 | 端口 | 绑定 | 运行用户 | supervisord 优先级 |
|------|------|------|---------|-------------------|
| Nginx Portal | 7860 | 0.0.0.0 | root | 10 |
| TigerVNC | 5901 | 127.0.0.1 | root | 20 |
| noVNC | 6080 | 127.0.0.1 | — | 30 |
| Hermes Gateway | 8642 | 127.0.0.1 | hermes | 40 |
| Hermes Studio | 8648 | 127.0.0.1 | hermes | 50 |
| llama.cpp | 8081 | 127.0.0.1 | hermes | 60 |
| Open WebUI | 8082 | 127.0.0.1 | hermes | 65 |
| Flowise | 8083 | 127.0.0.1 | hermes | 80 |

## 部署

### 魔搭 Docker Space（生产）

1. Fork/推送本仓库到 GitHub
2. 在魔搭创建 Docker 类型 Space，关联 GitHub 仓库
3. 在 Space 设置中配置 Secrets（见 [.env.example](.env.example) 底部清单）
4. 配置 GitHub Actions Secrets（`MODELSCOPE_TOKEN` / `SPACE_ID`），启用 keepalive 保活

### 本地开发

```bash
cp .env.example .env   # 填入 PORTAL_PASSWORD 和 VNC_PASSWORD
docker compose up --build
```

## 仓库结构

```
├── Dockerfile              # 多阶段构建（llama.cpp 编译 + Studio 前端 + 运行时）
├── docker-compose.yml      # 本地开发用
├── .env.example            # Secrets 模板与说明
├── modelscope/
│   ├── entrypoint.sh       # 容器入口：持久化→校验→配置生成→首次初始化→supervisord
│   ├── supervisord.conf    # 8 进程优先级编排
│   ├── nginx/              # nginx.conf + portal.conf（路由/认证/安全头）
│   ├── config/             # llama-cpp.env + open-webui-models.env（运行时配置源）
│   └── scripts/            # 模型下载（SHA256 校验）+ API 连通性测试
├── scripts/                # first-run-init / backup / restore / health-check
├── portal/                 # 导航页
├── config/                 # Hermes 种子配置 + rclone 模板
├── .github/workflows/      # keepalive 保活（GET 状态→仅 Stopped 才 deploy）
└── docs/                   # 架构方案、安全审计报告、最终方案文档
```

## 安全模型

三道门认证：魔搭平台登录 → Nginx Basic Auth → 各应用自身认证（VNC 密码 / Flowise 凭据）。

关键措施：Secret 全部运行时注入（镜像零密钥）、htpasswd bcrypt、敏感文件 chmod 600、noVNC SHA256 校验、`/api/` 不进路由表、内部端口 Nginx 层双保险防护。详见 [docs/security-hardening-supplement.md](docs/security-hardening-supplement.md) 与 [docs/audits/](docs/audits/)。

## 模型集成

混合模式：本地 `unsloth/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf`（llama.cpp，日常对话）+ ModelScope API（Qwen3-235B，复杂推理，免费 2000 次/天）。模型首次启动自动下载（约 5GB），带 SHA256 完整性校验；下载失败自动禁用 llama.cpp，不影响其他服务。

## 文档

- [最终方案文档](docs/最终方案文档.md) — 全部 11 项决策的权威合并记录
- [架构方案](docs/Zephyr-AI-Desktop-架构方案.md) — 决策点拆解与选项对比
- [安全审计报告（模型层）](docs/audits/SECURITY-AUDIT-MODEL-LAYER.md)
- [架构审计报告](docs/audits/ARCHITECTURE-AUDIT-FULL.md)
- [容器化评估报告](docs/CONTAINER-ASSESSMENT-REPORT.md)
