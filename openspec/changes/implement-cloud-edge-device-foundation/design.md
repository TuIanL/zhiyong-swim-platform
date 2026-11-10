# Design

## Context

动机与唯一实施范围见[proposal](proposal.md)，路线与决策补录见[全项目审计](../../../docs/planning/2026-11-10-p0-p1-roadmap.md)。负责人已确认本Change为首项业务主线及D11–D13，并授权基于PR #4 head 334f589b66e22dc55716f5e6befb44d31e003cd1 进入Apply。ADR0003 D1–D10及D11–D13仍是设计输入，不能被误报为已实现。

main@d7f1eed只有六表、19操作。[api.py](../../../services/cloud/src/swimplatform/api.py)已有identity/membership/manager/site_access和UTC瞬间归一逻辑；[models.py](../../../services/cloud/src/swimplatform/models.py)有Site复合唯一键；[PG schema测试](../../../services/cloud/tests/test_postgresql_schema.py)固定六表，现有[pg_support](../../../services/cloud/tests/pg_support.py)授权使用ALL TABLES语句。新增表时必须改为批准集合并扩展断言，不能删除六表回归或沿用自动授权任意表。

## Goals / Non-Goals

**Goals:** 用现有用户权限管理节点登记，用独立持久凭据验证本节点观测；在没有真实硬件/存储/GPU的隔离环境中可验收。规范见[新能力](specs/cloud-edge-registry/spec.md)和[基础增量](specs/cloud-identity/spec.md)。

**Non-Goals:** 不实现完整Edge软件、设备控制/电机/运动/自动跟拍/安全协议、配置下发、媒体/训练/分析、学员关系、RLS或生产栈。D11第一版仅支持camera登记，不单建Cart Device；其他kind与控制器/底盘遥测须后续领域/协议评审。Node列表不扩张为全API分页。

## Decisions

### 已确认的负责人决策 D11–D13

| 决策 | 已确认内容与本片边界 |
| --- | --- |
| D11 Camera-first | 云端Device标识摄像头；一台摄像头固定安装于一台跟拍小车并随车移动，这是当前物理部署关系，不是泳池固定位置机位。无需先建Cart实体/ID，不在本片实施控制器或安全协议；Device标识、父归属和类型判别保持通用，未来kind可经独立Change扩展。 |
| D12 EdgeCredential | 默认7天、最长30天，服务端UTC为到期基准；撤销不可恢复、明文成功签发只返一次，不存入数据库/读取/日志/幂等。无自动续期、离线无限延长、离线身份恢复协议或自动轮换服务。 |
| D13 Heartbeat | 默认发送30秒；Node active且0≤服务端当前时刻−last_seen_at<90秒才online，允许抖动/有界重试；失败和超时不改变行政状态，自报时间无权替代接收时间。90秒不是SLA。 |

### F1 模型、归属与历史

在既有单体增加4张表，不引入外部服务；仍使用UUID字符串和UTC时间，具体列长度/约束如下供实施：

| 表 | 字段与约束方向 |
| --- | --- |
| edge_nodes | id、tenant_id/site_id、name(1–120)、status(pending/active/disabled，默认pending)、config_revision(默认1)、applied_config_revision(可空非负int)、created_by_user_id、last_seen_at/最近health/observed_at_raw(可空)、credential_generation(默认0)、created_at/updated_at；UNIQUE(tenant_id,site_id,id)，复合FK→sites(tenant_id,id) |
| devices | id、tenant_id/site_id/edge_node_id、name(1–120)、kind(camera)、status(active/disabled，默认active)、hardware_serial(可空，最长120)、created_at/updated_at；UNIQUE(tenant_id,site_id,edge_node_id,id)，复合FK→edge_nodes |
| edge_credentials | id、tenant_id/site_id/edge_node_id、generation、token_hash(唯一)、issued_at/expires_at/revoked_at(可空)、issued_by_user_id/revoked_by_user_id(可空)；复合FK→edge_nodes，用户外键RESTRICT；不存secret |
| idempotency_records | id、tenant_id/site_id/user_id、operation、target_id、key_hash、request_hash、resource_kind/resource_id、created_at；UNIQUE(tenant_id,site_id,user_id,operation,target_id,key_hash)；不存完整请求/响应或secret |

新增父级FK使用RESTRICT，不沿用六表CASCADE；Node/Device没有删除入口，迁场馆重新登记。身份引用指向User，不指向TenantMembership，避免成员撤销被登记记录阻止；现有无新引用的六表级联语义保留。幂等的多类型resource引用由写服务核对并与实际资源同事务提交，不冒充多态FK自动约束。

tenant/site/node归属创建后API不可更改，PATCH仅name/status且至少一个字段；kind/serial不在PATCH可写集合。复合FK保证一致性，不声称FK能独自保证所有状态/权限/不可变规则。Device创建与重新启用要求父Node active，停用父节点不迁移/删除Device。名称/序列号不默认唯一，不能当认证身份。

D11按一机一车描述物理安装关系，不新增Cart表、Cart外键或强制cart_id，也不把一机一车误设为一个Edge只能有一个Device。一个Node可登记多台camera，每台有自己的通用Device UUID/来源；不将Device ID编码成Cart ID、泳池固定机位或仅Camera专用资源名。第一版输入及约束只接受camera，未来类型通过扩展kind校验/相应迁移与协议实现，不必更换既有ID/父归属。摄像头随车移动，不能从“固定安装”推导出相机坐标固定；运动补偿/标定不在本片实现。

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

节点/设备读取保留PR3已有字段；本片增加NodeRead.online和health_summary（含software_version/status）以完成原节点任务的“版本/健康可查”。HeartbeatRead见F4，发送间隔/在线窗口按已确认D13说明；其余字段/长度细化仍随本提案最终审阅，不是声称PR3已经实现。

### F3 凭据与行政生命周期

采用高熵不透明token（至少256位随机量，Edge命名空间前缀）+摘要；不使用机器人User或用户会话，不在此引入mTLS/证书发行栈。请求头固定为 Authorization: Bearer swim_edge_<opaque-token>，仅heartbeat路由接受Edge凭据；User bearer只查AuthSession，不能互用。日志不记录Authorization头或token。

按已确认D12，expires_at可省略，默认服务端签发时UTC+7天；提供时必须晚于服务端当前时刻且不超过签发时刻30天。截止恰好命中即拒绝，复用as_utc语义，UTC/Asia时区变体隔离配置。Credential可在pending/active/disabled节点签发，但pending/disabled一律不能用它heartbeat；普通查询不含secret/hash。明文只在成功签发时返回一次，数据库/普通读取/日志/幂等记录不得出现明文；重试不重放secret。撤销不可恢复，不能清空revoked_at使旧钥复活；只能由有权管理员重新签发。

本Change的凭据操作审计边界是保留credential生命周期行：issued_by_user_id/issued_at与首次revoked_by_user_id/revoked_at可追溯到执行管理员；这些User外键RESTRICT，避免历史事件因账号删除级联消失。当前不建通用audit/event表，不保存请求IP、完整请求体、token明文或token摘要到API响应/日志；数据库仅保存用于验证的token摘要。

Node pending→active、pending/active→disabled、disabled→active；同状态PATCH为无副作用重试，非法回pending为409。停用在同事务锁定Node、generation递增、撤销所有当前凭据；恢复必须有停用后新generation有效凭据。disabled时先签新凭据再显式激活，不形成“只能active签发而恢复又需新凭据”的死循环。active节点的有权管理员可手动先签新凭据再撤旧；这是现有签发/撤销操作的人工组合，不是自动续期或自动轮换服务。成功心跳不延长expires_at，离线也不冻结或无限延长有效期。

签发/撤销/停用/恢复/heartbeat共享Node锁及事务顺序；PostgreSQL使用实际行锁，SQLite使用受支持的事务/条件更新语义。停用先提交后的新heartbeat拒绝；heartbeat先获锁提交的观测可以保留，不声称已接受请求能被事后撤回。只靠进程内锁无法跨worker/重启保证，不采用该方案。

### F4 心跳只是观测

HeartbeatRequest：reported_config_revision?(非负int)、observed_at_raw?(≤128字符，保留原始不确定时间)、health?对象。health仅software_version?(1–64字符)与status?(ok/degraded/unknown)，拒绝未知字段，序列化大小≤8KiB，不接收任意日志/设备Secret。

HeartbeatRead：edge_node_id、服务端UTC last_seen_at、当前online、heartbeat_interval_seconds（默认30）、online_window_seconds（90）。请求不得自报权威last_seen_at、online、行政status或替换这些服务端参数；响应的30/90说明当前心跳策略，不构成可用性SLA。默认每30秒发送是客户端接入约定，本Change通过模拟客户端/可控时钟验证，不实现Edge Runtime常驻发送器。

服务端接收时写UTC last_seen_at、最近版本/健康观测；reported版本只写applied观测，不修改desired config_revision（本片固定初始1，无配置下发端点）、status或归属。NodeRead按active且0≤now-last_seen_at<90秒计算online，不用定时任务修改行政状态；从未心跳、pending/disabled或到达90秒均offline。合法最近观测持久存储，不能把在线心跳当GPU/存储健康实测或完整监控。

按已确认D13，允许网络抖动、丢包及有限次数/有限超时预算的重试，不要求云端必须在恰好30秒接收到请求；每次收到重试仍重新核验凭据，以本次有效接收时间更新观测。预算用尽不能无限忙循环，具体退避/重试上限由后续Runtime设计确定；本片用有限步模拟验证协议容忍性。失败、超时或超过90秒只影响online观测，不自动disabled/active节点；再次收到有效心跳可恢复online，不授予行政权限。90秒和凭据期限已确认，不再列为待决参数。

### F5 持久幂等及一次性明文

Idempotency-Key为8–128字符可打印ASCII受限集合。作用域含当前Tenant/Site/User、具体operation、目标Site或Node；仅存键摘要、规范化可写参数摘要及资源引用。规范化在应用动态默认/UUID/now之前完成，避免省略expires_at的重试变成异参；时间显式值按相同UTC瞬间规范化。

成功资源与幂等行同事务；唯一约束裁定并发，冲突回滚后重新读已提交结果。Node/Device重试返回201与原ID的当前可见状态；同键异参409；每次先做当前授权，降权后不能重放。凭据同键重试只返回409+credential_id，不缓存明文、再次签发或用加密缓存绕过“一次返回”边界；响应丢失时管理员查询/撤销后用新键重签。

本片不自动过期/淘汰幂等记录，保证重启/较晚重试不产生重复；记录只有最小摘要，不存视频或完整请求。生产容量和回收策略是后续独立评审门槛，不把24小时后悄悄复用旧键作为实现捷径。负责人已批准此行为；本片按其范围实现并通过两后端测试验证。

### F6 与既有规格及测试基线衔接

cloud-identity两个MODIFIED块完整保留原场景；原基础revision20261106_0001继续验证六表快照，新head额外验证4表。应用授权改为明确10表集合，不使用ALL TABLES默许未知表；保留schema USAGE、版本表仅SELECT，以及DDL/TRUNCATE/SET ROLE拒绝。直接create未批准canary表时应用无DML。

完整跑默认SQLite与专用PG共享/专属场景，新增必需场景被跳过或零收集须失败。复用pool_size=1与并发pool_size=8分别证明pg_backend_pid；至少覆盖同键Node/Device/凭据并发、停用/签发/heartbeat顺序、提交失败回滚和跨租户/跨场馆无副作用。旧112/150是历史基线，不是本片新增测试的固定期望。

### F7 代码与包边界

本片在services/cloud新增独立registry/Edge路由与认证服务，复用当前identity/manager/site_access、数据库事务与security摘要工具，不复制一套用户注册或跨项目import。OpenAPI快照和域文档逐项标出本片12个已实现，Session/Asset/Upload等仍未来；不把整篇v0.1文档改成“全部实现”。递增迁移和模块随wheel发布，并通过独立安装路径验证；不通过测试源码路径掩盖安装缺失。

### F8 来源与本片的偏差清单

| ADR方向 | 本片处理/新增细化 |
| --- | --- |
| D1/D2/D9 | 实施Node/Device固定归属、RESTRICT和停用历史；Asset等未来来源未建表 |
| D3 | 仅Owner/Admin管理和独立Edge身份；不实施Coach媒体grant/学员关系 |
| D4/D5/D6/D7/D10 | Session/Asset/上传/采集时间/离线协议不实施；不以通用幂等替代采集身份 |
| D8 | 复用11个管理操作+heartbeat；字段/长度按本Change实现；期限和30秒/90秒由D12/D13确认；不改现有19操作 |
| D11 | camera是随车移动的摄像头Device；一机一车为物理关系，不建Cart资源，不把kind/ID设计封死为不可扩展 |
| D12 | 7天默认/30天最长、一次性明文、不可恢复撤销、服务端UTC；长离线恢复仅作后续议题 |
| D13 | 30秒发送/90秒窗口及服务端last_seen_at，响应说明策略、有限重试不改行政状态，不作SLA |
| Notion节点原任务 | 版本/健康可查、身份可撤销由本片承接；健康summary不替代Runtime安装/完整运维验收 |

## Risks / Trade-offs

- 新表使旧六表断言失效 → 分开基础revision快照与head全集，新增失败/回滚用例，不删旧测试或修改历史迁移。
- 迁移后角色权限丢失 → 测试夹具在roundtrip后重新按批准表集合授权；迁移脚本不冒充生产角色部署。
- 行锁/唯一冲突处理在两后端有差异 → 共享行为测试+PG独立连接实测，超时/串行单连接不能冒充并发通过。
- 永久幂等摘要增长、短凭据需轮换、在线只反映最近通信 → 作为开发切片明确限制，生产容量/轮换自动化和监控另评审；本片不部署生产。
- D11–D13已确认并由负责人按PR #4批准head授权Apply；其他实施细化依照本Change验收和实现证据落实。

## Future Considerations / Known Limitations

- **长期断网凭据恢复（未来待决）**：例如Edge连续离线35天，已超过最长30天有效期。即使Node行政状态仍active，重新联网后旧凭据也必须401，云端认证及未来依赖该凭据的同步不能继续，直到通过受控方式重新签发并在Edge更新凭据。不得以修改旧expires_at、复活revoked凭据、无限离线宽限或一次心跳来绕过到期。
- 未来需另行评审离线节点重新验证、谁可恢复、secret的受控投递/设备端更新、审计及失败处理。本片仅提供既定管理员签发/撤销接口，不实现自动续期、离线身份恢复协议或自动密钥轮换服务，不创建相关新Change。不能将本地优先原则解释为云端凭据可无限有效；本地业务的离线身份/运行能力仍由后续Runtime方案负责，本片不承诺其已实现。
- 30秒发送节奏与有界重试属于接入契约，不扩张本片为完整Runtime调度、网络恢复或运维服务；90秒在线窗口不提供成功率、延迟或可用性SLA。
- D11已确认相机随小车移动；未来独立小车控制器、底盘遥测、运动/安全控制与其他Device.kind须扩展设备协议及领域模型，不在本片隐含实现，也不把摄像头安装固定等同泳池位置固定。

## Migration Plan

1. 基于明确Apply授权新增递增revision；不改20261106_0001，不连旧库/生产库。隔离库升级保留六表原数据，新建4表、约束/索引、版本标记。
2. 验证空库base→head、含六表数据base→head、head→基础revision→head、受控失败回滚；删除新表仅用于隔离测试降级，原六表数据必须保留。
3. 用应用身份实测正常CRUD与禁止权限、容器实际归属与精确清理；增加新测试包/迁移安装验证。
4. 更新真实模型/API/文档、PR/Notion局部证据。Apply结束后停止；独立Verify、Archive、主规格同步选择与Merge各按后续授权推进。
