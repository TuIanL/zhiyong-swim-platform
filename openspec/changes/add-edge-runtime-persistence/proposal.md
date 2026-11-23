# Proposal

## Why

M4.1 已为 Edge 定义命令持久接收、业务接单、实际执行、离线事实与可靠补投，但仓库中的 Edge Runtime 仍只有 README scaffold。除持久账本外，Runtime 身份绑定、单实例写入、严格命令验证和可恢复升级也是防止跨 Node 错发历史事实、序号冲突或损坏账本的前置条件。

## What Changes

- 增加不可变 `LocalRuntimeIdentity`，将 Runtime 安装实例、Tenant、Site、Node 与本地数据目录绑定；启动先核对配置绑定，CloudAdapter 身份验证成功后才开放云端收发。凭据轮换保留原账本，作用域不符时禁止读取/发送旧 Outbox 或运行旧 Assignment。用操作系统级独占锁保护单目录运行、初始化和升级互斥。
- 严格执行 M4.1 下行协议：分页上限 50 条，单命令 JSON UTF-8 实际字节上限 8192，严格白名单、重复键/未知字段拒绝、版本/UUID/UTC/整数/方向校验，以及节点连续序号和持久固定 `round_through`；不合格命令不写 Inbox、不推进或 ACK Cursor。
- 明确 Runtime Readiness、Command Inbox/Cursor、Cloud 控制快照、本地 Task/Assignment、FileRecord、Node SafetyHold 与 Assignment 恢复状态机。Inbox/命令效果/Cursor、接单/accepted Outbox、事实/序号/Outbox 分别原子提交；SQLite 并发写入以数据库事务、唯一约束和条件更新保证不变量。
- 定义本地文件 `staging_intent → staged_verified → published → available` 状态、受控路径和同卷不可覆盖发布；覆盖 ENOSPC、fsync、EXDEV、符号链接/路径替换及缺失/损坏/孤立文件。原始字节不能因恢复失败自动删除。
- 为 Schema 升级使用 SQLite 一致性备份、候选库迁移与完整验证、受控切换及原库保留；规定启动必需账本扫描和历史文件分级校验/性能度量，不自动全库升级或以文件存在冒充哈希验证。
- 保留离线、取消、精确收据匹配、有界重试、`recovery_required`、多 Hold 聚合及人工恢复规则；用 MockCloudAdapter、FakeClock/FakeNetwork、确定性 Worker 和独立连接故障注入验收。
- 本地隔离验证推荐 SQLite 文件数据库与 Edge 自有 SQLAlchemy/Alembic 环境；PostgreSQL/Redis 生产选择、生产数据目录/容量/备份/保留、凭据存储和现场管理面仍待另行批准。
- **不包含** Cloud API/模型/迁移、真实双进程同步、真实摄像头/完整 Worker、完整媒体上传、Venue Console、分析算法、生产存储策略或生产安全通知通道。

## Capabilities

### New Capabilities

- `edge-runtime-persistence`: Edge 在进程重启和离线期间持久接收命令、维护本地任务/事实、稳定投递事件、登记文件并恢复或挂起不确定状态。

### Modified Capabilities

无。Cloud Identity、Edge Registry、TrainingSession、Media Asset/Authorization/Transfer 的正式行为保持不变；Edge Runtime 的新增行为由独立能力规格定义。

## Impact

- 目标模块：`services/edge-runtime/` 及其独立依赖、锁文件、迁移、测试和运行说明；根级 OpenSpec 新增行为 Delta。
- 本地数据：M4.2 隔离 CPU profile 使用独立 SQLite 文件和持久测试目录。显式初始化写入不可变 RuntimeIdentity；初始化、运行和 Schema 升级互斥；升级先备份并在候选库验证后切换。服务启动不静默迁移。
- 云边交互：只通过版本化 `CloudAdapter` 抽象和 `MockCloudAdapter` 验收 M4.2 本地行为；无当前认证时可按已绑定身份本地离线恢复，但云端收发暂停。真实 Cloud 路由尚不存在，M4.3 负责 Cloud Sync Inbox/Projection，M4.4 负责双进程集成。
- 不修改 `services/cloud/`、Cloud 主规格、OpenAPI、现有迁移或 CI 工作流；不执行数据库迁移或业务代码实现。
