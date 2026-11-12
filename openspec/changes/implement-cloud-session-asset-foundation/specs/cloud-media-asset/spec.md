# Spec Delta

## Purpose

定义视频逻辑资产（VideoAsset）的独立身份、不可变归属与来源、采集时间与时钟不确定性、声明值与服务端确认值的边界，以及上传意图（UploadSession）的原子创建与终态配对，确保在二进制上传能力交付前不会出现可冒认的媒体资产。

## ADDED Requirements

### Requirement: Logical asset identity is per capture

每次独立采集、导入或派生 SHALL 产生新的 asset_id；不同设备、不同采集或不同导入即使 SHA-256 相同也 MUST 各自保留独立身份、来源、采集时间与授权，系统 MUST NOT 以 checksum 作为逻辑唯一键或据此拒绝创建。

#### Scenario: Same content from two captures

- **WHEN** 同一 Session 下两次独立上传意图声明相同的 expected_sha256 与相同大小
- **THEN** 服务 MUST 创建两个不同 asset_id 的记录，并分别保留各自来源与采集元数据

#### Scenario: Idempotent replay is not a new capture

- **WHEN** 同一已认证主体使用同一 Idempotency-Key 与相同参数重试创建上传意图
- **THEN** 服务 MUST 返回同一 asset_id 与同一 upload_session_id，而不是新建第二个逻辑资产

### Requirement: Asset scope and source pairing

Asset 的 tenant_id、site_id、session_id MUST 由已校验的父 Session 决定且创建后不可改；origin 为 edge 时节点与设备来源 MUST 同时存在且属于该场馆与认证节点，manual 时二者 MUST 为空，derived 时 MUST 存在同租户/场馆/会话的父 Asset。

#### Scenario: Edge source must match credential

- **WHEN** 节点凭据为 A 节点，请求声明属于 B 节点的 device_id，或该 device 已 disabled
- **THEN** 服务 MUST 返回 404 或 409 且不创建任何 Asset 或 UploadSession

#### Scenario: Manual capture has no device

- **WHEN** 具 S-manage 的用户为某 Session 创建人工上传意图
- **THEN** 服务 MUST 写入 origin=manual、source_edge_node_id 与 source_device_id 为空、created_by_user_id 为当前用户

#### Scenario: Scope is not client-writable

- **WHEN** 请求试图指定 tenant_id、site_id、session_id、origin、created_at 或 received_at
- **THEN** 服务 MUST 返回 422 且不创建记录

#### Scenario: Derived asset inherits parent

- **WHEN** 系统记录一个派生 Asset 而其父 Asset 属于另一 Session、另一机构或尚未 ready
- **THEN** 该记录 MUST 被拒绝，且 MUST NOT 出现跨 Session 或跨机构的派生链

### Requirement: Capture time keeps raw device values

设备采集时间 SHALL 保存原始字符串字面值、时间基准与时钟来源，服务 MUST NOT 裁剪、规范化或解析这些原始值，也 MUST NOT 从原始值猜测 UTC；时间基准为 unknown 时 MUST NOT 生成 UTC 派生值。

#### Scenario: Raw values survive round trip

- **WHEN** 上传意图声明首尾带空格的 `device_capture_started_at_raw` 与 `device_capture_ended_at_raw`
- **THEN** 读取该 Asset 时 MUST 返回与提交完全相同的字符串，且不因普通字符串规范化规则被改变

#### Scenario: Unknown basis cannot carry UTC

- **WHEN** 请求声明 device_time_basis=unknown 同时提供 device_timezone、device_utc_offset_minutes 或任一 capture_*_at_utc
- **THEN** 服务 MUST 返回 422 且不创建记录

#### Scenario: Basis-specific fields must agree

- **WHEN** device_time_basis=iana_timezone 未提供合法 IANA 时区，或 device_time_basis=offset 未提供落在 ±14 小时内的整数分钟偏移
- **THEN** 服务 MUST 返回 422 且不创建记录

#### Scenario: Ordering of known instants

- **WHEN** 请求同时提供 capture_started_at_utc 与 capture_ended_at_utc 且开始晚于结束
- **THEN** 服务 MUST 返回 422 且不创建记录

### Requirement: Declared media metadata is not verified metadata

上传意图中的 media_type、expected_size_bytes 与 expected_sha256 SHALL 被视为未经验证的声明值；Asset 的 checksum_sha256 MUST 在服务端完成整对象校验前保持为空，系统 MUST NOT 以任何响应把声明值呈现为已确认。

#### Scenario: Intent response before any bytes

- **WHEN** 上传意图创建成功
- **THEN** 响应 MUST 包含声明的 media_type 与 size 信息、`status=pending_upload` 且 checksum_sha256 为 null

#### Scenario: Invalid declaration is rejected early

- **WHEN** expected_sha256 不是 64 位小写十六进制，或 expected_size_bytes 不是正整数
- **THEN** 服务 MUST 返回 422 且不创建记录

### Requirement: Intent creates asset and upload session together

创建上传意图 SHALL 在同一事务内同时写入 VideoAsset(pending_upload) 与 UploadSession(uploading)，并返回两者的初始状态；系统 MUST NOT 提供任何绕过上传意图的裸 Asset 创建路径。

#### Scenario: Both records appear or neither

- **WHEN** 上传意图创建成功
- **THEN** 服务 MUST 返回 201 且同时可读到该 Asset 与该 UploadSession，后者 asset_id 指向前者

#### Scenario: Failure leaves nothing behind

- **WHEN** 在写入 UploadSession 阶段发生受控失败
- **THEN** 事务 MUST 整体回滚，既不存在该 Asset 也不存在该 UploadSession

### Requirement: Upload session terminal states pair with asset failure

UploadSession 的每个终态 MUST 在同一事务内与该 Asset 的状态配对：aborted、expired 与 failed 均对应 Asset.failed；终态不可逆，终结后重试 MUST 创建新的 Asset 与 UploadSession 而不是复活旧记录。

#### Scenario: Abort pairs both sides

- **WHEN** 发起主体中止一个 uploading 上传会话
- **THEN** 服务 MUST 返回 204，且该 UploadSession 为 aborted、其 Asset 为 failed，两者原因一致

#### Scenario: Repeated terminal request does not rewrite history

- **WHEN** 发起主体重复中止同一上传会话
- **THEN** 服务 MUST 返回 204 且不改变首次终结时间与原因

#### Scenario: Terminal state is final

- **WHEN** 对已终结的上传会话再次请求中止或读取
- **THEN** 读取 MUST 返回已提交终态，中止 MUST 不使其回到 uploading 或变为 completed

### Requirement: Intent expiry uses the server clock

UploadSession 的 expires_at SHALL 由服务端按签发时刻与既定上限写入，到期判定 MUST 使用服务端 UTC 时间且不因读取、重试或心跳延长；到期后该上传会话 MUST 被终结为 expired、其 Asset MUST 同事务进入 failed。

#### Scenario: Expired intent cannot stay pending

- **WHEN** 当前服务端时间已超过 expires_at 且调用方读取该上传会话
- **THEN** 服务 MUST 返回终态 expired，且其 Asset MUST 不再处于 pending_upload

#### Scenario: Abort after expiry

- **WHEN** 已过期的上传会话收到中止请求
- **THEN** 服务 MUST 返回已提交的终态结果，且不把原因改写为 aborted

### Requirement: No ready without whole-object verification

本切片 MUST NOT 提供任何能把 VideoAsset 置为 ready 的操作；经创建、读取、中止或过期路径得到的 Asset 状态 MUST 仅为 pending_upload 或 failed，ready 只允许在服务端完成整对象 bytes、SHA-256 与媒体元数据校验后由后续能力产生。

#### Scenario: Every reachable status

- **WHEN** 调用方遍历本切片全部公开操作后再次读取任一 Asset
- **THEN** 其 status MUST 为 pending_upload 或 failed，且 checksum_sha256 MUST 为 null

#### Scenario: No completion operation is exposed

- **WHEN** 调用方尝试对上传会话提交完成请求
- **THEN** 服务 MUST NOT 存在可接受该请求的公开操作，Asset MUST 不因该尝试变为 ready
