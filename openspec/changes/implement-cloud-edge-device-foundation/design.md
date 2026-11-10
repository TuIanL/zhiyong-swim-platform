# Design

## Context

动机与唯一实施范围见[proposal](proposal.md)，路线建议见[全项目审计](../../../docs/planning/2026-11-10-p0-p1-roadmap.md)。本文件的F1–F8是**本次待审实施选择**；ADR0003 D1–D10是已评审文档方向，两者不混同为业务已获批准。

main@d7f1eed只有六表、19操作。[api.py](../../../services/cloud/src/swimplatform/api.py)已有identity/membership/manager/site_access和UTC瞬间归一逻辑；[models.py](../../../services/cloud/src/swimplatform/models.py)有Site复合唯一键；[PG schema测试](../../../services/cloud/tests/test_postgresql_schema.py)固定六表，现有[pg_support](../../../services/cloud/tests/pg_support.py)授权使用ALL TABLES语句。新增表时必须改为批准集合并扩展断言，不能删除六表回归或沿用自动授权任意表。

## Goals / Non-Goals

**Goals:** 用现有用户权限管理节点登记，用独立持久凭据验证本节点观测；在没有真实硬件/存储/GPU的隔离环境中可验收。规范见[新能力](specs/cloud-edge-registry/spec.md)和[基础增量](specs/cloud-identity/spec.md)。

**Non-Goals:** 不实现完整Edge软件、设备控制、配置下发、媒体/训练/分析、学员关系、RLS或生产栈。首次仅支持camera登记，其他Device kind须另评审；Node列表不扩张为全API分页。

## Decisions

### F1 模型、归属与历史

在既有单体增加4张表，不引入外部服务；仍使用UUID字符串和UTC时间，具体列长度/约束如下供实施：

| 表 | 字段与约束方向 |
| --- | --- |
| edge_nodes | id、tenant_id/site_id、name(1–120)、status(pending/active/disabled，默认pending)、config_revision(默认1)、applied_config_revision(可空非负int)、created_by_user_id、last_seen_at/最近health/observed_at_raw(可空)、credential_generation(默认0)、created_at/updated_at；UNIQUE(tenant_id,site_id,id)，复合FK→sites(tenant_id,id) |
| devices | id、tenant_id/site_id/edge_node_id、name(1–120)、kind(camera)、status(active/disabled，默认active)、hardware_serial(可空，最长120)、created_at/updated_at；UNIQUE(tenant_id,site_id,edge_node_id,id)，复合FK→edge_nodes |
| edge_credentials | id、tenant_id/site_id/edge_node_id、generation、token_hash(唯一)、issued_at/expires_at/revoked_at(可空)；复合FK→edge_nodes；不存secret |
| idempotency_records | id、tenant_id/site_id/user_id、operation、target_id、key_hash、request_hash、resource_kind/resource_id、created_at；UNIQUE(tenant_id,site_id,user_id,operation,target_id,key_hash)；不存完整请求/响应或secret |

新增父级FK使用RESTRICT，不沿用六表CASCADE；Node/Device没有删除入口，迁场馆重新登记。身份引用指向User，不指向TenantMembership，避免成员撤销被登记记录阻止；现有无新引用的六表级联语义保留。幂等的多类型resource引用由写服务核对并与实际资源同事务提交，不冒充多态FK自动约束。

tenant/site/node归属创建后API不可更改，PATCH仅name/status且至少一个字段；kind/serial不在PATCH可写集合。复合FK保证一致性，不声称FK能独自保证所有状态/权限/不可变规则。Device创建与重新启用要求父Node active，停用父节点不迁移/删除Device。名称/序列号不默认唯一，不能当认证身份。

### F2 12个操作及错误边界

P=/api/v1/tenants/{tenant_id}/sites/{site_id}。以下均为本次拟实现，现有19操作不改：

| 方法 | 路径 | 身份/成功 |
| --- | --- | --- |
| GET | P/edge-nodes | Owner/Admin，200数组，status筛选 |
| POST | P/edge-nodes | Owner/Admin，201 EdgeNodeRead，要求Idempotency-Key |
| GET | P/edge-nodes/{edge_node_id} | Owner/Admin，200 |
| PATCH | P/edge-nodes/{edge_node_id} | Owner/Admin，200，仅name/status |
| GET | P/edge-nodes/{edge_node_id}/credentials | Owner/Admin，200 CredentialRead数组，无secret/hash |
| POST | P/edge-nodes/{edge_node_id}/credentials | Owner/Admin，201 CredentialIssued，要求Idempotency-Key |
| DELETE | P/edge-nodes/{edge_node_id}/credentials/{credential_id} | Owner/Admin，204，仅撤销，重复合法撤销仍204 |
| GET | P/devices | Owner/Admin，200数组，edge_node_id/status筛选 |
| POST | P/devices | Owner/Admin，201 DeviceRead，要求Idempotency-Key |
| GET | P/devices/{device_id} | Owner/Admin，200 |
| PATCH | P/devices/{device_id} | Owner/Admin，200，仅name/status |
| POST | /api/v1/edge/heartbeat | 本节点有效凭据且active，200 HeartbeatRead |

Owner/Admin不依赖显式SiteMembership；Coach/Athlete无节点/设备读取或管理权。结构合法请求先按用户/节点身份401、非机构成员404、同机构角色不足403，再按授权管理范围下的错误Tenant/Site/Node/Device/Credential ID返回404；非法筛选、枚举、空PATCH/未知字段为422；合法值遇状态冲突为409。复用detail.code/message，新增edge_node_not_found/device_not_found/credential_not_found、edge_unauthorized、state_conflict和幂等code；credential_secret_not_replayable在detail附可见credential_id。框架422结构保持既有行为，不更改19操作的顺序或错误格式。

节点/设备读取保留PR3已有字段；本片增加NodeRead.online和health_summary（含software_version/status）以完成原节点任务的“版本/健康可查”。它们是本提案的可观测字段细化，不是声称PR3已经实现。所有字段/长度和候选参数须随本提案审阅。

### F3 凭据与行政生命周期

采用高熵不透明token（至少256位随机量，Edge命名空间前缀）+摘要；不使用机器人User或用户会话，不在此引入mTLS/证书发行栈。Bearer承载方式可共用HTTP机制，认证查询空间与权限必须分离。

expires_at可省略，默认签发时UTC+7天；提供时必须晚于当前时刻且不超过30天。截止恰好命中即拒绝，复用as_utc语义，UTC/Asia时区变体隔离配置。Credential可在pending/active/disabled节点签发，但pending/disabled一律不能用它heartbeat；普通查询不含secret/hash。

Node pending→active、pending/active→disabled、disabled→active；同状态PATCH为无副作用重试，非法回pending为409。停用在同事务锁定Node、generation递增、撤销所有当前凭据；恢复必须有停用后新generation有效凭据。disabled时先签新凭据再显式激活，不形成“只能active签发而恢复又需新凭据”的死循环。active节点可先签新凭据再撤旧完成轮换。

签发/撤销/停用/恢复/heartbeat共享Node锁及事务顺序；PostgreSQL使用实际行锁，SQLite使用受支持的事务/条件更新语义。停用先提交后的新heartbeat拒绝；heartbeat先获锁提交的观测可以保留，不声称已接受请求能被事后撤回。只靠进程内锁无法跨worker/重启保证，不采用该方案。

### F4 心跳只是观测

HeartbeatRequest：reported_config_revision?(非负int)、observed_at_raw?(≤128字符，保留原始不确定时间)、health?对象。health仅software_version?(1–64字符)与status?(ok/degraded/unknown)，拒绝未知字段，序列化大小≤8KiB，不接收任意日志/设备Secret。

服务端接收时写UTC last_seen_at、最近版本/健康观测；reported版本只写applied观测，不修改desired config_revision（本片固定初始1，无配置下发端点）、status或归属。NodeRead按active且0≤now-last_seen_at<90秒计算online，不用定时任务修改行政状态；从未心跳、pending/disabled或到达90秒均offline。合法最近观测持久存储，不能把在线心跳当GPU/存储健康实测或完整监控。

替代“客户端时间决定在线”和“心跳自动激活”会引入身份提升/时钟伪造，因此不采用；90秒窗口及凭据期限是本提案明确选择、待负责人批准，不是既有政策。

### F5 持久幂等及一次性明文

Idempotency-Key为8–128字符可打印ASCII受限集合。作用域含当前Tenant/Site/User、具体operation、目标Site或Node；仅存键摘要、规范化可写参数摘要及资源引用。规范化在应用动态默认/UUID/now之前完成，避免省略expires_at的重试变成异参；时间显式值按相同UTC瞬间规范化。

成功资源与幂等行同事务；唯一约束裁定并发，冲突回滚后重新读已提交结果。Node/Device重试返回201与原ID的当前可见状态；同键异参409；每次先做当前授权，降权后不能重放。凭据同键重试只返回409+credential_id，不缓存明文、再次签发或用加密缓存绕过“一次返回”边界；响应丢失时管理员查询/撤销后用新键重签。

本片不自动过期/淘汰幂等记录，保证重启/较晚重试不产生重复；记录只有最小摘要，不存视频或完整请求。生产容量和回收策略是后续独立评审门槛，不把24小时后悄悄复用旧键作为实现捷径。新行为的保留取舍已明确写在本提案，未获批准前不Apply。

### F6 与既有规格及测试基线衔接

cloud-identity两个MODIFIED块完整保留原场景；原基础revision20261106_0001继续验证六表快照，新head额外验证4表。应用授权改为明确10表集合，不使用ALL TABLES默许未知表；保留schema USAGE、版本表仅SELECT，以及DDL/TRUNCATE/SET ROLE拒绝。直接create未批准canary表时应用无DML。

完整跑默认SQLite与专用PG共享/专属场景，新增必需场景被跳过或零收集须失败。复用pool_size=1与并发pool_size=8分别证明pg_backend_pid；至少覆盖同键Node/Device/凭据并发、停用/签发/heartbeat顺序、提交失败回滚和跨租户/跨场馆无副作用。旧112/150是历史基线，不是本片新增测试的固定期望。

### F7 代码与包边界

未来Apply在services/cloud新增独立registry/Edge路由与认证服务，复用当前identity/manager/site_access、数据库事务与security摘要工具，不复制一套用户注册或跨项目import。更新OpenAPI快照和域文档时逐项标出本片12个已实现，PR3剩余21个操作仍未来；不把整篇v0.1文档改成“全部实现”。新增迁移与模块应包含在wheel中并验证独立安装路径；不通过测试源码路径掩盖安装缺失。

### F8 来源与本片的偏差清单

| ADR方向 | 本片处理/新增细化 |
| --- | --- |
| D1/D2/D9 | 实施Node/Device固定归属、RESTRICT和停用历史；Asset等未来来源未建表 |
| D3 | 仅Owner/Admin管理和独立Edge身份；不实施Coach媒体grant/学员关系 |
| D4/D5/D6/D7/D10 | Session/Asset/上传/采集时间/离线协议不实施；不以通用幂等替代采集身份 |
| D8 | 复用11个管理操作+heartbeat；新增Node在线/健康读取字段、期限/长度为本次待审细化；不改现有19操作 |
| Notion节点原任务 | 版本/健康可查、身份可撤销由本片承接；健康summary不替代Runtime安装/完整运维验收 |

## Risks / Trade-offs

- 新表使旧六表断言失效 → 分开基础revision快照与head全集，新增失败/回滚用例，不删旧测试或修改历史迁移。
- 迁移后角色权限丢失 → 测试夹具在roundtrip后重新按批准表集合授权；迁移脚本不冒充生产角色部署。
- 行锁/唯一冲突处理在两后端有差异 → 共享行为测试+PG独立连接实测，超时/串行单连接不能冒充并发通过。
- 永久幂等摘要增长、短凭据需轮换、在线只反映最近通信 → 作为开发切片明确限制，生产容量/轮换自动化和监控另评审；本片不部署生产。
- 本提案参数可能被负责人调整 → 在Propose中按确认修改规格/设计/任务后再Apply，不从已归档文档推导实现授权。

## Migration Plan

1. 仅在明确Apply后新增递增revision；不改20261106_0001，不连旧库/生产库。隔离库升级保留六表原数据，新建4表、约束/索引、版本标记。
2. 验证空库base→head、含六表数据base→head、head→基础revision→head、受控失败回滚；删除新表仅用于隔离测试降级，原六表数据必须保留。
3. 用应用身份实测正常CRUD与禁止权限、容器实际归属与精确清理；增加新测试包/迁移安装验证。
4. 更新真实模型/API/文档、PR/Notion局部证据。通过独立Verify后按各阶段授权再Archive/主规格同步选择/Merge；本轮止于Propose。
