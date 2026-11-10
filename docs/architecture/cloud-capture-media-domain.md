# 云端采集与媒体领域模型

> **v0.1-draft／部分实现**
>
> 本文记录负责人于 2026-11-09 第二轮 Proposal 技术审阅通过的设计方向。EdgeNode、Camera Device、EdgeCredential已由implement-cloud-edge-device-foundation增量实现；TrainingSession、VideoAsset、UploadSession、授权关系与媒体API仍未实现。其他未来设计仍须由各自业务Change实现。

- OpenSpec Change：**define-cloud-capture-media-contracts**
- Proposal 基线：**main@afb0e5fce4c187c8d3c3d5607d2a675375c2a04d**
- 评审依据：本 Change 第二轮 Proposal 技术审阅通过，D1–D10 方向获批准；文档 Apply 获授权。业务实现仍需另一个行为 Change。
- 配套文档：[API 契约草案](../contracts/cloud-capture-media.md)、[ADR 0003](../decisions/0003-capture-media-domain-contracts.md)、[既有云端领域模型](cloud-domain-model.md)。

## 1. 范围与当前事实

本草案原先设计EdgeNode、Device、TrainingSession、VideoAsset四个实体。EdgeNode、Camera Device与EdgeCredential现由独立Change实现；TrainingSession、VideoAsset、UploadSession仍是未来设计。训练编排、学员档案及关系、分析任务/结果、对象存储选型、离线同步协议、RLS、生产部署均不在范围内。

当前已实现的云端包含初始六表以及Edge Registry四表；API为21 paths / 31 operations，其中基础身份19个，Edge Registry新增12个。Edge实现细节见[Cloud Edge Registry模型](cloud-edge-registry-domain.md)与[Registry API契约](../contracts/cloud-edge-registry.md)。本文中的TrainingSession、VideoAsset、UploadSession、授权及媒体存储图/字段/端点仍是未实施设计方向。

## 2. 概念 ERD 与基数

~~~mermaid
erDiagram
    TENANTS ||--o{ SITES : contains
    SITES ||--o{ EDGE_NODES : registers
    EDGE_NODES ||--o{ DEVICES : registers
    EDGE_NODES ||--o{ EDGE_CREDENTIALS : authenticates
    SITES ||--o{ TRAINING_SESSIONS : hosts
    TRAINING_SESSIONS ||--o{ VIDEO_ASSETS : contains
    DEVICES o|--o{ VIDEO_ASSETS : captures
    VIDEO_ASSETS o|--o{ VIDEO_ASSETS : derives
    VIDEO_ASSETS ||--o| UPLOAD_SESSIONS : upload_intent
    USERS ||--o{ TRAINING_SESSIONS : creates
    USERS o|--o{ VIDEO_ASSETS : user_creator
~~~

Tenant、Site、User是既有实体；本Change不改动其表结构。EdgeNode、Device和EdgeCredential已有独立增量实现；本草案中其余实体与UploadSession仍是未来设计。Session/Asset读取授权是权限语义叠加在资源上的概念关系，**不是已建表或现有API**。

| 关系 | 基数与必选性 | 推荐归属约束 |
| --- | --- | --- |
| Tenant → Site | 一个 Tenant 有零到多个 Site；每个 Site 必属一个 Tenant | 复用既有 sites(tenant_id,id) 归属模式；本 Change 不改该表 |
| Site → EdgeNode | 一个 Site 有零到多个节点；每个节点必属一个 Site 和 Tenant | EdgeNode 的 (tenant_id,site_id) 引用 sites；归属创建后不可变 |
| EdgeNode → Device | 一个节点有零到多台设备；每台 Device 必挂一个节点 | Device 的 (tenant_id,site_id,edge_node_id) 必须引用同机构/场馆的节点 |
| EdgeNode → EdgeCredential | 一个节点可有零到多份轮换凭据；每份凭据只属一个节点 | 凭据按摘要唯一并复合引用节点；明文只签发一次 |
| Site → TrainingSession | 一个 Site 有零到多个 Session；每个云端 Session 必属一个 Site/Tenant，不绑定唯一节点 | tenant_id/site_id 复合引用既有 Site；Session 归属不可变 |
| TrainingSession → VideoAsset | 一个 Session 有零到多个 Asset；每个 Asset 必属一个 Session | Asset 的 tenant/site/session 复合引用父 Session；创建后不可改归属 |
| Device → VideoAsset 来源 | 一台设备可产生零到多个 Asset；人工上传可无设备来源 | Edge 来源时节点和设备都必填且匹配；人工来源时二者都空；派生来源继承父 Asset |
| VideoAsset → 派生父 Asset | 一个父 Asset 可有零到多个派生 Asset；派生父关系可空 | 父子必须同 tenant/site/session；父 Asset 创建时已 ready；父引用不可变 |
| VideoAsset → UploadSession | 一个逻辑 Asset 恰有零或一条上传意图；每条上传意图只指向一个 Asset | 支持记录复合引用 Asset；失败或过期后的新采集意图使用新 Asset ID |

### 2.1 归属与复合键建议

以下唯一键和外键是设计建议，不是迁移：

| 实体 | 主键及候选复合唯一键 | 关键复合外键 |
| --- | --- | --- |
| EdgeNode | id；UNIQUE (tenant_id, site_id, id) | (tenant_id, site_id) → sites(tenant_id, id) |
| Device | id；UNIQUE (tenant_id, site_id, edge_node_id, id) | (tenant_id, site_id, edge_node_id) → EdgeNode(tenant_id, site_id, id) |
| TrainingSession | id；UNIQUE (tenant_id, site_id, id) | (tenant_id, site_id) → sites(tenant_id, id) |
| VideoAsset | id；UNIQUE (tenant_id, site_id, session_id, id) | (tenant_id, site_id, session_id) → TrainingSession(tenant_id, site_id, id)；派生父键复用同一 tenant/site/session；设备来源键 → Device(tenant, site, edge_node, id) |
| EdgeCredential | id；token_hash UNIQUE | (tenant_id, site_id, edge_node_id) → EdgeNode(tenant, site, id) |
| UploadSession | id；asset_id UNIQUE | (tenant_id, site_id, session_id, asset_id) → VideoAsset(tenant, site, session, id) |

这些复合键用于表达父子归属一致性；实现时还需核对目标数据库对复合唯一键、可空列和约束检查时机的支持。派生环、origin 与来源列配对、互斥上传主体、状态迁移及授权决策不应声称仅靠这些外键就能保证。

### 2.2 索引建议

建议在业务实施 Change 中按真实查询计划复核，而不是直接照搬为 DDL：

- EdgeNode：(tenant_id, site_id, status, id)；必要时按 site/status 查询活跃节点。
- Device：(tenant_id, site_id, edge_node_id, status, id)。
- TrainingSession：(tenant_id, site_id, created_at, id)；按稳定游标读取；可评估 (tenant_id, site_id, status, created_at, id)。
- VideoAsset：(tenant_id, site_id, session_id, created_at, id)；支持会话内稳定游标；checksum 不建立逻辑唯一索引。
- EdgeCredential：token_hash 唯一索引；复合归属字段索引视凭据认证查询形态决定。
- UploadSession：(tenant_id, site_id, session_id, status, expires_at)；asset_id 唯一索引。
- 面向授权的索引只在授权记录物理模型经后续设计后选择；本 Change 不假设授权表存在。

## 3. 字段设计方向

类型是概念取向：UUID 标识、UTC 时间戳、短枚举、有限长度字符串、整数/十进制数和 JSON 对象。字段最终类型、server default、校验规则和迁移兼容性须在业务实施 Change 定案。除明确标为可空外，字段为建议必填。所有创建/更新时间由可信云端生成；客户端不可自报创建者或租户归属。

### 3.1 EdgeNode

| 字段 | 类型取向 / 可空 | 来源、默认或验证 |
| --- | --- | --- |
| id | UUID / 非空 | 云端生成；创建后稳定 |
| tenant_id, site_id | UUID / 非空 | 由路径与已验证资源决定；不得从请求体覆盖；复合引用 Site |
| name | string / 非空 | Owner/Admin 提供；非空、长度限值待实施定案 |
| status | enum / 非空 | pending 默认；仅 Owner/Admin 转换 |
| config_revision | integer / 非空 | 云端配置版本建议从 1 开始；完整配置下发不在本 Change |
| applied_config_revision | integer / 可空 | 节点 heartbeat 回报的观测值；不能提升权限 |
| last_seen_at | UTC timestamp / 可空 | 云端收到有效 heartbeat 时生成 |
| created_by_user_id | UUID / 非空 | 从当前可信云端身份写入 |
| created_at, updated_at | UTC timestamp / 非空 | 云端生成 |

### 3.2 Device

| 字段 | 类型取向 / 可空 | 来源、默认或验证 |
| --- | --- | --- |
| id | UUID / 非空 | 云端生成；物理设备迁移/重新登记时新 ID |
| tenant_id, site_id, edge_node_id | UUID / 非空 | 由已验证路径/节点决定；复合引用同一 EdgeNode |
| name | string / 非空 | Owner/Admin 提供 |
| kind | enum/string / 非空 | 当前Registry只接受camera；其他设备类型须另行扩展与评审 |
| status | enum / 非空 | active 默认；Owner/Admin 启停 |
| hardware_serial | string / 可空 | Owner/Admin 登记；不是来源授权凭据，也不默认全局唯一 |
| created_at, updated_at | UTC timestamp / 非空 | 云端生成 |

### 3.3 TrainingSession

| 字段 | 类型取向 / 可空 | 来源、默认或验证 |
| --- | --- | --- |
| id | UUID / 非空 | 云端生成 |
| tenant_id, site_id | UUID / 非空 | 由请求路径中经校验的 Site 决定，创建后不变 |
| created_by_user_id | UUID / 非空 | 云端认证身份写入；不接受客户端指定 |
| title | string / 可空 | 用户创建时可提供；长度待实施定案 |
| status | enum / 非空 | planned 默认；云端按状态机推进 |
| started_at | UTC timestamp / 可空 | planned 时为空；由云端接受的开始转换记录，不作为设备拍摄时间 |
| completed_at, cancelled_at | UTC timestamp / 可空 | 仅对应云端状态转换时由云端写入 |
| created_at, updated_at | UTC timestamp / 非空 | 云端生成并用于审计/稳定排序 |

Session 不绑定单个 EdgeNode；同一 Session 可以汇集多设备的独立 VideoAsset。学员参与者、教练学员业务关系、训练计划/编排不在此模型范围。

### 3.4 VideoAsset 与采集时间

| 字段 | 类型取向 / 可空 | 来源、默认或验证 |
| --- | --- | --- |
| id | UUID / 非空 | 每次独立采集、导入或派生生成；幂等重试同一请求才复用 |
| tenant_id, site_id, session_id | UUID / 非空 | 由可信 Session 决定；组合引用父 Session，创建后不可改 |
| origin | enum / 非空 | 云端决定 edge/manual/derived；与来源列和派生父关系一致 |
| created_by_user_id | UUID / 条件可空 | manual 时从认证用户写入；edge 时为空；derived 的执行主体由后续实施设计 |
| source_edge_node_id, source_device_id | UUID / 成对可空 | edge 时均必填且属于目标场馆、节点与凭据一致；manual 时均空；derived 沿用父 Asset |
| derived_from_asset_id | UUID / 可空 | 仅派生资产填写；父 Asset 必须同 tenant/site/session 且 ready |
| status | enum / 非空 | pending_upload 默认；服务端确认后 ready 或失败后 failed |
| capture_started_at_utc, capture_ended_at_utc | UTC timestamp / 可空 | 仅当原始设备时间及其基准足以无歧义换算时填写；不以接收时间填充 |
| device_capture_started_at_raw, device_capture_ended_at_raw | 原始字符串 / 可空 | 设备/采集端原样提供；保留原始精度与字面值，不能假定有时区；API capture_metadata 使用完全相同的字段名 |
| device_time_basis | enum / 非空 | utc、offset、iana_timezone、unknown；unknown 是显式状态，不猜测 UTC |
| device_timezone | IANA timezone string / 可空 | 由设备或采集端报告；若使用 IANA 基准则必需并在实施时校验 |
| device_utc_offset_minutes | signed integer / 可空 | 设备报告的 UTC 偏移；与时间基准一致；不由场馆时区代替 |
| video_timebase_kind | enum / 非空 | relative、wall_clock、unknown；描述视频内部时间轴，不等于服务端时钟 |
| video_timebase_metadata | JSON object / 可空 | 时间单位/刻度及一个或多个视频偏移—墙钟锚点；未知或不适用时为空，不构造虚假映射 |
| device_clock_source | enum / 非空 | ntp、ptp、gps、manual、unknown；采集端报告，默认 unknown |
| device_clock_offset_ms | decimal / 可空 | 相对可信参考时钟的有符号偏差；只有设备/校准流程提供证据时填写 |
| device_clock_accuracy_ms | non-negative decimal / 可空 | 时钟不确定度/精度估计；未知时为空，不填 0 伪装准确 |
| received_at | UTC timestamp / 可空 | 服务端首次收到媒体对象/上传完成事件的时间；不是拍摄时间 |
| media_type, size_bytes | string / 可空；integer / 可空 | 上传声明值先视为未验证；最终元数据由完整对象检查确认 |
| checksum_sha256 | 64 hex string / 可空 | 服务端整对象校验结果；ready 前为空或待确认；不是逻辑身份或唯一键 |
| storage_object_ref | opaque server reference / 可空 | 存储适配层引用；产品/区域/物理模型未定，不向客户端泄露 |
| created_at, updated_at | UTC timestamp / 非空 | 逻辑资产由云端创建/更新；用于排序与审计，和采集时间分离 |

时间数据验收方向：开始/结束两端均已知时校验开始不晚于结束；原始时间、时间基准、时区/偏移之间不得矛盾；基准未知时不生成 UTC 派生值；校时偏差与精度是带来源的不确定性记录而非设备绝对准确证明；服务端 received_at 与 created_at 由服务端生成。多机位时钟对齐算法、时间偏差阈值和不可信时钟处置属于后续实施设计。

### 3.5 支持概念（非业务新实体范围）

| 概念 | 关键字段方向 | 边界 |
| --- | --- | --- |
| EdgeCredential | id、tenant/site/edge_node_id、token_hash、issued_at、expires_at、revoked_at、issued_by_user_id | token_hash 唯一；不存明文；节点停用时凭据失效，重新启用需新凭据 |
| UploadSession | id、tenant/site/session_id/asset_id、status、initiator_user_id、initiator_edge_node_id、expected_size_bytes、expected_sha256、expires_at、created_at、completed_at | 仅一个发起主体：用户或节点恰一；asset_id 唯一；绑定原创建主体；服务端整对象校验之前不得将 Asset 置 ready |

EdgeCredential 和 UploadSession 是完整契约说明所需的支持概念，其字段并不表示本 Change 创建表。资源读取 grant 的持久化表/关联方式也留待业务实施设计；D3/D8 的授权效果必须由后续实施实现。

## 4. 身份、来源和不可变约束

- Tenant、Site 和来源 EdgeNode/Device 由服务端路径与认证上下文解析。Session/Asset 创建主体不得由客户端任意填写。
- EdgeNode、Device、Session 与 Asset 的 tenant/site/session 归属创建后不允许 PATCH 改写。硬件搬迁通过目标场馆重新登记新 EdgeNode/Device ID；旧记录与既有录像继续保留旧来源。
- Edge 上传的设备必须属于认证节点及目标场馆；人工上传无设备来源；派生 Asset 与父记录同租户/场馆/Session 并保留来源链。
- 每次独立采集/import/derive 有独立逻辑 asset_id。不同设备或不同采集即使 SHA-256 相同，也不合并身份、来源、时间或权限；不设 checksum 逻辑唯一键。
- 幂等请求重放同一业务请求才复用原逻辑结果；物理内容复用是可选存储优化，不共享逻辑资产授权或生命周期。MediaBlob 是否独立建表、物理复用及引用清理另行设计，本 Change 不建表。
- Session 读取 grant 在有效期内涵盖该 Session 现有及未来新增的全部 VideoAsset；撤销后不再提供该授权路径。独立 Asset grant 只覆盖目标 Asset，不开放 Session 详情或兄弟 Asset。多条合法路径并存时撤销一条路径不消除其他路径。
- Owner/Admin 在当前 Tenant 范围内管理及读取资源，不受 Coach grant 约束；Coach 需有效机构成员、Site 访问以及资源级创建者/显式读取授权。读 grant 不授予 Session 修改、上传或转授权权力。

## 5. 状态机和非法迁移

| 实体 | 允许迁移 | 终态/拒绝规则 |
| --- | --- | --- |
| EdgeNode | pending → active；pending/active → disabled；disabled → active（须新签凭据） | disabled 阻止节点调用并使原凭据失效；heartbeat 不得恢复权限 |
| Device | active ↔ disabled | disabled 后不得创建/确认新上传；历史 Asset 仍依 D3/D5 授权访问 |
| TrainingSession | planned → recording → completed；planned/recording → cancelled | completed/cancelled 终态；计划态 started_at 可空；云端状态由获 S-manage 的用户路径推进 |
| VideoAsset | pending_upload → ready 或 failed | ready/failed 终态；失败重试新逻辑 Asset ID；ready 内容不变 |
| UploadSession | uploading → completing → completed/failed/aborted/expired；uploading → failed/aborted/expired | completed 与 Asset.ready 配对；failed/aborted/expired 与尚未 ready 的 Asset.failed 配对；所有终态不可逆，重试新建 Asset/UploadSession |

UploadSession 与 VideoAsset 的终态必须在同一数据库事务中配对更新：完整对象验证成功后才能原子提交 `UploadSession.completed + VideoAsset.ready`；校验失败提交 `failed + failed`，显式中止提交 `aborted + failed`，到期提交 `expired + failed`。尚未 ready 的资产不允许随着 UploadSession 进入终态而遗留在 pending_upload。UploadIntentCreate 也应原子创建 Asset 与 UploadSession。

Session 取消、complete、abort 与 expiry 竞争时，对 Session、UploadSession、Asset 的检查和状态更新必须串行化或用条件更新确保仅一个合法事务获胜。若取消先获胜，所有未完成的关联上传以 `session_cancelled` 原因进入 UploadSession.failed，Asset 同事务进入 failed；之后 complete 返回 409。若 complete 的完整性确认先获胜，则原子提交 completed/ready，之后取消不得回退或删除该 Asset。若数据库事务提交失败，不能只提交其中一侧的终态；同一请求可安全重试并读取唯一最终结果。到期处理需要可重试地终结过期的 uploading/completing 会话，避免永久 pending_upload；对象存储残留清理仍按后续存储策略设计。Session completed 后允许合规补传但不回退 Session 状态。分片回执只证明分片传输，不证明整对象 ready。

Edge 离线可生成临时本地 Session/采集记录并保留录像；恢复联网后可提交同步。云端仍是 Session 最终业务权威，本地临时 ID/状态/创建者声明不会直接覆盖云端记录。云边授权、ID 映射、重复检测与状态冲突协议另开 Change，本稿不定义 Outbox/Inbox 或同步算法。

## 6. 历史、停用与删除边界

- 四实体均不提供 DELETE API；EdgeNode/Device 使用停用，Session 使用取消，Asset 保留状态与来源。
- Site/Tenant 将来接入历史媒体后，不得经父级删除或 CASCADE 清除历史 Session、Asset、来源、授权审计或仍被保留的内容引用。存在历史资产、活动引用或未满足保留/处置条件时，应先停用/归档并保持稳定父 ID。
- 物理对象只有在后续批准的保留/处置策略允许、且不存在其他需保留逻辑 Asset 引用时才能清理；删除一条逻辑引用不能误删共享内容。
- 本地采集原件不因云端 Asset ready 自动变成可删除缓存；清理须满足独立保留策略和云端确认。
- 本文不设定保留天数、删除/导出接口、外键 ondelete、软删除字段或物理存储回收实现。既有六表 CASCADE 是现状，不能自动扩展为未来媒体策略。

## 7. 设计追溯

完整 C1–C5、D1–D10 决策记录和替代方案见 [ADR 0003](../decisions/0003-capture-media-domain-contracts.md)；端点与资源授权规则见 [API 契约草案](../contracts/cloud-capture-media.md)。本草案不声称主规格已同步、业务代码/数据库已实现、RLS/生产已验证。
