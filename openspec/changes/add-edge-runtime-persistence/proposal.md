# Proposal

## Why

M4.1 已为 Edge 定义命令持久接收、业务接单、实际执行、离线事实与可靠补投，但仓库中的 Edge Runtime 仍只有 README scaffold。持久本地账本和可恢复的文件登记是安全实现这些边界的前置条件；进程重启不能重新接单、丢失已发生事实或改变待重试事件身份。

## What Changes

- 为 Edge Runtime 增加可独立运行的本地持久化基础，包含显式数据目录、独立版本化 Schema、Command Inbox/游标、本地 Task/Assignment、采集事实、事务 Outbox、安全挂起、文件登记及恢复记录。
- 规定命令接收、业务接单、采集事实、任务终态和 Outbox 的原子边界；文件写入使用暂存、校验、同卷原子发布与启动对账处理数据库/文件系统双写窗口。
- 定义离线、重启、取消、精确收据匹配、有界重试、`recovery_required` 和人工恢复行为；提供 MockCloudAdapter、确定性 Worker、可注入时钟/网络及故障注入验收要求。
- 本地隔离验证推荐 SQLite 文件数据库与 Edge 自有 SQLAlchemy/Alembic 环境；PostgreSQL/Redis 生产选择继续评估，不由本 Change 批准。
- **不包含** Cloud API/模型/迁移、真实双进程同步、真实摄像头/完整 Worker、完整媒体上传、Venue Console、分析算法、生产存储策略或生产安全通知通道。

## Capabilities

### New Capabilities

- `edge-runtime-persistence`: Edge 在进程重启和离线期间持久接收命令、维护本地任务/事实、稳定投递事件、登记文件并恢复或挂起不确定状态。

### Modified Capabilities

无。Cloud Identity、Edge Registry、TrainingSession、Media Asset/Authorization/Transfer 的正式行为保持不变；Edge Runtime 的新增行为由独立能力规格定义。

## Impact

- 目标模块：`services/edge-runtime/` 及其独立依赖、锁文件、迁移、测试和运行说明；根级 OpenSpec 新增行为 Delta。
- 本地数据：M4.2 隔离 CPU profile 使用独立 SQLite 文件和持久测试目录。首次创建/升级通过显式命令管理，服务启动校验版本，不静默迁移。
- 云边交互：只通过版本化 `CloudAdapter` 抽象和 `MockCloudAdapter` 验收 M4.2 本地行为。真实 Cloud 路由尚不存在，M4.3 负责 Cloud Sync Inbox/Projection，M4.4 负责双进程集成。
- 不修改 `services/cloud/`、Cloud 主规格、OpenAPI、现有迁移或 CI 工作流；不执行数据库迁移或业务代码实现。
