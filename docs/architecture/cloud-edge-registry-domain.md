# Cloud Edge Registry 领域模型

本文件记录 implement-cloud-edge-device-foundation Apply 的实际实现。它只覆盖Cloud Edge Registry，不代表Edge Runtime、采集媒体或整个云端平台已完成。

- 实际模型：[models.py](../../services/cloud/src/swimplatform/models.py)
- 增量迁移：[20261110_0002](../../services/cloud/migrations/versions/20261110_0002_cloud_edge_registry.py)
- Apply范围：[OpenSpec Tasks](../../openspec/changes/archive/2026-11-11-implement-cloud-edge-device-foundation/tasks.md)
- API契约：[Cloud Edge Registry API](../contracts/cloud-edge-registry.md)
- 验收报告：[Apply验证记录](../verification/cloud-edge-device-foundation-apply.md)

## 关系与身份

~~~mermaid
erDiagram
    TENANTS ||--o{ SITES : contains
    SITES ||--o{ EDGE_NODES : registers
    EDGE_NODES ||--o{ DEVICES : registers
    EDGE_NODES ||--o{ EDGE_CREDENTIALS : authenticates
    SITES ||--o{ IDEMPOTENCY_RECORDS : scopes
    USERS ||--o{ EDGE_NODES : creates
    USERS ||--o{ EDGE_CREDENTIALS : issues_or_revokes
    USERS ||--o{ IDEMPOTENCY_RECORDS : owns
~~~

云端Device身份代表摄像头设备本身。第一版只接受kind=camera。摄像头固定安装在跟拍小车上并随车移动；这是物理安装关系，不是摄像头固定在泳池位置。当前一摄一车不要求额外的Cart记录，也不限制一个EdgeNode登记多台各自独立的Camera。每台Camera有独立、通用的Device UUID。

Device的通用ID、Node父归属和kind字段保留未来扩展空间；第一版不能登记cart或其他未支持类型。独立管理小车控制器、底盘遥测、运动/自动跟拍及安全协议须另行扩展领域模型和设备协议。

## 四张新增表

| 表 | 归属、关键字段和约束 |
| --- | --- |
| edge_nodes | UUID；复合归属tenant_id/site_id；名称；pending/active/disabled状态；期望配置revision和自报applied revision；最近服务端心跳、版本/健康观测；凭据generation；登记User与时间。复合外键引用Site，创建者外键引用User。 |
| devices | UUID；复合归属tenant_id/site_id/edge_node_id；名称；kind=camera；active/disabled状态；可空硬件序列号。序列号不是认证身份或唯一键。 |
| edge_credentials | UUID；Node复合归属；generation；唯一SHA-256 token摘要；签发/到期时间及签发User；首次撤销时间及撤销User。数据库不存明文。 |
| idempotency_records | UUID；Tenant/Site/User/operation/target作用域；幂等键摘要、规范化请求摘要和资源种类/ID；不存明文key、完整请求或响应。范围唯一约束避免重复逻辑资源。 |

新增父引用均使用ON DELETE RESTRICT，不会沿用基础六表的级联清除语义。Node/Device没有DELETE API；Site或Node被登记记录引用时不能直接删除。账号历史引用也不级联删除。用户退出机构成员关系不删除其已创建的节点记录，因为Registry历史只引用User身份，不引用可撤销的tenant_memberships。

Node、Device的Tenant/Site/父Node归属在创建后不可修改。管理PATCH只接受明确列出的名称和状态。Node和Device的行政状态由Owner/Admin显式变更；心跳、过期或网络错误不会替管理员改变状态。

## 凭据生命周期与有限审计

- 默认有效期7天；显式期限必须晚于服务端当前UTC且不超过签发时刻30天。
- 明文只在成功签发响应返回一次；普通读取不返回明文或摘要，数据库、幂等行和应用日志不包含明文。
- 撤销不能恢复。Node停用在同一事务中递增credential generation并撤销当前凭据；已停用Node须由管理员签发新generation凭据后显式激活。
- Credential行记录签发User/时间和首次撤销User/时间；对应User外键RESTRICT。审计范围不包括通用事件系统、请求IP或完整请求体。
- Edge认证请求头为Authorization: Bearer swim_edge_<opaque-token>。User会话与Edge凭据分别查找和授权，互不通用；Edge凭据只授权其所属Node的heartbeat。
- 自动续期、密钥轮换服务、离线宽限和离线身份恢复协议均未实现。连续离线35天会超过最长凭据期限；旧凭据认证和依赖该身份的云端同步须等受控重新签发并更新Edge后恢复。

## 心跳观测

客户端默认每30秒发送一次；网络抖动可通过有限次数/超时预算重试。云端使用收到有效heartbeat时的服务端UTC写入last_seen_at，不得用客户端observed_at_raw代替。

查询时，只有Node状态为active且0 <= server_now - last_seen_at < 90秒才报告online=true。恰好90秒即offline；从未有效心跳、pending或disabled均offline。90秒是在线判定窗口，不是SLA。失败或离线不会自动改Node行政状态；有效心跳只更新最近观测，不续期凭据、不改desired config revision。

本Change提供云端heartbeat接口及模拟/可控时钟测试，不提供Edge Runtime常驻发送器、自动配置下发、监控平台或运动控制。

## 幂等与并发

Node/Device创建、Credential签发要求Idempotency-Key。键按Tenant、Site、User、operation和目标资源隔离，只保存摘要。请求摘要在应用时间/UUID等动态默认值生成前由规范化可写字段计算。

成功资源与幂等记录在同一事务提交。相同键和相同参数的Node/Device重试返回同一资源ID及当前可见状态；异参返回409。Credential签发的同键重试不会返回第二份secret，而返回409及可见Credential ID。权限在每次重放时重新检查。本Change不自动淘汰幂等记录。

PostgreSQL使用Node行锁串行化凭据签发、撤销、停用、恢复与heartbeat；SQLite写事务使用数据库锁。Node停用及批量撤销在同一数据库事务提交，失败时二者一起回滚。实现证据由Change验证记录中的SQLite/专用PostgreSQL完整套件提供。

## 实体边界

现有账号、机构、场馆六表及其19个操作保持不变；此次新增4表和12个操作。TrainingSession、VideoAsset、UploadSession、Pool/Lane、Outbox/Inbox、RLS、生产部署和媒体存储均不在此实现内。
