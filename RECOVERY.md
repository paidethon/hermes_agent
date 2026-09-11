# Hermes × 魔搭空间：核心链路恢复实现

编制日期：2026-09-11。

**这是可以加入仓库并执行构建、验收和部署的代码包，不是“已经替你上线”的声明。** 当前环境已运行 25 项测试，其中包含真实 Nginx 与模拟后端的集成测试；没有运行完整 Docker 镜像，没有登录或修改你的魔搭空间。完整镜像必须先通过随包 GitHub Actions 验收，再部署到魔搭。

## 1. 这个版本解决什么

保留 KDE 桌面、Hermes Agent、桌面内访问的 Hermes Studio。公网只开放 7860，由 Nginx 与 Authelia 进行 Cookie 登录鉴权，再进入 noVNC。Studio 留在容器内部 127.0.0.1:8648，在远程 KDE 的浏览器内使用。

恢复版**不安装、不开放** Open WebUI、Flowise、llama.cpp，也不自动下载本地模型，不启动消息渠道 Gateway。它不是原项目所有功能的等价替换，而是用于先修复“登录 → 桌面 → Hermes → 持久化”的独立部署配置。

```text
本地浏览器 ── HTTPS ── 魔搭入口 ── Nginx :7860
                                  ├─ /auth/ → Authelia :9091
                                  ├─ / → 受保护的入口页
                                  └─ /desktop/ → noVNC :6080 → TigerVNC :5901 → KDE
                                                                                └─ 桌面 Chrome
                                                                                   → 127.0.0.1:8648
                                                                                   → Hermes Studio
                                                                                   → Hermes Agent
                                                                                   → 云端模型 API
```

Auth、noVNC、VNC、Studio 的服务监听均按本机访问设计。KDE 与 Agent 使用 uid 1001，Authelia 使用 uid 1002；Nginx 主进程和 Supervisor 保留必要的 root 权限。**同一个容器不是不可信 Agent 的强隔离沙箱。** 不应在其中保存无关的高权限凭据。

## 2. 平台依据与故障定位

魔搭官方维护的 Docker 部署参考明确要求：监听 0.0.0.0:7860，不使用平台占用的 8080；应用请求不要使用 Authorization、X-modelscope-*、X-studio-*；持久化目录为 /mnt/workspace。[1]

原仓库入口使用 Nginx Basic Auth；Basic Auth 本身使用 Authorization，因此与平台要求冲突。这能解释上传记录中的“密码正确仍反复 401”，但并非本次已完成的线上抓包结论。不要再将反复修改 htpasswd 权限当作唯一修复方案。

原 Dockerfile 在 /opt/hermes-src 执行可编辑安装，随后复制到 /opt/hermes 并删除 /opt/hermes-src。可编辑安装依赖原始路径，因此命令存在不等于模块可导入。恢复版直接安装到最终路径，并从 /tmp 执行 hermes --help 验证。

上传日志还记录了 Debian wheel 的 RECORD 缺失及 antlr4-python3-runtime 构建失败。恢复版保留 Ubuntu 系统 Python，只在独立 venv 内安装 Hermes，不再通过覆盖系统 Python 或混装 Open WebUI 依赖解决这些错误。

**注意区分两段网络：** 上述平台请求头限制针对经魔搭入口到应用的请求，不意味着容器向模型供应商发送的出站 API 请求不能使用 Bearer API Key。本实现的模型请求直接由容器发出，不经公网的 /desktop/ 反向代理。

## 3. 文件清单

- Dockerfile：固定应用版本、Hermes 独立 venv、Studio 构建、KDE 与 Authelia。
- recovery/bootstrap.py：校验配置、创建独立数据目录、生成 Nginx/Authelia/Supervisor 配置。
- recovery/desktop.sh：等待 X Server 后显式启动 DBus 与 Plasma 桌面。
- recovery/studio.sh：Studio 仅监听本机，并关闭其自动启动 Gateway 的逻辑。
- recovery/health.py：区分入口存活和桌面/Studio 就绪，不冒充模型可用性检查。
- recovery/model_probe.py：按需测试云模型 API；聊天测试可能消耗额度，不自动执行。
- recovery/backup.sh：显式维护窗口内停写、校验的本地备份。
- tests/test_recovery.py：25 项单元及真实 Nginx 集成测试。
- tests/smoke_container.py：构建后真实容器验收，未通过则不发布镜像。
- .github/workflows/recovery-image.yml：构建、验收、发布同一镜像，再生成 digest 固定的部署文件。
- docs/VERIFICATION.md：已验证、未验证及魔搭现场验收边界。

## 4. 加入你的 GitHub 仓库

在 WSL 中使用一个新的工作目录，避免覆盖正在修改的原项目。先将下载的压缩包放到可访问的路径。下面只需改第一行的 ZIP 路径：

```bash
RECOVERY_ZIP=/mnt/c/Users/zephyr/Downloads/hermes-modelscope-recovery.zip
mkdir -p ~/projects
cd ~/projects
git clone https://github.com/paidethon/hermes_agent.git hermes_agent-recovery
cd hermes_agent-recovery
git switch -c recovery/modelscope-cookie-auth
unzip "$RECOVERY_ZIP" -d /tmp/hermes-recovery-package
PKG=/tmp/hermes-recovery-package/hermes-modelscope-recovery
cp "$PKG/Dockerfile" Dockerfile
cp "$PKG/.dockerignore" .dockerignore
cp -R "$PKG/recovery" ./
mkdir -p tests .github/workflows docs/recovery
cp "$PKG/tests/"*.py tests/
cp "$PKG/.github/workflows/recovery-image.yml" .github/workflows/
cp "$PKG/README.md" RECOVERY.md
cp "$PKG/.env.example" .env.recovery.example
cp "$PKG/docs/"* docs/recovery/
git add Dockerfile .dockerignore recovery tests .github/workflows/recovery-image.yml RECOVERY.md docs/recovery
git add -f .env.recovery.example
git diff --cached --stat
git commit -m "Add ModelScope cookie-auth recovery profile and deployment gates"
git push -u origin recovery/modelscope-cookie-auth
```

压缩包中没有你的真实密码、Token 或历史对话。不要把自己的 .env、rclone 配置、备份、模型文件加入提交。

新分支的 push 会触发 recovery-image。旧的自动同步魔搭、自动发布镜像或 keepalive 工作流需要单独检查、停用，避免新旧流程互相覆盖。不要为了阻止平台休眠而添加未经平台允许的保活策略。

## 5. 构建成功后部署到魔搭

工作流顺序：配置测试 → 构建候选镜像 → 真实容器验收 → 发布同一个候选镜像 → 生成部署文件。镜像验收失败时不应跳过步骤强行发布。

成功后，GitHub Actions 的 `modelscope-deployment` artifact 内有：

```text
Dockerfile
source-commit.txt
image-digest.txt
```

Dockerfile 的形式为：

```dockerfile
FROM ghcr.io/paidethon/hermes_agent@sha256:实际生成的摘要
EXPOSE 7860
```

**不要复制上面的占位文字；使用工作流真正生成的文件。** 首次发布时检查 GHCR Package 是否可公开拉取。源码仓库公开不自动意味着镜像公开。镜像内不应包含运行时 Secret。

先建议建立测试空间验证；使用原空间时，先备份旧数据与旧 Dockerfile。在魔搭空间的代码仓库中，用生成的 Dockerfile 替换根目录 Dockerfile，保留适用于 Docker 空间的元信息。不要追加旧 CMD/ENTRYPOINT。通过页面编辑提交，可避免误把 GitHub 的 main 和魔搭的 master 当作同一分支；使用 Git 时必须确认空间实际构建分支。

这一部署步骤只拉取预构建镜像，不再在每次魔搭构建时编译整套 KDE、Python、Node 和推理引擎。仍然需要下载镜像层；不能保证镜像站网络、拉取速度或构建耗时。若 GHCR 在空间构建网络中不可达，将通过验收的镜像复制到你有权限的阿里云镜像仓库，再使用该仓库实际生成的 digest；不同仓库的 manifest digest 可能不同，不要手工沿用旧值。

## 6. 魔搭运行配置

在空间的运行时变量/Secret 设置中添加以下字段，**不要写进 Dockerfile、公开 README 或构建参数**：

| 字段 | 填写方式 |
|---|---|
| PUBLIC_ORIGIN | 魔搭显示的实际应用 HTTPS 源地址，不带路径；不是 www.modelscope.cn/studios/... 管理页。不要仅根据用户名猜测域名。 |
| AUTH_USERNAME | 例如 zephyr，使用小写字母、数字、下划线或连字符。 |
| AUTH_PASSWORD | 新生成的至少 16 字符密码；仅保存 Argon2 哈希，未提供则首次启动失败关闭。 |
| VNC_PASSWORD | 首次启动必填，恰好 8 个非空格 ASCII 字符；不要与外层密码相同。 |
| OPENAI_BASE_URL | 你已确认可用的 OpenAI 兼容 HTTPS API 基础地址。 |
| OPENAI_API_KEY | 对应供应商的运行时密钥。 |
| HERMES_MODEL | 该账号真正有权限调用的模型完整 ID，不要照抄旧截图的模型名。 |
| DATA_ROOT | 保持 /mnt/workspace/zephyr-v2。不要改回旧 zephyr 目录。 |
| CHROME_NO_SANDBOX | 默认 0；仅在确认平台阻止 Chrome 沙箱且接受风险时显式改为 1。 |

前四项用于建立登录和桌面。云模型三项可以稍后配置；未配置时界面就绪不代表 Agent 能回答。模型只在没有现存 config.yaml 时由环境初始化；已有配置优先保留，后续切换用 `hermes model`，不能靠更改 HERMES_MODEL 强行覆盖历史设置。

外层表单登录与 VNC 密码是两层口令，**不是双因素认证**。VNC 传统认证的密码长度限制不是外层登录密码也只能用 8 位的理由。

## 7. 第一次使用及验收

从魔搭打开应用的**独立页面**，不要在平台嵌入式 iframe 内测试登录。恢复版主动设置 X-Frame-Options: DENY，Cookie 按 HTTPS 与明确域名设置。

先通过 Authelia 表单登录，再进入桌面并输入单独的 VNC 密码。点击桌面的 Hermes Studio 快捷方式，或在**远程 KDE 内的 Chrome**打开：

```text
http://127.0.0.1:8648
```

这不是在你 Windows 本地浏览器地址栏输入的地址。本地浏览器只访问魔搭 HTTPS 应用入口。

远程终端中先执行：

```bash
hermes --help
hermes model
/usr/bin/python3 /opt/recovery/model_probe.py
# 以下请求可能消耗 API 额度，确认后手工执行：
/usr/bin/python3 /opt/recovery/model_probe.py --chat
```

`/models` 并非所有兼容供应商都提供；404 不必然意味着聊天接口不可用，应以供应商文档和一次实际调用验证。Probe 只确认 API 传输，不确认 Hermes 工具调用。再进入 Hermes，让它在 `/mnt/workspace/zephyr-v2/work` 下创建一个明确指定的测试文本文件、读取内容并返回，验证一次实际工具执行。不要用生产文件做第一轮操作。

接着在桌面创建一个测试文件，完成一次 Studio 对话，并在允许的情况下保存浏览器设置。重启空间，再检查文件、模型配置、会话和浏览器状态；仅确认 home 哨兵文件存在不能代表所有应用数据库迁移都正确。最后还要执行一次重建和一次隔离恢复演练。

管理员排障命令：

```bash
supervisorctl -c /run/zephyr/supervisord.conf status
/usr/bin/python3 /opt/recovery/health.py --once
curl -fsS http://127.0.0.1:7860/healthz
curl -fsS http://127.0.0.1:7860/readyz
```

`/healthz` 只代表 Nginx 活着。`/readyz` 要求 Auth、noVNC、VNC、Studio HTTP 与 Plasma 进程均满足检查；不测试有费用的模型调用，也不证明每个画面控件正常。

## 8. 持久化、旧数据迁移与回滚

```text
/mnt/workspace/zephyr/       原数据，恢复实现不自动修改或删除
/mnt/workspace/zephyr-v2/
  auth/                    Auth 哈希、密钥、数据库，uid 1002 私有
  home/                    KDE、Chrome、桌面、用户配置，uid 1001
  hermes/                  Hermes 配置与会话
  studio/                  Studio 状态
  work/                    用户工作文件
```

/home/hermes 指向新 home；其 .hermes 指向新 hermes。不是只把 Desktop 目录持久化。

先验收空白新环境，再安排迁移。**不要直接将旧目录软链接到新目录，也不要在运行中 rsync SQLite 数据库。** 迁移前用原程序停止写入，保留旧目录和新目录各一份备份，确认上游版本兼容后复制需要的数据，统一目标权限；旧配置中的绝对路径、端口、provider 和历史失效密钥要逐项检查。恢复版不自动猜测每个历史版本的数据库结构。

回滚时将魔搭根 Dockerfile 换回记录下来的原镜像 digest 或原 Dockerfile，并使用其原数据目录。新环境使用独立目录，不会因回滚而自动删除。若迁移后已产生新数据，要先导出再回滚；不能认为旧版本总能读取新数据库。

## 9. 备份

`backup.sh` 必须在空间的**管理员终端**以 root 运行，不能在即将被关闭的 noVNC 终端中运行。它会停止桌面、Studio、Auth 和相关服务，并终止 uid 1001 的用户进程，所以必须先保存工作、结束 Agent 任务，再显式执行：

```bash
bash /opt/recovery/backup.sh
```

它生成 `/mnt/workspace/recovery-backups/*.tar.gz` 与 SHA256 校验文件，打包前停止写入，打包后检查归档可读性，失败不会输出“成功”。停止期间应用不可访问。

该文件仍在同一个空间里，**不是异地备份**。它可能包含浏览器登录状态和 API 凭据；应使用你已有的加密备份方案，例如 rclone crypt，复制到你控制的存储，并在隔离目录/测试空间验证恢复。加密密钥要保存在空间之外。不要把未加密备份上传到公开代码或模型仓库。

## 10. 常见错误

**登录后又回到登录页：** 检查 PUBLIC_ORIGIN 与实际独立应用域名是否完全一致、Cookie 的 Secure/Domain 是否正确、Set-Cookie 是否被入口保留；不要回退到 Basic Auth。

**noVNC 页面能打开但连不上：** 在浏览器 Network 中检查 `/desktop/websockify` 是否 101，确认 Origin 是实际应用 origin，再检查 VNC 5901 和桌面进程。不要为了排障去掉鉴权或把 5901 暴露到公网。

**Auth 或桌面目录 permission denied：** 用管理员终端检查真实挂载的拥有者和 uid 写权限。本实现只处理自己的新目录，不假设 chmod 777 能解决全部平台限制。若平台不允许所需 uid/权限模型，停止该部署并按实际限制调整；不要把整个 Agent、Auth 和公开浏览器一并切成 root 作为默认方案。

**Chrome 报 No usable sandbox：** 默认保留沙箱。确认平台内核限制后，CHROME_NO_SANDBOX=1 是显式风险开关；仅用于受控的本机 Studio 页面，不等于可安全浏览任意网页。没有 GPU 不是自动关闭浏览器沙箱的理由。

**Studio 页面出现而回答失败：** 检查最终安装路径、HERMES_BIN、实际模型配置和提供商响应。不要用 Nginx 200 代替 Agent 健康。

**构建失败：** 保留第一处失败命令和版本信息。应用 tag 固定不代表所有 apt/PyPI 传递依赖已完全锁定；本实现保存实际解析版本，并使用发布后的镜像 digest 固定部署产物。后续可加入依赖锁、镜像扫描和已验证的依赖约束。不要通过删除测试绕过原生模块或上游兼容性失败。

## 11. 后续扩展边界

Open WebUI 和 Flowise 先按本机服务或已有云服务器上的独立服务增加，每个服务有独立依赖环境、数据目录、版本与验收。简单把 /chat/ 或 /flow/ 前缀从请求里剥掉，不会自动改写前端的绝对 /api/、资源地址和 WebSocket。

公网暴露前，要实测对应版本的 base path、认证与平台请求头限制；换成另一个魔搭空间也不会自动解决 Authorization 限制。无法适配的服务更适合放在你控制的 VPS 与 HTTPS 入口后。

本地推理先独立测试真实 CPU、可用内存、模型量化、上下文与输出速度。恢复版不默认下载数 GB 模型，也不把下载完成当作核心入口启动条件。

真正的全天候定时任务、网盘长任务和消息网关需要根据空间实际暂停/回收政策选择环境；本次没有证据证明你的当前资源具备 24/7 可用性。不要承诺固定免费额度、固定磁盘空间或不限流量。

## 12. 参考资料与复用边界

[1] 魔搭官方 Docker 部署参考：
https://github.com/modelscope/modelscope-skills/blob/main/skills/ms-studio-deploy/references/docker-templates.md

魔搭 Docker 文档入口（动态页面，本次未取得正文）：
https://www.modelscope.cn/docs/studios/docker

原项目：
https://github.com/paidethon/hermes_agent

接近的社区实现，作者报告在魔搭运行过；本次未代其独立复现：
https://github.com/comedy1024/hermes-agent-desktop

Authelia 官方 Nginx、子路径监听、会话 Cookie、密码文件配置：
https://www.authelia.com/integration/proxies/nginx/
https://www.authelia.com/configuration/miscellaneous/server/
https://www.authelia.com/configuration/session/introduction/
https://www.authelia.com/configuration/first-factor/file/

Hermes 官方 Docker 和模型配置文档：
https://hermes-agent.nousresearch.com/docs/user-guide/docker/
https://hermes-agent.nousresearch.com/docs/user-guide/configuring-models/

使用原项目的 Hermes v2026.8.3、Studio v0.6.39 兼容性基线，而不是宣称这些是最新版本。Authelia 使用已核查发布资产的 4.39.25，下载时校验 SHA256。Studio 的 tag、Node 原生依赖和完整镜像运行仍必须通过 CI，不能只靠本文认为已验证。各上游软件仍适用其原许可证，本包不重新授权上游代码。