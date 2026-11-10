# Cloud Edge Registry API 契约

本文件描述 implement-cloud-edge-device-foundation 实际实现的12个API操作。基础身份契约仍见[云端基础API](cloud-foundation.md)；模型与持久化边界见[领域模型](../architecture/cloud-edge-registry-domain.md)。OpenAPI机器可读快照为[openapi.json](openapi.json)。

## 身份与权限

Node/Device/Credential管理API需要有效User Bearer及当前Tenant成员关系，并只允许Owner/Admin。本机构Owner/Admin可管理本机构全部场馆，无需显式SiteMembership。Coach/Athlete即使有Site访问权也没有Registry管理或读取权限。

Heartbeat只接受当前Node的Edge凭据，使用请求头Authorization: Bearer swim_edge_<opaque-token>。User token不能调用heartbeat；Edge token不能调用用户管理或基础API。凭据只授权其所属、处于active状态的Node提交heartbeat。

## 操作

令P=/api/v1/tenants/{tenant_id}/sites/{site_id}。

| 方法与路径 | 输入/权限 | 成功 |
| --- | --- | --- |
| GET P/edge-nodes | Owner/Admin；可选status=pending/active/disabled | 200 EdgeNodeRead数组 |
| POST P/edge-nodes | Owner/Admin；Idempotency-Key；EdgeNodeCreate | 201 EdgeNodeRead |
| GET P/edge-nodes/{edge_node_id} | Owner/Admin | 200 EdgeNodeRead |
| PATCH P/edge-nodes/{edge_node_id} | Owner/Admin；非空EdgeNodePatch | 200 EdgeNodeRead |
| GET P/edge-nodes/{edge_node_id}/credentials | Owner/Admin | 200 EdgeCredentialRead数组，不含token或摘要 |
| POST P/edge-nodes/{edge_node_id}/credentials | Owner/Admin；Idempotency-Key；可选UTC expires_at | 201 EdgeCredentialIssued，secret仅首次响应 |
| DELETE P/edge-nodes/{edge_node_id}/credentials/{credential_id} | Owner/Admin | 204；只撤销，不删除历史 |
| GET P/devices | Owner/Admin；可选edge_node_id、status=active/disabled | 200 DeviceRead数组 |
| POST P/devices | Owner/Admin；Idempotency-Key；DeviceCreate | 201 DeviceRead |
| GET P/devices/{device_id} | Owner/Admin | 200 DeviceRead |
| PATCH P/devices/{device_id} | Owner/Admin；非空DevicePatch | 200 DeviceRead |
| POST /api/v1/edge/heartbeat | Header中有效Edge bearer；HeartbeatRequest | 200 HeartbeatRead |

## 请求与响应字段

| Schema | 字段和限制 |
| --- | --- |
| EdgeNodeCreate | name必填，1–120字符。新Node以pending、config revision 1创建。 |
| EdgeNodePatch | 至少提供一个非空字段；只接受name和status。归属、generation和观测字段不可写。状态迁移非法时409。 |
| DeviceCreate | edge_node_id必填；name 1–120；kind仅camera（默认camera）；hardware_serial可空，最多120。父Node须active。 |
| DevicePatch | 非空；只接受name和status。父Node非active时不能重新启用Device。 |
| EdgeCredentialIssue | expires_at可省略；省略为服务端当前UTC+7天。显式值须带时区、晚于当前时刻且不超过30天。 |
| HeartbeatRequest | 可选reported_config_revision>=0、原样observed_at_raw最多128字符、health中的software_version最多64字符和status=ok/degraded/unknown；未知字段拒绝。 |
| EdgeNodeRead | 稳定ID与归属、名称/状态、期望与最近自报revision、服务端last_seen_at、在线结果、最近版本/健康观测、创建者及时间。 |
| DeviceRead | 稳定Device ID、Tenant/Site/Node归属、名称、kind、状态、可空序列号及时间。 |
| EdgeCredentialRead | ID、generation、签发/到期时间、签发User、首次撤销时间和撤销User；不含token或token摘要。 |
| EdgeCredentialIssued | EdgeCredentialRead字段及一次性token；仅签发成功响应包含secret。 |
| HeartbeatRead | edge_node_id、服务端UTC last_seen_at、online、heartbeat_interval_seconds=30、online_window_seconds=90。 |

## 状态、幂等和错误

- Node允许pending→active、pending/active→disabled、disabled→active。恢复disabled Node要求当前generation有未撤销、未到期的新凭据。
- Node停用和撤销其有效凭据原子提交；撤销重放仍204且保留首次撤销者/时间。
- Idempotency-Key为8–128位受限ASCII字符。Node/Device成功重放返回同一逻辑资源；异参409。Credential签发重放409 credential_secret_not_replayable 并给出可见Credential ID，不重放secret。
- 认证失败401；非成员、跨Tenant/Site资源不泄露并返回404；同机构角色不足403；无效字段、kind、空PATCH或过滤值返回422；合法但状态不允许返回409。
- 业务错误沿用detail.code/detail.message。错误码包括edge_unauthorized、edge_node_not_found、device_not_found、credential_not_found、invalid_idempotency_key、idempotency_conflict、credential_secret_not_replayable、state_conflict、invalid_credential_expiry。

90秒只用于计算在线状态，不构成SLA；服务失败、网络超时或窗口过期不会自动改变Node行政状态。
