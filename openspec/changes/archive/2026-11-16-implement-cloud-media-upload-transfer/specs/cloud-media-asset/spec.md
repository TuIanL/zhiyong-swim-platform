# Spec Delta

## MODIFIED Requirements

### Requirement: Logical asset identity is per capture

每次独立采集、导入或派生 SHALL 产生新的 asset_id；不同设备、不同采集或不同导入即使 SHA-256 相同也 MUST 各自保留独立身份、来源、采集时间与授权，系统 MUST NOT 以 checksum 作为逻辑唯一键或据此拒绝创建。

#### Scenario: Same content from two captures

- **WHEN** 同一 Session 下两次独立上传意图声明相同的 expected_sha256 与相同大小
- **THEN** 服务 MUST 创建两个不同 asset_id 的记录，并分别保留各自来源与采集元数据

#### Scenario: Idempotent replay is not a new capture

- **WHEN** 同一已认证主体使用同一 Idempotency-Key 与相同参数重试创建上传意图
- **THEN** 服务 MUST 返回同一 asset_id 与同一 upload_session_id，而不是新建第二个逻辑资产

#### Scenario: Different cameras keep identities through verification
- **WHEN** 两台同节点或不同合法节点的摄像头用不同键提交相同 SHA-256/大小，随后各自通过完整对象校验
- **THEN** 两个 asset_id 与 upload_session_id MUST 不同，各自来源设备、采集时间、授权与对象绑定 MUST 保留，不得因验证摘要相同合并身份或拒绝创建

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

#### Scenario: Valid UTC offset and IANA capture metadata
- **WHEN** 调用者分别提交合法 utc、offset 与 iana_timezone（含有效 IANA 名称）的采集元数据与显式带时区 UTC 字段
- **THEN** 三类请求 MUST 均被接受，读取保留原始设备时间字面值及基准/时区/偏移，UTC 字段按绝对瞬间往返；服务端 received_at MUST 不得替代采集时间，unknown 仍不得生成 UTC

### Requirement: Declared media metadata is not verified metadata

上传意图中的 media_type、expected_size_bytes 与 expected_sha256 SHALL 被视为未经验证的声明值；Asset 的 checksum_sha256 MUST 在服务端完成整对象校验前保持为空，系统 MUST NOT 以任何响应把声明值呈现为已确认。声明值 MUST 保留于 UploadSession；实际大小、实际媒体类型、整对象摘要及验证时间 SHALL 作为独立验证结果，仅在成功最终提交时暴露为已验证值。

#### Scenario: Intent response before any bytes

- **WHEN** 上传意图创建成功
- **THEN** 响应 MUST 包含声明的 media_type 与 size 信息、`status=pending_upload` 且 checksum_sha256 为 null

#### Scenario: Invalid declaration is rejected early

- **WHEN** expected_sha256 不是 64 位小写十六进制，或 expected_size_bytes 不是正整数
- **THEN** 服务 MUST 返回 422 且不创建记录

#### Scenario: Verified values and original declaration remain separate
- **WHEN** 完整对象验证成功并提交 ready
- **THEN** Asset MUST 返回服务端实际 verified_size_bytes、verified_media_type、verified_at 与 checksum_sha256，原 expected_size_bytes、expected_sha256 与声明 media_type MUST 仍可从原 UploadSession 读取；失败和待验证 Asset 的验证字段 MUST 保持为空

### Requirement: Upload session terminal states pair with asset failure

UploadSession 的每个终态 MUST 在同一事务内与该 Asset 的状态配对：aborted、expired 与 failed 均对应 Asset.failed；终态不可逆；同键同参重放 MUST 返回原记录的当前终态而不复活。需要重新传输时 MUST 使用新键创建新的 Asset 与 UploadSession，并重新满足当前 Session 状态与授权约束。

#### Scenario: Abort pairs both sides

- **WHEN** 发起主体中止一个 uploading 上传会话
- **THEN** 服务 MUST 返回 204，且该 UploadSession 为 aborted、其 Asset 为 failed，两者原因一致

#### Scenario: Repeated terminal request does not rewrite history

- **WHEN** 发起主体重复中止同一上传会话
- **THEN** 服务 MUST 返回 204 且不改变首次终结时间与原因

#### Scenario: Terminal state is final

- **WHEN** 对已终结的上传会话再次请求中止或读取
- **THEN** 读取 MUST 返回已提交终态，中止 MUST 不使其回到 uploading 或变为 completed

### Requirement: No ready without whole-object verification

VideoAsset SHALL 仅在服务端对绑定的不可变完整对象完成实际大小、整对象 SHA-256 与媒体类型校验后进入 ready，并与 UploadSession.completed 同事务提交。pending_upload 与 failed 的 checksum_sha256 及验证字段 MUST 为空；客户端声明、分片回执和物理合并不能直接产生 ready。

#### Scenario: Every reachable status
- **WHEN** 调用方仅创建、读取、中止、过期上传或校验未成功
- **THEN** Asset MUST 仅为 pending_upload 或 failed，checksum_sha256 与验证字段 MUST 为空

#### Scenario: Completion operation requires successful verification
- **WHEN** 调用方对上传会话提交完成请求
- **THEN** 校验中 MUST 返回 202 且 Asset 仍 pending_upload，只有整对象验证与最终事务成功才允许返回 200 completed/ready

#### Scenario: No completion operation is exposed
- **WHEN** 调用方尝试直接提交 ready 状态、checksum 或存储引用，要求不经服务端整对象验证就完成上传
- **THEN** 服务 MUST 不存在接受该旁路的公开操作，相关不可写字段 MUST 返回 422，Asset MUST 不因该尝试变为 ready；本场景延续 M2 的无直接完成旁路保证，合法 complete 按上一个场景执行

#### Scenario: Ready is bound to an immutable physical identity
- **WHEN** Asset 被提交为 ready 或用于访问 URL 签发
- **THEN** 数据库 MUST 存在同 tenant/site/session/asset 的精确已验证存储引用、验证字段与 completed 上传，且后续不得用同 key 的其他版本替换原对象或覆盖采集来源

## ADDED Requirements

### Requirement: Existing intent replay precedes new intent state checks

上传意图重试 SHALL 在重新确认当前身份、资源权限与主体作用域后检查既有幂等记录。同主体/作用域/键且摘要相同时 MUST 返回原 Asset/UploadSession 的当前状态；不同摘要 MUST 返回 409 idempotency_conflict。只有不存在记录的新请求才应用 cancelled 禁止新建等状态约束，User 与 Edge MUST 一致。

#### Scenario: Cancelled session returns original terminal pair
- **WHEN** 原主体成功创建意图后 Session 被取消，再以同键同参重试
- **THEN** 服务 MUST 返回 201 与原两个 ID 的 failed/session_cancelled 当前终态，不创建新记录、不复活、不覆盖原因或首次时间

#### Scenario: New key and conflicting key after cancellation
- **WHEN** 有权原主体在 cancelled Session 上用新键，或用原键不同摘要提交
- **THEN** 新键 MUST 返回 409 state_conflict，原键异参 MUST 返回 409 idempotency_conflict，两者均无新增记录

#### Scenario: Replay cannot bypass current authorization
- **WHEN** 用户已失去当前成员/场馆/资源管理权限，或 Edge 凭据已过期/撤销，再重放原键
- **THEN** 服务 MUST 按当前身份与可见性拒绝访问，不得从幂等缓存返回越权资源或签名 URL
