# Performance Baseline（2026-09-14 夜）

> 只记录 before / after / 差异 / 结论。没有数据支撑的优化不保留。

## 镜像体积（压缩层合计，GHCR manifest 实测）

| 版本 | 大小 | 层数 | 说明 |
|---|---|---|---|
| before：`recovery-890087b`（= 线上 digest 980ecf6e，Hermes v2026.8.3 / Studio v0.6.39） | **1468.5 MB** | 12 | 最大层：812.9 MB（apt：KDE+Chrome 依赖树）、208.5 MB（Studio 构建阶段 `/usr/local` 全量，含 npm/corepack）、182.9 MB（Hermes venv+源码）、161.8 MB（Chrome） |
| after：`recovery-b5ab642`（Hermes v2026.9.14 / Studio v0.7.21，CI 门禁全绿） | **1463.0 MB** | 14 | **净 −5.5 MB（−0.4%）** |

### 净值的构成（逐层实测，诚实结论）

- **减重措施实际收益 ≈ −210 MB**：apt 去掉 ffmpeg/rclone −47.7；`/usr/local` 只拷 node 二进制（208.5 → 45.9）−162.6。
- **上游增长抵消 ≈ +204 MB**：Studio v0.6.39→v0.7.21 生产依赖 +129.2（node_modules 膨胀，与我们的镜像优化无关）；Chrome 周更 +46.7；Hermes venv +28.3（v0.21.x 模块化新依赖）。
- **结论**：减重措施保留（有效且零回归——真实容器门禁全绿），但在上游快速膨胀期，镜像总体积由上游主导；下一步若要再减，须审计 Studio 生产依赖树（超出本次范围，不做无把握裁剪）。

## 冷启动 / 内存

| 项 | before | after | 结论 |
|---|---|---|---|
| 容器冷启动→/readyz 200 | CI 真实容器门禁观测（await_ready 上限 240s，历史实际 ~60-90s） | 同一门禁回归验证 | 无架构性变化，预期持平 |
| idle 内存 | 未测量（本地无 docker；线上需 /proc 实测） | — | 不做无数据优化；diagnose.sh 已能采集，留待下次线上窗口 |

## 已做/未做的取舍

- **做**：`/usr/local` 精确拷贝（node 二进制 + Studio 树）——构建期 `node -e require(node-pty)` 仍是门禁；build-essential purge——所有编译发生在安装期；ffmpeg/rclone 移除——活跃路径零引用（rsync 保留给 migrate-data.sh）。
- **不做**：KDE 元包裁剪（kde-plasma-desktop 换手工包清单风险高、无数据证明收益）；locale/doc 深度清理（收益 <50MB，破坏 `--no-install-recommends` 前提）；Chrome 依赖精简（平台发行版管理）；Studio node_modules 手工裁剪（动态 require 面未知，破坏风险 > 收益）。
