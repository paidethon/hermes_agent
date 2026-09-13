# 供应链：CI 构建镜像 + 空间侧 digest 固定 2 行 Dockerfile

状态：Accepted（2026-09-11）

## 问题

原方式把整套构建（KDE、Python、Node、推理引擎）放在魔搭空间的原地 Docker 构建：构建慢且不可控，依赖版本漂移，镜像内容不可审计，且历史镜像存在数据重置与 root 崩溃等供应链问题。

## 决定

- 镜像只在 GitHub Actions 构建：单元测试 → 真实容器验收 → 通过才发布 GHCR；
- 魔搭空间仓库只保留 2 行 Dockerfile：`FROM ghcr.io/…@sha256:<digest>` + `EXPOSE 7860`；
- 平台侧不再构建，部署内容 = 某一次验收通过的镜像，digest 固定。

## 原因

- 构建环境固定（ubuntu-24.04 runner），依赖解析结果可保存、可复现；
- 验收与发布是同一个产物，杜绝「测试的镜像 ≠ 部署的镜像」；
- digest 固定使回滚 = 换一行。

## 影响

- 换代码必须走 CI 才能上线；改密码等运行时配置例外（Secret + 重部署即可，见 DEPLOYMENT）；
- 若平台拉不动 GHCR，需要把镜像复制到自有仓库，并使用**该仓库实际生成的 digest**（跨仓库 digest 不同，不能沿用）；
- 平台侧 Dockerfile 必须保持 2 行，不追加 CMD/ENTRYPOINT。
