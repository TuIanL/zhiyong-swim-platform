# Design

## Context

动机与拟实施范围见 [proposal](proposal.md)。设计输入是已评审的 [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) D1–D10、[领域模型](../../../docs/architecture/cloud-capture-media-domain.md)、[API 契约](../../../docs/contracts/cloud-capture-media.md)、已实现的 [Cloud Edge Registry](../archive/2026-11-11-implement-cloud-edge-device-foundation/design.md) 与本轮 [P0/P1 路线](../../../docs/planning/2026-11-10-p0-p1-roadmap.md)。这些是方向，不是已实现事实。

main@57e91a5 的真实基线：10 张业务表、21 paths / 31 operations。可复用的实现事实：

- [api.py](../../../services/cloud/src/swimplatform/api.py) 提供 `identity`、`membership`（非成员 404）、`manager`（角色不足 403）、`site_access`（owner/admin 免显式 SiteMembership）与 `as_utc` 瞬间归一；`fail()` 统一 `detail.code/message`。
- [edge_registry.py](../../../services/cloud/src/swimplatform/edge_registry.py) 提供 `get_edge_identity`、`lock_node`/`lock_manager_node`（PG 行锁、SQLite 条件写）、`commit_idempotently`、`idempotency_key_digest`、`request_digest` 与 `server_now` 时钟缝。
- [models.py](../../../services/cloud/src/swimplatform/models.py) 已有复合 `UNIQUE (tenant_id, site_id, id)` 与 `ForeignKeyConstraint` 的 RESTRICT 模式；[迁移 0002](../../../services/cloud/src/swimplatform/migrations/versions/20261110_0002_cloud_edge_registry.py) 展示增量迁移与列约束命名。
- 测试侧 [pg_support.py](../../../services/cloud/tests/pg_support.py) 的 `APPROVED_APP_TABLES` 是10张的显式集合，[test_postgresql_schema.py](../../../services/cloud/tests/test_postgresql_schema.py) 用 `TABLES | REGISTRY_TABLES` 断言表集合，[test_postgresql_identity.py](../../../services/cloud/tests/test_postgresql_identity.py) 用 `len(APPROVED_APP_TABLES)+1` 断言授权行数。新增表必须显式扩展这些集合，不能改成 `ALL TABLES`。

### 已实现事实与待设计实体的分界

| 类别 | 实体 | 本轮处理 |
| --- | --- | --- |
| 已实现 | users、auth_sessions、tenants、tenant_memberships、sites、site_memberships | 不改表结构，只新增指向它们的受限外键 |
| 已实现 | edge_nodes、devices、edge_credentials、idempotency_records | 不改前三表；第四表需**受控扩展**以支持 Edge 主体 |
| 待设计→本 Change 建表 | training_sessions、video_assets、upload_sessions、session_read_grants、asset_read_grants | 本 Change 建表并实现 |
| 支持概念，本轮不建 | MediaBlob、upload parts 明细、Outbox/Inbox、分析任务与结果、Pool/Lane | 明确排除，见 Non-Goals |

## Goals / Non-Goals

**Goals:** 在无对象存储、无真实视频、无 GPU 的隔离环境中，交付「训练会话 + 逻辑视频资产 + 资源级读取授权 + 上传意图登记」的可独立验收切片；让 S-read / S-manage / A-read 在 SQLite 与 PostgreSQL 上都有可重放证据；让 M3 的二进制能力可以只新增而不推翻本片模型。

**Non-Goals:** 分片、断点续传、短时上传 URL、整对象校验、播放 URL、对象存储选型、MediaBlob、孤儿对象清理、Edge Runtime 与离线同步、分析/结果/报告、Web/移动端、学员档案与教练—学员关系、Pool/Lane、RLS、生产部署、真实学员视频。四实体均不提供 DELETE。

## Decisions

以下 D14–D21 为本轮**提案**，不是已批准决策；D11–D13 已由上一切片确认，本 Change 不复用它们的授权。

### D14 M2/M3 切分：以「能否产生 ready」为分界线

切分不按代码目录或工作量，而按**可观察不变量**划分：一个切片是否可以产生 `ready` 资产。

- M2（本 Change）交付：Session 全生命周期、Asset 逻辑身份与来源、上传意图的原子创建、上传意图的终态配对（aborted / expired / session_cancelled）、懒物化过期、S-read/S-manage/A-read 与全部读取路径、过滤式游标分页。
- M3 接手：part URL 与分片回执、断点续传查询、`complete` 与整对象 bytes / SHA-256 / 媒体元数据校验、`completed → ready` 原子配对、播放 URL 签发、可重试的过期清扫作业、孤儿对象清理、cancel-vs-complete 竞态。
- **M2 内不存在任何能把 Asset 置为 `ready` 的路径**。因此 M2 的验收不得包含播放、下载、checksum 非空或 ready 资产；M2 创建的资产在 abort/过期/Session 取消后进入 `failed`，不会永久悬空。

替代方案与否决理由：

| 替代 | 否决理由 |
| --- | --- |
| A：M2 只建表与 grant，Asset 由测试直接插库产生 | 这正是路线图禁止的「以测试 fixture 冒充业务闭环」；授权测试将建立在业务不可达的数据上 |
| B：M2 也交付 UploadSession 但允许一次性 PUT 完成 | 一次 PUT 无法承接 C1 的分片/续传/整对象校验范围，且会以单次请求冒充完整性证明 |
| C：M2 用内存/临时目录假实现存储与校验以产出 ready | 提前冻结存储与校验实现，且产出「看起来已校验」的 ready，违反已批准契约 |
| D：把 UploadSession 整体推迟到 M3，M2 只交付 Session | Asset 无任何创建入口，VideoAsset 表在 M2 内恒为空，来源/采集时间/派生约束全部无法验收 |

采用本切分后仍满足已批准的业务原子性：**Asset 与 UploadSession 永远同事务创建**（D19），**ready 永远只由整对象校验产生**（M3），**不存在裸 Asset 创建接口**（任何切片都不提供）。

### D15 资源读取授权的物理模型：两张表 + 软撤销 + 部分唯一索引

采用 `session_read_grants` 与 `asset_read_grants` 两张结构同形的表，而不是单张多态 `resource_read_grants`。

- 理由：多态表无法用复合外键约束到两个不同的父实体，只能由写服务自查，这与本项目「用复合外键表达父子归属一致」的既有取向冲突；而授权表是权限判定核心，不能把一致性降级为应用约定。
- 撤销采用 `revoked_at` / `revoked_by_user_id` 软撤销，与 `edge_credentials` 的既有模式一致，并让「谁在何时撤权」可追溯；重复撤销不覆盖首次执行者与时间（沿用 Registry W3 修复后的语义）。
- 「同一资源对同一受授人只有一条有效授权」由**部分唯一索引**保证：`UNIQUE (tenant_id, site_id, <resource>_id, grantee_user_id) WHERE revoked_at IS NULL`。SQLite 与 PostgreSQL 都支持部分索引，但必须在两后端各写一条断言。
- `PUT` 的语义是 upsert：存在未撤销记录时更新 `expires_at` 与 `updated_at`，保留首次 `granted_at` / `granted_by_user_id`；不存在时插入。已过期但未撤销的记录被 PUT 刷新即视为重新授权，从而不产生第二条有效行。
- 到期不落库、不清扫：`expires_at` 只是判定谓词的一部分（`expires_at IS NULL OR expires_at > now`），所以 grant 过期无需后台作业。

### D16 权限判定次序与 403/404 分界

判定次序固定为：身份（401）→ 机构成员（404 `tenant_not_found`）→ 场馆归属与访问（404 `site_not_found`）→ 资源范围（404 具体资源码）→ 能力（403 `forbidden`）。字段、枚举、空 PATCH、未知字段为 422；合法枚举但状态机不允许为 409。

两类操作在「先查资源还是先查角色」上不同，这是有意的：

| 操作类 | 次序 | 理由 |
| --- | --- | --- |
| 读取类（Session/Asset 详情、子列表、游标续页） | 先按 (tenant, site, id) 取资源，取不到 404；取到后若不具备 S-read/A-read 仍 404 | 不泄露「存在但你看不到」这一事实 |
| 管理类（PATCH、grant PUT/DELETE、上传意图） | 先验角色与场馆（403/404），再按 scope 取资源（404） | 与既有 Registry 的 `require_manager_site` 一致；不因猜测 ID 获得资源存在性信息 |

「已可读但无权写」是唯一返回 403 的读取侧情形：调用者具 S-read 但不是创建者也无 S-manage 时 PATCH 返回 403，因为该资源对他已公开可见，403 不增加泄漏。

能力定义与判定（`u` 为调用者，`now` 为服务端时刻）：

| 能力 | 判定 |
| --- | --- |
| S-read | `role ∈ {owner, admin}`；或 `member ∧ site_membership(u, site) ∧ (session.created_by_user_id = u ∨ ∃ active session_read_grant(session, u))` |
| S-manage | `role ∈ {owner, admin}`；或 `session.created_by_user_id = u ∧ member ∧ site_membership(u, site)` |
| A-read | `role ∈ {owner, admin}`；或 `member ∧ site_membership(u, site) ∧ (asset.created_by_user_id = u ∨ ∃ active asset_read_grant(asset, u) ∨ S-read(asset.session_id, u))` |

`active grant` = `revoked_at IS NULL ∧ (expires_at IS NULL ∨ expires_at > now)`。三项能力必须由**同一个谓词构造器**产出，列表、详情、子列表、游标续页共用，禁止各处手写不同条件。

Owner/Admin 不依赖 `site_memberships`；其范围是「当前 tenant 内全部 site」，且不跨机构。Coach 的 Site 访问只是前置条件，永远不能替代资源级判定。

### D17 Session 状态机与并发裁定

状态与时间字段的对应关系由数据库 CHECK 与 API 双重保证：

| 状态 | started_at | completed_at | cancelled_at | 允许进入自 |
| --- | --- | --- | --- | --- |
| planned | NULL | NULL | NULL | 创建 |
| recording | 非空 | NULL | NULL | planned |
| completed | 非空 | 非空 | NULL | recording |
| cancelled | 任意 | NULL | 非空 | planned、recording |

- `planned → completed` 不允许（409），因为已批准契约只列出 `planned → recording → completed`。
- 终态不可回退；重复提交当前状态返回 200 且不重写时间字段（幂等重试友好）。
- 并发：PostgreSQL 用 `SELECT … FOR UPDATE` 锁住 `(tenant_id, site_id, id)` 范围内的会话行；SQLite 用带 scope 谓词的条件 `UPDATE` 取得写锁后再做状态判断，沿用 `lock_manager_node` 已验证的模式，不引入进程内互斥。
- 迁移合法性判断必须基于**加锁后重新读取**的当前状态，不能用请求开始时的快照。

### D18 取消与过期：两侧终态在同一事务配对

- 取消 Session：先锁会话行，再 `UPDATE upload_sessions SET status='failed', failure_reason='session_cancelled' WHERE session_id=? AND status IN ('uploading','completing')`，再 `UPDATE video_assets SET status='failed', failure_reason='session_cancelled' WHERE session_id=? AND status='pending_upload'`，最后写会话 cancelled。任一语句失败则整体回滚，不允许出现「会话已取消但资产仍 pending_upload」。
- 因为每个 pending 资产恰有一条上传会话（`upload_sessions.asset_id` 唯一），两条 UPDATE 覆盖的是同一批业务对象；取消场景下原因统一为 `session_cancelled`，不会出现两侧原因不一致。
- 取消与中止并发：两者都对同一行做条件更新，只有一个事务的行数不为 0；落败方重新读取并返回已提交终态。取消先赢则该上传会话原因为 `session_cancelled`，中止先赢则原因为 `upload_aborted`，后到的取消不再改写原因。
- 取消后新建上传意图返回 409 `state_conflict`。completed 会话可以继续接收上传意图（契约允许合规补传），但 status 不回退。

### D19 上传意图：原子创建、失败原因词表、懒物化过期

创建路径只有两条：用户路径（`S-manage`，发起人=当前用户）与 Edge 路径（节点凭据、Session 同 tenant/site、device 属该节点且 active）。两者都在一个事务内 `INSERT video_assets` + `INSERT upload_sessions`，任何一侧失败则回滚。

- `upload_sessions.asset_id` 唯一，保证「一个逻辑资产恰有零或一条上传意图」。
- 失败原因使用**一次定义、封闭**的词表：`upload_aborted`、`upload_expired`、`session_cancelled`、`upload_failed`、`validation_failed`。M2 只能产生前三个（`upload_failed` 保留给 M3 的分片/传输失败，`validation_failed` 保留给整对象校验失败），并在 CHECK 中一次性写入，避免 M3 再改约束。
- `expires_at` 由服务端按 `created_at + 默认 24 小时` 写入，上限 7 天；判定只用服务端时钟，读取、重试、心跳都不延长。
- 过期**懒物化**：只有对该上传会话的读取或中止请求会把 `uploading` 且已过期的记录原子终结为 `expired` + 资产 `failed(upload_expired)`。M2 不引入后台作业；因此会话列表/资产列表可能短暂显示已过期但未物化的 `pending_upload`，这是本切片的已知限制，由 M3 的可重试清扫作业收口。M2 的验收必须按单资源读取断言过期语义，不能把列表瞬时状态当作缺陷或当作已实现清扫。

### D20 幂等记录按主体扩展（迁移风险最高的一项）

`idempotency_records` 现为纯用户主体：`user_id` 非空、`operation` 与 `resource_kind` 是封闭 CHECK、唯一约束含 `user_id`。Edge 上传意图没有用户，必须扩展：

| 变更 | 内容 |
| --- | --- |
| 新增列 | `actor_kind`（`user`/`edge_node`，非空，默认 `user` 用于回填既有行）、`edge_node_id`（可空） |
| 可空性 | `user_id` 改为可空 |
| 新外键 | `(tenant_id, site_id, edge_node_id) → edge_nodes(tenant_id, site_id, id)` RESTRICT |
| 主体配对 | `(actor_kind='user' ∧ user_id 非空 ∧ edge_node_id 空) ∨ (actor_kind='edge_node' ∧ user_id 空 ∧ edge_node_id 非空)` |
| 词表扩展 | `operation` 增加 `training_session.create`、`upload_intent.create`；`resource_kind` 增加 `training_session`、`upload_session` |
| 唯一性 | 删除原唯一约束，改为两条部分唯一索引：用户域 `(tenant_id, site_id, user_id, operation, target_id, key_hash) WHERE actor_kind='user'`，节点域同形但以 `edge_node_id` 代替 `user_id` |

选择扩展而非新建第二张表：两套幂等机制会产生两套保留/重试语义，且 Edge 与用户在同一次「上传意图」上必然并存。代价是触及既有表，因此：

- SQLite 需 `batch_alter_table` 重建该表，PostgreSQL 需 drop/add 约束与索引；两后端都要有「升级 → 降级到 0002 → 再升级」的往返用例。
- 既有 12 个 Registry 操作的幂等测试断言**不得修改**，必须原样通过；这是本片最高优先级的回归门槛。
- 用户域与节点域的键不得互相碰撞（同一字符串在两域可各自成立），由部分索引的作用域保证。

替代：若负责人不接受改动共享表，则 Edge 上传意图整体推迟到 M3，M2 只保留用户路径；代价是 M2 无法验收设备来源，且 M3 要同时引入来源模型与传输模型。见待裁决 Q11。

### D21 采集时间与声明值的信任边界

- 原始设备时间两个字段**按字面值保存**：不裁剪、不规范化、不解析。字段级 `strip_whitespace=False`，沿用 `observed_at_raw` 已验证的做法。
- `device_time_basis` 为显式枚举，`unknown` 是合法终态值，表示「不知道」而非「缺失」。
- 服务端**不从原始字符串推导 UTC**：`capture_started_at_utc` / `capture_ended_at_utc` 只接受调用方显式提供，并在库层与字段层双重校验与基准自洽（见下表）。原始字符串解析格式、设备时钟对齐算法不在本片范围。
- `media_type` / `size_bytes` 在 `ready` 之前是**声明值**；`checksum_sha256` 只能由整对象校验写入。库层用「`ready` ⇒ `checksum_sha256`、`received_at`、`size_bytes`、`media_type` 全部非空」把「无校验不得 ready」变成数据库约束，而不只是代码约定。
- `received_at` 与 `created_at` 由服务端生成；响应里设备时间保留原始值与基准，不与服务端时间混用。

| 基准 | 必填 | 必须为空 | UTC 字段 |
| --- | --- | --- | --- |
| `utc` | — | `device_timezone`；`device_utc_offset_minutes` 只能为 NULL 或 0 | 允许 |
| `offset` | `device_utc_offset_minutes`（−840…840 整数分钟） | `device_timezone` | 允许 |
| `iana_timezone` | `device_timezone`（合法 IANA） | `device_utc_offset_minutes` | 允许 |
| `unknown` | — | `device_timezone`、`device_utc_offset_minutes`、两个 UTC 字段 | 禁止 |

## 物理模型

五张新表。UUID 存 `String(36)`、时间为 `DateTime(timezone=True)`、`video_timebase_metadata` 用 JSON；沿用现有命名前缀 `uq_` / `fk_` / `ck_` / `ix_`。

### training_sessions

| 列 | 类型/可空 | 约束 |
| --- | --- | --- |
| id | String(36) / 非空 | 主键 |
| tenant_id, site_id | String(36) | `UNIQUE (tenant_id, site_id, id)`；复合 FK → `sites(tenant_id, id)` RESTRICT |
| created_by_user_id | String(36) | FK → `users(id)` RESTRICT |
| title | String(120) / 可空 | `length(trim(title)) BETWEEN 1 AND 120` |
| status | String(16) | `planned/recording/completed/cancelled`；与三个时间列的组合 CHECK |
| started_at, completed_at, cancelled_at | 可空 | `started_at >= created_at`、`completed_at >= started_at`、`cancelled_at >= created_at` |
| created_at, updated_at | 非空 | 服务端写入，`created_at` 不可变 |

索引：`(tenant_id, site_id, created_at, id)` 供游标；`(tenant_id, site_id, created_by_user_id, created_at, id)` 供「我创建的」谓词。

### video_assets

| 列 | 类型/可空 | 约束 |
| --- | --- | --- |
| id | String(36) | 主键 |
| tenant_id, site_id, session_id | String(36) | `UNIQUE (tenant_id, site_id, session_id, id)`；复合 FK → `training_sessions` RESTRICT |
| origin | String(16) | `edge/manual/derived` |
| created_by_user_id | String(36) / 条件可空 | `manual` 必填、其余必须为空；FK → `users(id)` RESTRICT |
| source_edge_node_id, source_device_id | String(36) / 成对可空 | `edge` 必填、其余必须为空；复合 FK `(tenant_id, site_id, source_edge_node_id, source_device_id)` → `devices(tenant_id, site_id, edge_node_id, id)` RESTRICT |
| derived_from_asset_id | String(36) / 可空 | 复合 FK `(tenant_id, site_id, session_id, derived_from_asset_id)` → 本表同四列，RESTRICT；`CHECK (id <> derived_from_asset_id)` |
| status | String(20) | `pending_upload/ready/failed` |
| failure_reason | String(32) / 可空 | 封闭词表；`failed` ⇔ 非空 |
| capture_started_at_utc, capture_ended_at_utc | 可空 | 两端已知时 `started <= ended` |
| device_capture_started_at_raw, device_capture_ended_at_raw | String(64) / 可空 | 字面值保存，不解析 |
| device_time_basis | String(16) | `utc/offset/iana_timezone/unknown` |
| device_timezone | String(64) / 可空 | 合法 IANA（应用层校验），与基准配对 |
| device_utc_offset_minutes | Integer / 可空 | −840…840，与基准配对 |
| video_timebase_kind | String(16) | `relative/wall_clock/unknown` |
| video_timebase_metadata | JSON / 可空 | 原样对象，不构造虚假映射 |
| device_clock_source | String(16) | `ntp/ptp/gps/manual/unknown` |
| device_clock_offset_ms, device_clock_accuracy_ms | Numeric(12,3) / 可空 | 精度 `>= 0`；未知留空，不填 0 |
| received_at | 可空 | 服务端首次收到对象时间；M2 恒为空，M3 写入 |
| media_type | String(128) / 可空 | ready 前为声明值 |
| size_bytes | BigInteger / 可空 | `> 0` |
| checksum_sha256 | String(64) / 可空 | 64 位小写十六进制；`ready` ⇒ 非空 |
| created_at, updated_at | 非空 | 服务端写入 |

关键 CHECK：`ready` ⇒ `checksum_sha256`、`received_at`、`size_bytes`、`media_type` 均非空；`failed` ⇒ `failure_reason` 非空；非 `failed` ⇒ `failure_reason` 为空。checksum **没有**唯一索引。

索引：`(tenant_id, site_id, session_id, created_at, id)`、`(tenant_id, site_id, created_by_user_id)`。

### upload_sessions

| 列 | 类型/可空 | 约束 |
| --- | --- | --- |
| id | String(36) | 主键 |
| tenant_id, site_id, session_id, asset_id | String(36) | `UNIQUE (asset_id)`；复合 FK `(tenant_id, site_id, session_id, asset_id)` → `video_assets` RESTRICT |
| status | String(16) | `uploading/completing/completed/failed/aborted/expired` |
| initiator_user_id, initiator_edge_node_id | String(36) / 成对可空 | 恰一非空；用户 FK → `users` RESTRICT；节点复合 FK → `edge_nodes` RESTRICT |
| failure_reason | String(32) / 可空 | 与 status 配对（终态失败类必须非空） |
| expected_size_bytes | BigInteger | `> 0` |
| expected_sha256 | String(64) | 64 位小写十六进制 |
| media_type | String(128) / 可空 | 声明值 |
| expires_at | 非空 | `> created_at`；上限由服务端参数控制 |
| completed_at | 可空 | 与本切片无关，`completed` ⇔ 非空 |
| created_at, updated_at | 非空 | 服务端写入 |

索引：`(tenant_id, site_id, session_id, status, expires_at)`。

`completing` / `completed` 在本切片不可达（M3 才产生），但 CHECK 已包含它们，避免 M3 再改约束。

### session_read_grants / asset_read_grants

两表同形，仅资源列不同（`session_id` 或 `asset_id`）：

| 列 | 类型/可空 | 约束 |
| --- | --- | --- |
| id | String(36) | 主键 |
| tenant_id, site_id, <resource>_id | String(36) | `session_read_grants` 复合 FK `(tenant_id, site_id, session_id)` → `training_sessions(tenant_id, site_id, id)` RESTRICT；`asset_read_grants` 复合 FK `(tenant_id, site_id, session_id, asset_id)` → `video_assets(tenant_id, site_id, session_id, id)` RESTRICT |
| grantee_user_id | String(36) | FK → `users` RESTRICT |
| granted_by_user_id | String(36) | FK → `users` RESTRICT；首次授予者不可改写 |
| granted_at, updated_at | 非空 | 首次授予时间 / 最近修改时间 |
| expires_at | 可空 | `> granted_at`（若提供） |
| revoked_at, revoked_by_user_id | 成对可空 | FK → `users` RESTRICT；`revoked_at >= granted_at` |

部分唯一索引：`(tenant_id, site_id, <resource>_id, grantee_user_id) WHERE revoked_at IS NULL`。查询索引：`(tenant_id, site_id, <resource>_id, grantee_user_id)`。

`asset_read_grants` 额外带 `session_id`，使其复合 FK 能同时锁定资产与其父会话归属一致；这也是「单 Asset grant 不得跨 Session」的结构保证。

### idempotency_records 扩展

按 D20 的六项变更执行。既有 `unique` 约束名 `uq_idempotency_scope_key` 删除，新增 `uq_idempotency_user_scope_key` 与 `uq_idempotency_edge_scope_key` 两条部分唯一索引。

## 端点

P = `/api/v1/tenants/{tenant_id}/sites/{site_id}`。共 12 paths / 16 operations，全部为拟新增；既有 31 个操作不变，完成后总数 33 paths / 47 operations。

| # | 方法 | 路径 | 能力/主体 | 请求 | 成功 |
| --- | --- | --- | --- | --- | --- |
| 1 | GET | P/training-sessions | S-read 过滤 | `status`、`limit`、`cursor` | 200 Page[SessionRead] |
| 2 | POST | P/training-sessions | Owner/Admin 或具 Site 访问的 Coach | SessionCreate + `Idempotency-Key` | 201 SessionRead |
| 3 | GET | P/training-sessions/{session_id} | S-read | — | 200 SessionRead |
| 4 | PATCH | P/training-sessions/{session_id} | S-manage | SessionPatch | 200 SessionRead |
| 5 | GET | P/training-sessions/{session_id}/video-assets | 先 S-read 再 A-read | `status`、`limit`、`cursor` | 200 Page[AssetRead] |
| 6 | GET | P/video-assets/{asset_id} | A-read | — | 200 AssetRead |
| 7 | PUT | P/training-sessions/{session_id}/read-grants/{user_id} | Owner/Admin | GrantPut | 204 |
| 8 | DELETE | P/training-sessions/{session_id}/read-grants/{user_id} | Owner/Admin | — | 204 |
| 9 | PUT | P/video-assets/{asset_id}/read-grants/{user_id} | Owner/Admin | GrantPut | 204 |
| 10 | DELETE | P/video-assets/{asset_id}/read-grants/{user_id} | Owner/Admin | — | 204 |
| 11 | POST | P/training-sessions/{session_id}/upload-sessions | S-manage，发起人=自己 | UploadIntentCreate + `Idempotency-Key` | 201 UploadIntentRead |
| 12 | GET | P/upload-sessions/{upload_session_id} | 原发起用户且仍具 S-manage | — | 200 UploadSessionRead |
| 13 | POST | P/upload-sessions/{upload_session_id}/abort | 原发起用户且仍具 S-manage | — | 204 |
| 14 | POST | `/api/v1/edge/sessions/{session_id}/upload-sessions` | 有效节点凭据；Session 同 tenant/site；device 属该节点且 active | EdgeUploadIntentCreate + `Idempotency-Key` | 201 UploadIntentRead |
| 15 | GET | `/api/v1/edge/upload-sessions/{upload_session_id}` | 原发起节点、有效凭据 | — | 200 UploadSessionRead |
| 16 | POST | `/api/v1/edge/upload-sessions/{upload_session_id}/abort` | 原发起节点、有效凭据 | — | 204 |

首版仍不提供：Session/Asset/UploadSession 的 DELETE、Edge 对他人上传的接管/完成、Edge 读取 Session/Asset、批量操作。

### 请求与响应模型

| 模型 | 字段与校验 |
| --- | --- |
| SessionCreate | `title?`（trim 后 1–120）；其余字段一律拒绝 |
| SessionPatch | `title?`、`status?`；至少一个非空字段，空 PATCH/含 null 为 422；不接受归属、创建者、历史时间 |
| GrantPut | `expires_at?`（必须带时区且严格晚于当前时刻）；受授人由路径决定 |
| CaptureMetadata | `device_capture_started_at_raw?`、`device_capture_ended_at_raw?`（各 ≤64，字面值）、`device_time_basis`、`device_timezone?`、`device_utc_offset_minutes?`、`video_timebase_kind`、`video_timebase_metadata?`（JSON 对象，序列化 ≤8 KiB）、`device_clock_source`、`device_clock_offset_ms?`、`device_clock_accuracy_ms?`；按 D21 表做交叉校验 |
| UploadIntentCreate | `expected_size_bytes`、`expected_sha256`、`media_type?`、`capture_metadata` |
| EdgeUploadIntentCreate | `device_id`、`expected_size_bytes`、`expected_sha256`、`media_type?`、`capture_metadata`；来源由凭据解析，不接受自报节点或场馆 |
| SessionRead | id、tenant_id、site_id、created_by_user_id、title、status、started_at、completed_at、cancelled_at、created_at、updated_at |
| AssetRead | id、tenant_id、site_id、session_id、origin、created_by_user_id、source_edge_node_id、source_device_id、derived_from_asset_id、status、failure_reason、capture_*（与请求同名同值）、video_*、device_clock_*、received_at、media_type、size_bytes、checksum_sha256、created_at、updated_at |
| UploadSessionRead | id、asset_id、status、initiator（用户或节点二选一）、expected_size_bytes、expected_sha256、media_type、expires_at、confirmed_parts（本切片恒为空数组）、completed_at、failure_reason、created_at、updated_at |
| UploadIntentRead | `upload_session`、`asset` |
| Page[T] | `items[]`、`next_cursor?`；无 `total_count` |

Asset API 不暴露 `storage_object_ref`（本切片无该列），不暴露对象 key。

### 错误码

新增 `training_session_not_found`、`video_asset_not_found`、`upload_session_not_found`、`grantee_not_eligible`（422）、`invalid_cursor`（422）；复用既有 `tenant_not_found`、`site_not_found`、`forbidden`、`state_conflict`、`idempotency_conflict`、`unauthorized`（服务端已注册的 `edge_unauthorized` 用于 Edge 路径）。每个请求只应用与自身阶段一致的错误，检查次序按 D16。

## 分页与游标

- 排序固定为 `created_at DESC, id DESC`（不可变列，`started_at` 可空因此不作排序键）。
- `limit` 默认 20、上限 100、必须为正整数；实现取 `limit + 1` 行判断是否还有下一页。
- 游标是不透明 base64url 文本，载荷含版本、资源种类、tenant_id、site_id、筛选条件摘要、排序方向与（created_at, id）边界。校验任一不匹配返回 422 `invalid_cursor`。
- 游标**不做签名**：它不承担授权职责，服务端每页都用当前身份重新套用资源谓词，篡改只能改变取窗位置，无法越过谓词看到未授权资源。这一点必须在测试与文档中显式声明，避免被误读为能力令牌。
- 撤权后的续页只返回当前仍可见的资源；不得补占位、不得返回未授权计数。

## 事务与并发边界

| 场景 | 处理 |
| --- | --- |
| 会话创建 | 幂等记录 + 会话同事务；唯一冲突回滚后重读已提交结果 |
| 会话状态迁移 | PG 行锁 / SQLite 条件写；基于加锁后状态判定；同一目标状态重放为 200 无副作用 |
| 会话取消 | 单事务：锁会话 → 终结未完成上传 → 失败其 pending 资产 → 写 cancelled |
| 上传意图创建 | 单事务：Asset + UploadSession + 幂等记录；`asset_id` 唯一兜底 |
| 上传意图中止 | 条件更新 `uploading → aborted` 与资产 `pending_upload → failed`；已终态返回 204 不重写 |
| 上传意图过期 | 读取/中止时的条件更新 `uploading → expired`；与中止竞争只有一个行数为 1 |
| 授权写入 | 部分唯一索引裁定并发；冲突回滚后重读并返回 204 |
| 授权撤销 | 条件更新 `revoked_at IS NULL → now`；重复撤销不覆盖首次执行者 |

测试必须证明「并发是在独立物理连接上发生的」：沿用 `CONCURRENCY_POOL`（`pool_size=8`）并断言不同的 `pg_backend_pid()`，不得以单连接串行或超时冒充并发。

## 与既有体系的兼容性

| 面 | 影响与要求 |
| --- | --- |
| 表集合 | 10 → 15。`pg_support.APPROVED_APP_TABLES` 增加五张；`test_postgresql_schema` 的表集合断言改为三段并集；`test_postgresql_identity` 的行数断言随集合自动变化 |
| 授权不放宽 | 仍用显式表集合授权；未批准 canary 表必须继续无 DML；`USAGE`、版本表仅 `SELECT`、DDL/TRUNCATE/SET ROLE 拒绝全部保留 |
| 既有 19 + 12 操作 | 不改路径、字段、错误与检查次序；OpenAPI 只做增量 |
| `idempotency_records` | 见 D20；Registry 的幂等回归必须原样通过 |
| 六表级联 | 保持不变；新增外键一律 RESTRICT，因此带历史的 Site/Tenant 删除会被拒绝（当前无该删除端点） |
| 用户删除 | 新增 `users` 外键为 RESTRICT；当前无删除账号端点，不构成回归 |
| 时钟 | 复用 `server_now` 时钟缝，所有时间断言用可控时钟，不依赖真实等待 |
| 依赖 | 不新增第三方库；JSON 列用 SQLAlchemy `JSON`（SQLite 与 PostgreSQL 均支持） |

## 与既有契约文档的偏差

| 已批准契约/领域草案 | 本片处理 |
| --- | --- |
| 契约列出 21 个 Session/Asset/Upload 操作 | 本片实现其中 16 个；part-urls、complete、playback-url 留给 M3（5 个） |
| 契约的 `UploadSessionRead.confirmed_parts[]` | 本片恒为空数组，因为尚无分片回执；字段保留以免 M3 改响应形状 |
| 契约的播放 TTL ≤ 5 分钟 | 本片不实现播放，只在文档中保留该上限待 M3 使用 |
| 领域草案的「父 Asset 必须 ready 才能派生」 | 本片无派生创建入口，库层只保证同租户/场馆/会话与自引用禁止；ready 前置条件在引入派生路径的 Change 中校验 |
| 领域草案的 `storage_object_ref` | 本片不设该列；存储引用属 M3 |

## Risks / Trade-offs

1. **改动共享幂等表** 是本片最高风险项：SQLite 需重建表，PG 需替换约束。缓解：两后端往返迁移用例 + 12 个 Registry 幂等回归原样通过 + 失败路径显式回滚验证。
2. **M2 内资产必然走向 failed**：这是切片限制而非产品行为。缓解：文档与验收明确禁止把 pending/ready 混用，M2 不面向真实用户。
3. **懒物化过期** 会让列表短暂显示过期未终结记录。缓解：单资源读取的语义严格断言；M3 清扫作业是已知后续项，不在 M2 声称已实现。
4. **授权谓词三处复用**（列表、详情、子列表）容易漂移。缓解：单一谓词构造器 + 授权矩阵逐格测试（含跨机构、跨场馆、撤权、降级、成员移除）。
5. **部分唯一索引两后端差异**：必须以真实写入冲突验证，而不是只读 DDL。
6. **游标不签名**：仅影响取窗位置，不影响授权；以测试证明篡改游标无法越过谓词。
7. 资产读取路径的 OR 组合在数据量增大后可能变慢；索引按本片查询形态给出，长期查询计划在 M3 引入真实数据量后复核。

## Migration Plan

1. 新增 revision `20261112_0003`，`down_revision = 20261110_0002`；不改写 0001/0002。
2. 升级顺序：创建五张表（先 `training_sessions`，再 `video_assets`，再 `upload_sessions` 与两张 grant 表）→ 扩展 `idempotency_records`。降级顺序相反，且必须先删子表再改幂等表。
3. SQLite 的 `idempotency_records` 变更走 `batch_alter_table`；PostgreSQL 直接 drop/add 约束与索引。
4. 往返验证：空库 0001 → head；含六表数据 0001 → head；head → 0002 → head；受控失败后回滚且不留半成品。
5. 迁移脚本不创建角色、不授权限、不写生产凭据；角色授权仍由测试编排按显式表集合执行。
6. 完成后更新 OpenAPI 快照、领域/契约/RBAC 文档，并在两份文档中把「已实现 16 个操作」与「M3 未实现 5 个操作」分开标注。

## Notion 追溯

| Notion 任务 | 本 Change 承接 | 交付物 | 验收证据 |
| --- | --- | --- | --- |
| [P0 建立新版媒体上传、绑定与下载授权边界](https://app.notion.com/p/410f602574aa811094bec51f53fe50e3) | 上传者/机构/场馆归属、详情与资源授权、禁止绕过校验的裸路径 | 上传意图 + Asset 详情 + 两类 grant | 授权矩阵与跨机构/跨场馆负向用例；播放/下载明确留给 M3 |
| [P0 定义租户隔离与 RBAC 权限矩阵](https://app.notion.com/p/410f602574aa816e87dcd70f56c4100e) | S-read / S-manage / A-read 与 403/404 分界 | `cloud-media-authorization` 规格 | 逐格矩阵、撤权/降级/成员移除、游标续页 |
| [P0 评审新版数据模型与历史资产取舍边界](https://app.notion.com/p/410f602574aa811bbad3c6e452a065b6) | 五张新表的字段、复合键、可空性与不可变归属 | 迁移 0003 + 领域文档更新 | 两后端 schema 断言与约束负向用例 |
| [P0 建立系统架构与接口契约基线](https://app.notion.com/p/410f602574aa816582ccc14817ce4601) | 12 paths / 16 operations 的路径、字段、错误 | OpenAPI 快照 + 契约文档更新 | 路由与快照一致；既有 31 操作不变 |
| [P1 实现云端视频分片上传与完整性校验](https://app.notion.com/p/410f602574aa8129ab07d088ad80aa5b) | 仅提供前置契约（UploadSession 状态机、失败词表、过期语义、幂等作用域） | 设计边界 | 本片不实现分片/校验；不得把该任务标为已实施 |
| [P1 建设教练-学员授权关系与学员档案](https://app.notion.com/p/410f602574aa810eb1f2e547f585ffcc) | 明确排除：不实现学员档案、班组、监护人与教练—学员关系 | 无 | athlete 读取在本片一律不生效；关系授权留给该任务自己的 Change |

## 待负责人裁决

| 编号 | 事项 | 建议默认 | 若改变的影响 |
| --- | --- | --- | --- |
| Q10 | 受授人角色范围 | 仅 `coach`（契约原文）；`athlete` 在学员路径 Change 落地前不可作为受授人 | 放开 athlete 会提前耦合教练—学员任务 |
| Q11 | Edge 上传意图是否留在 M2（含 D20 的共享表扩展） | 留在 M2 | 移除则 M2 无设备来源创建路径，来源只能做 schema 级验收，M3 需同时引入来源与传输 |
| Q12 | 上传意图有效期参数 | 默认 24 小时、上限 7 天 | 参数化常量，不影响结构；变更只需改配置与测试 |
| Q13 | 接受「M2 内不存在 ready」的切片限制 | 接受 | 若要求 M2 即产出 ready，本 Change 必须并入 M3 的存储与校验，范围翻倍 |

## Future Considerations / Known Limitations

- M3 必须补：part URL 与分片回执表、`complete` 的 202/200 语义与幂等、整对象校验、`completed → ready`、播放 URL（TTL ≤ 5 分钟）、cancel-vs-complete 竞态、可重试过期清扫、孤儿对象清理。
- MediaBlob 是否独立建表、物理内容复用与引用回收仍待存储决策；本片不建表、不引入引用计数。
- 派生资产的创建路径、`ready` 父前置与跨 Session 共享禁止需在引入派生/转码的 Change 中单独评审。
- 学员端读取、教练—学员关系与监护人同意由 [P1 教练-学员任务](https://app.notion.com/p/410f602574aa810eb1f2e547f585ffcc) 自己的 Change 承接，本片不提供预留字段。
- Pool/Lane、保留与处置策略、审计事件系统、RLS 与生产部署均不在本片；本片不声称任何一项已具备。
