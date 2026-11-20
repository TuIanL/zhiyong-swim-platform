# 新版开发约定

- 本目录是独立新版。业务代码、数据库、配置、测试与依赖不依赖旧 `swim` 的内部导入或 `.env`。
- 用户选择先完成账号、机构与场馆的云端基础；按可运行的功能链交付，不复制旧演示数据充当真实业务。
- 旧 `swim` 的算法、报告或解析器只可按模块评估后迁入，记录来源、许可证、输入输出及回归证据；不复制整库、依赖目录、模型权重、运行数据或旧数据库。
- 机构是隔离边界，场馆必须属于机构；请求中的资源ID必须与当前身份授权校验。公开注册不得授予机构或平台特权。
- 不在启动或测试中自动迁移外部/旧数据库。测试只使用本目录隔离临时库；本地开发数据放 `var/`。
- RTMO-l Large、COCO17、官方 Body7 仍为已确认的公开姿态模型默认；配置保存在 `configs/public_pose_baseline.json`，不代表已接入产品。
- 文档用简体中文；跨模块契约变更形成 OpenSpec/ADR 草案；正式范围、生产部署与生产数据操作由项目负责人决策。
- 实施结束记录真实测试和限制，任务状态以 Notion 为准，不虚构日期或 Agent 用户。

## Monorepo 协作

- 项目负责人主责 `services/cloud/`、Cloud 根级依赖、核心数据模型、统一分析引擎、云边同步、共享契约和仓库级治理。Mike 主责 `services/edge-runtime/`、`apps/venue-console/`、`apps/personal-workbench/` 及其测试、构建和交付。部署及共享路径的归属见[工程组织说明](docs/engineering/monorepo.md)。
- 在模块责任范围内提交独立分支和 PR。修改其他模块、共享契约或仓库级 CI 前先取得对应负责人批准，并邀请受影响模块负责人评审。
- 每个模块维护自己的依赖、锁文件、构建和测试入口。Cloud 保留根级 `pyproject.toml`、`requirements-dev.lock` 和现有启动、迁移与测试路径。Edge 和前端依赖放在各自模块内。
- 跨模块使用版本化 API、DTO、JSON Schema 或事件契约。禁止跨模块导入 ORM、内部服务或数据库 Session，以及直接访问对方数据库。现有契约和 OpenAPI 快照保留在 `docs/contracts/`。
- 跨模块契约变更先在根级 OpenSpec 提案中列出消费者、兼容性和迁移安排，由项目负责人和受影响模块负责人评审，再同步实现与契约测试。按 Propose → Apply → Verify → Archive 保留证据，运行主规格与受影响 Change 的 strict 校验，归档保留历史。
- 模块变更运行该模块测试。Cloud 继续保留 SQLite、PostgreSQL 17 和隔离媒体存储验证。共享契约变更运行所有受影响消费者的契约测试。报告实际命令、结果与跳过项。
- 场馆部署只包含 Edge Runtime 和 Venue Console。个人工作台采用独立部署 Profile。分析接入使用统一引擎契约。
