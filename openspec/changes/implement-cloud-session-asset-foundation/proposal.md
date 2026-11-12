# Proposal

## Why

main 已有账号/机构/场馆与 Cloud Edge Registry 共10张业务表、21 paths / 31 operations，但[已批准的采集媒体契约](../../../docs/contracts/cloud-capture-media.md)中 TrainingSession、VideoAsset、UploadSession 与资源读取授权仍「无表无接口」。平台现在能登记设备和凭据，却没有任何训练业务记录、没有视频逻辑资产、也无法回答「哪位教练可以看哪次训练」。M2 必须先把业务资源与资源级读取授权做实，才能让 M3 的二进制上传、校验与播放有合法落点；不允许先开放无授权的媒体壳，也不允许先造人工专用来源模型再重写。

## What Changes

- **阶段授权**：本轮仅 Propose。规划、strict/内容核对、Draft PR、Notion 回链为本次交付；Apply、Verify、Archive、主规格同步、Merge 均未授权。下列全部为拟实施内容。
- **M2 范围（本 Change）**：新增 `training_sessions`、`video_assets`、`upload_sessions`、`session_read_grants`、`asset_read_grants` 五张表；扩展既有 `idempotency_records` 以支持 Edge 主体；拟新增12 paths / 16 operations（总数变为33 paths / 47 operations）；既有19 + 12个操作保持不变。
- **上传意图原子性**：`POST …/upload-sessions`（用户）与 `POST /api/v1/edge/sessions/{session_id}/upload-sessions`（节点）在同一事务内创建 `VideoAsset(pending_upload)` + `UploadSession(uploading)`；全平台不提供任何裸 Asset 创建接口。M2 不提供 part-urls / complete，因此 M2 内资产只能经 abort 或过期进入 `failed`，**任何路径都不会产生 `ready`**。
- **M2/M3 切分（详见 [design](design.md)）**：M2 = 业务资源元数据 + 资源读取授权 + 上传意图登记与终态配对（aborted / expired / session_cancelled）+ 懒物化过期；M3 = 分片与短时 URL、断点续传、整对象 bytes/SHA-256/媒体元数据校验、`completed → ready` 原子配对、播放 URL、可重试过期清扫与孤儿对象清理。切分不破坏已批准的业务原子性：资产与上传意图永远同事务创建，`ready` 永远只由整对象校验产生。
- **资源授权**：实现 S-read / S-manage / A-read 三项能力与 `SessionReadGrant` / `AssetReadGrant` 物理持久化（软撤销 + 部分唯一索引）；Session grant 在其有效期内覆盖该 Session 当前与未来新增的全部 Asset（含后续派生 Asset），撤销只移除该路径；显式 Asset grant 只覆盖目标 Asset。教练的场馆授权仍只是前置条件，不能代替资源级授权。
- **权限矩阵**：Owner/Admin 在本机构范围内管理与读取，不依赖显式 SiteMembership；Coach 需机构成员 + 该 Site 访问 + 创建者身份或有效 grant；读取不授予管理、上传或转授权；Coach 不能向他人授予 grant。
- **不实施**：分片/断点续传/整对象校验/播放 URL/对象存储与 MediaBlob、Edge Runtime 与离线同步（Outbox/Inbox、ID 映射、冲突裁决）、分析任务与结果、报告/PDF、Web/移动端、学员档案与教练—学员关系、Pool/Lane、RLS、生产部署与真实学员视频。四实体均无 DELETE。
- **未冻结项**：对象存储产品/区域、分片大小与数量、整对象校验实现、播放 URL 上限实现值、保留与处置策略、MediaBlob 是否独立建表。M2 只定义这些能力所需的契约边界，不选型、不建表、不写死参数。
- 复用 Notion 既有任务建立回链，不新建任务：[P0 媒体上传/绑定/下载授权](https://app.notion.com/p/410f602574aa811094bec51f53fe50e3)、[P0 租户隔离与 RBAC](https://app.notion.com/p/410f602574aa816e87dcd70f56c4100e)、[P0 数据模型与历史资产取舍](https://app.notion.com/p/410f602574aa811bbad3c6e452a065b6)、[P0 架构与接口契约基线](https://app.notion.com/p/410f602574aa816582ccc14817ce4601)、[P1 云端视频分片上传与完整性校验](https://app.notion.com/p/410f602574aa8129ab07d088ad80aa5b)、[P1 教练-学员授权关系与学员档案](https://app.notion.com/p/410f602574aa810eb1f2e547f585ffcc)。

## Capabilities

### New Capabilities

- `cloud-training-session`：TrainingSession 的建立、状态机（planned → recording → completed；planned/recording → cancelled）、终态不可逆、归属不可变、稳定游标列表与取消对未完成上传的同事务收口。
- `cloud-media-asset`：VideoAsset 的逻辑身份、origin 与来源配对（edge/manual/derived）、采集时间与时钟不确定性、声明值与服务端确认值的区分、UploadSession 生命周期与终态配对、资产与上传意图同事务创建、不提供裸 Asset 创建与 `ready` 旁路。
- `cloud-media-authorization`：S-read / S-manage / A-read 三项能力的判定语料、SessionReadGrant 与 AssetReadGrant 的持久化与撤销、未来资产覆盖、权限检查次序、403/404 分界与列表/游标的一谓词过滤。

### Modified Capabilities

- `cloud-identity`：修改 `Isolated database validation` 与 `PostgreSQL schema integrity` 两项，把已批准表集合由「六表基线 + Edge Registry 四表」扩为「再加本 Change 五张表」共15张，并保持容器实际归属、应用最小权限、DDL/版本表拒绝与清理非零传播等全部原保证。其余8项要求与 Purpose 不变；本轮只写增量，不同步主规格。

## Impact

- 事实基线 main@57e91a5（PR #4 合并）。输入为 [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) D1–D10、[领域模型](../../../docs/architecture/cloud-capture-media-domain.md)、[API 契约](../../../docs/contracts/cloud-capture-media.md)、[Cloud Edge Registry 模型](../../../docs/architecture/cloud-edge-registry-domain.md)与 [P0/P1 路线](../../../docs/planning/2026-11-10-p0-p1-roadmap.md)；这些是已评审方向，不是已实现事实。
- Apply 将触及 `services/cloud` 的模型 / 新增迁移 `0003` / 路由与输入输出 / 两后端测试 / OpenAPI 快照 / 领域与契约文档；复用现有 identity、membership、manager、site_access、Edge 凭据认证与幂等工具，不复制注册或跨目录 import。
- **迁移风险**：`idempotency_records` 现有 `operation` / `resource_kind` CHECK 与 `(tenant_id, site_id, user_id, operation, target_id, key_hash)` 唯一约束需扩展为按主体（user / edge_node）区分；SQLite 需 batch 重建该表，PostgreSQL 需替换约束与索引。既有12个 Registry 操作与19个基础操作的回归断言不得修改或删除。
- 测试基线从「六表 + 四表」变为15表批准集合；`pg_support.APPROVED_APP_TABLES`、`test_postgresql_schema`、`test_postgresql_identity` 的固定集合需同步扩展，并用未批准 canary 表证明授权未放宽。
- 不新增队列、对象存储、GPU 或外部服务依赖；不连接旧库、生产库或真实学员视频；本阶段只用合成数据设计与验收。
- 已存在的六表 CASCADE 语义不变；新增父级外键一律 RESTRICT，因此未来删除带历史的 Site/Tenant 会被拒绝而非级联抹除（当前无该删除端点，不构成行为回归）。
