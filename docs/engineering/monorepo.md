# Monorepo 工程组织

本文记录目录、开发责任和评审约定。部署 Profile 的配置与各模块首个可运行切片一同交付。

## 目录与所有权

| 路径 | 主责 | 范围 |
| --- | --- | --- |
| `services/cloud/`、根 `pyproject.toml`、`requirements-dev.lock`、既有 Cloud 脚本与配置 | 项目负责人 | 云 API、身份、Tenant、Site、设备登记、媒体管理、核心模型、Cloud 迁移与测试 |
| `services/edge-runtime/` | Mike | 场馆本地 API、设备、视频采集、媒体目录与存储、任务与 Worker、离线恢复及运维 |
| `apps/venue-console/` | Mike | 场馆 LAN 中的 Edge 管理前端 |
| `apps/personal-workbench/` | Mike | 个人上传与分析提交、指标、报告及历史，含工作台内部 API |
| `deploy/cloud/` | 项目负责人 | 云端独立部署 |
| `deploy/venue/` | Mike | 场馆部署 Edge Runtime 和 Venue Console |
| `deploy/personal/` | Mike | 个人工作台独立部署 |
| `deploy/dev/` | 双方共同评审 | 本地组合开发、Mock 和集成测试 |
| `docs/contracts/`、`openspec/`、`.github/` | 项目负责人 | 统一接口、规格与仓库治理，涉及其他模块时由相应负责人共同评审 |

当前 Cloud 的根级 Python 配置只服务 Cloud。Mike 在各自模块目录落地依赖清单、锁文件、测试入口、构建和版本交付。模块内部变更由对应负责人评审；跨模块或仓库级变更先取得相关负责人同意。GitHub CODEOWNERS 待核实 Mike 的登录名及仓库写权限后另行补录。

## 接口与数据边界

- 各模块拥有自己的持久化和迁移。跨模块通过版本化 API、DTO、JSON Schema 或事件交互。禁止直接读写对方数据库或导入对方的 ORM、内部服务和数据库 Session。
- 现有 [Cloud 契约与 OpenAPI 快照](../contracts/) 保持原位置。实际出现多个机器消费者时，才考虑 `packages/contracts/`。每个契约指定唯一源文件，生成的快照记录生成来源和校验方式。
- 项目负责人维护统一分析引擎和协议。Venue Capture 和 Personal Upload 使用各自的来源适配器，经统一分析任务、结果和报告接口交互。个人来源保留其真实归属，禁止伪造 Site、Camera 或 EdgeNode。
- 契约变更从根级 OpenSpec 提案开始。列明提供者、消费者、版本与兼容窗口、迁移和回退安排、验收场景；取得双方评审后再发布契约并推进实现。Verify 记录实际消费者测试和 strict 结果，按约定同步主规格并归档历史。

## CI 扩展方案

当前 [Cloud CI](../../.github/workflows/ci.yml) 对 push 和 pull_request 保留 SQLite、PostgreSQL 17 和隔离 RustFS。新模块具备可执行的安装、构建与测试命令后，再按下表增设任务。

| 变更路径 | 计划运行 |
| --- | --- |
| `services/cloud/**`、根 Cloud 依赖文件、Cloud 使用的 `scripts/**` 和 `configs/**`、`deploy/cloud/**` | 保留 Cloud 三项检查 |
| `services/edge-runtime/**` | Edge 单元、集成、合成视频及故障恢复 |
| `apps/venue-console/**` | Venue Console lint、类型、构建与 E2E |
| `apps/personal-workbench/**` | Personal Workbench 上传、来源适配、Mock Analysis Gateway 与 E2E |
| `deploy/venue/**`、`deploy/personal/**`、`deploy/dev/**` | 对应部署验证及受影响模块的组合测试。场馆部署验证同时检查个人工作台的隔离 |
| `docs/contracts/**`、将来的 `packages/contracts/**` | 按契约与消费者映射运行提供者及全部受影响消费者的契约测试 |
| 根 CI、公共构建边界或未能判定模块的变更 | 保守运行所有已接入的检查 |

扩展顺序：

1. 为可运行模块增加独立 Job 和明确的路径映射。对 PR 按 merge base 比对，对 push 按事件前后提交比对，覆盖新增、重命名和删除。契约消费者无法确定时运行全部已接入的契约测试。
2. 工作流入口持续运行。全局 Job 执行 OpenSpec 主规格 strict、受影响 Change strict 和仓库完整性检查。汇总 Job 检查所有应运行任务是否实际成功，并以稳定的检查名供分支保护使用。当前 OpenSpec strict 可从根目录执行 `OPENSPEC_TELEMETRY=0 openspec validate --specs --strict`。
3. 用 Cloud、Edge、两种前端、共享契约和文档变更验证路径矩阵。确认现有必需检查和证据产物可持续获取后，再评审 Cloud 路径过滤与分支保护调整。

依据：[Monorepo 工程组织方案](https://app.notion.com/p/41ef602574aa8125afdbd417a661b711) · [Edge Station 总控](https://app.notion.com/p/41ef602574aa81dba534fa10ed46ad2a) · [仓库整理任务](https://app.notion.com/p/41ef602574aa8194a982c1f4721d04d9)
