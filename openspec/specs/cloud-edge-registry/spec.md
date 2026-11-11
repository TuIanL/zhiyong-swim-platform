# cloud-edge-registry Specification

## Purpose
为新版游泳视频平台提供机构和场馆范围内的节点、设备与独立节点身份管理，使后续采集来源、云端登记和健康观测有可撤销、可追溯、可持久验证的基础；本能力不提供媒体、分析或完整场馆运行时。

## Requirements

### Requirement: Tenant scoped registry management
服务 SHALL 允许当前Owner/Admin在本机构Site范围内登记、查询、修改节点/设备以及签发、列举、撤销节点凭据。Coach/Athlete即使有Site访问权也 MUST NOT 获得这些管理或读取权限。既有用户身份、成员关系与19个基础操作 MUST 保持兼容；节点列表 SHALL 支持status筛选，设备列表 SHALL 支持edge_node_id/status筛选。

#### Scenario: Current institution manager
- **WHEN** 有效Owner/Admin对本机构存在的Site执行节点或设备管理操作
- **THEN** 服务 MUST 返回该Site资源，创建返回201、列表/详情/修改返回200、合法凭据撤销返回204，且不要求其持有显式SiteMembership

#### Scenario: Unprivileged or foreign caller
- **WHEN** 结构合法的用户请求分别来自匿名、非机构成员、同机构Coach/Athlete或持有其他机构/场馆资源ID的Owner/Admin
- **THEN** 服务 MUST 分别返回401、404、403或404，不能暴露目标资源；拒绝的写入 MUST 不产生持久副作用

#### Scenario: Invalid or empty patch
- **WHEN** 已授权请求含未知/不可变字段、空PATCH、空名称或无效枚举
- **THEN** 服务 MUST 返回422；值合法但当前状态不允许的迁移 MUST 返回409，错误沿用detail.code/message结构

### Requirement: Immutable device provenance
每个Node SHALL 固定归属一个Tenant/Site，每个Device SHALL 固定归属同Tenant/Site的一个Node；创建后归属 MUST 不可修改。D11第一版Device.kind SHALL 仅支持camera，身份为摄像头本身；物理部署 SHALL 按一台摄像头固定安装于一台跟拍小车并随车移动，不解释为泳池固定位置。创建Device SHALL 要求父Node active。停用 MUST 保留稳定ID和登记历史，实体 MUST 不提供DELETE；迁场馆 SHALL 登记新ID，hardware_serial MUST NOT 作为身份凭证或全局唯一键。当前登记 MUST NOT 要求Cart实体/ID，通用Device标识、父归属和kind扩展点 MUST 保留。

#### Scenario: Mismatched parent scope
- **WHEN** 管理员在Site A登记Device但指定Site B或其他Tenant的Node，或数据库写入不一致的复合父引用
- **THEN** 服务或数据库 MUST 拒绝写入且回滚后无错误归属记录

#### Scenario: Attempted relocation or parent deletion
- **WHEN** 调用者尝试修改Node/Device的tenant/site/parent，或删除仍被新登记资源引用的父级
- **THEN** 不可变字段请求 MUST 被拒绝，新增归属外键 MUST 阻止级联抹除这些记录；已停用记录 MUST 仍可由授权管理员查询，既有无新引用的六表删除语义 MUST 保持

#### Scenario: Independent devices
- **WHEN** 同一机构登记相同名称或相同hardware_serial的不同设备请求
- **THEN** 不同请求 MUST 能保留独立Device ID，不能按序列号将其合并或授予对方身份

#### Scenario: Mobile camera identity and physical deployment
- **WHEN** 管理员登记固定安装于跟拍小车、随小车移动的摄像头
- **THEN** Device MUST 标识camera本身，不要求泳池固定机位或Cart记录；一机一车 SHALL 是部署关系，本Change MUST NOT 因此提供电机/运动/自动跟拍/安全协议

#### Scenario: Camera first with later type extension
- **WHEN** 同一Node登记多台各自安装于不同小车的camera，或请求以cart/其他未支持kind登记
- **THEN** 多台camera MUST 可取得独立通用Device ID，不限制为一Edge一Device；当前未支持kind MUST 返回422，未来类型 SHALL 通过独立领域/协议扩展，不更换既有Device ID或归属模型

### Requirement: Independent revocable edge credentials
Edge凭据 MUST 与User会话分离，只授权所属Node的heartbeat，并使用`Authorization: Bearer swim_edge_<opaque-token>`。User与Edge凭据 MUST NOT 互用。

#### Scenario: User and node identity separation
- **WHEN** User token用于Edge heartbeat，或Edge token用于用户节点管理/既有基础API
- **THEN** 服务 MUST 返回401，节点凭据 MUST NOT 通过用户身份路径获得成员权限

### Requirement: Bounded credential lifecycle
D12凭据默认有效期为7天、最长30天，以服务端UTC判断到期。明文 MUST 仅在成功签发响应中返回一次；数据库、普通读取、日志和幂等记录 MUST 不保存明文，普通读取也 MUST NOT 暴露摘要。过期/撤销凭据 MUST 被拒绝；服务 MUST NOT 自动续期、复活撤销凭据或提供自动轮换和离线恢复协议。

#### Scenario: Issue and revoke
- **WHEN** Owner/Admin签发凭据、列举凭据并随后撤销，再以该凭据发heartbeat
- **THEN** 仅签发响应 MUST 含secret；列表/撤销不含secret/hash；撤销后heartbeat MUST 返回401且不更新观测，重复合法撤销 MUST 返回204

#### Scenario: Credential deadline and timezone
- **WHEN** 在UTC及Asia/Shanghai连接配置下分别请求截止前、恰好截止和截止后的相同绝对时刻
- **THEN** 截止前且Node active的请求 MUST 可通过；恰好截止及之后 MUST 返回401；重启或连接复用 MUST NOT 恢复过期/撤销凭据

#### Scenario: Credential lifecycle audit boundary
- **WHEN** 有权User签发或首次撤销某EdgeCredential
- **THEN** 持久化凭据历史 MUST 记录签发/撤销User及服务端时间；相关User外键使用RESTRICT，普通读取不返回token摘要，应用日志不记录Authorization头或secret，撤销重放不得覆盖首次撤销主体/时间；本记录不扩展为通用审计事件系统

#### Scenario: Long disconnected edge needs controlled reissue
- **WHEN** Node连续离线35天后使用原凭据重新连接云端，即使其行政状态仍active
- **THEN** 原凭据 MUST 因已过最长30天有效期而返回401；云端认证及未来依赖该身份的同步 SHALL 在受控重新签发并更新Edge凭据前保持不可用，不得自动启用离线宽限或恢复协议

#### Scenario: Heartbeats do not renew or revive a credential
- **WHEN** 节点持续心跳、重试或重新联网，或者管理员想继续使用已撤销凭据
- **THEN** expires_at MUST 不因通信而延长，revoked凭据 MUST 不可恢复；只能由有权管理员受控重新签发，明文一次性及幂等不重放规则 MUST 继续成立

### Requirement: Administrative node lifecycle
Node SHALL 从pending开始，只有Owner/Admin可执行pending→active、pending/active→disabled、disabled→active。停用 SHALL 原子撤销该Node当时全部有效凭据；heartbeat MUST NOT 激活或恢复Node。恢复disabled节点 SHALL 要求停用后新签发的有效凭据，旧凭据 MUST 永久失效。Device SHALL 支持active/disabled切换而保留来源。

#### Scenario: Disable and restore
- **WHEN** 管理员停用Node并尝试用旧凭据恢复通信，随后为该disabled Node签发新凭据并显式激活
- **THEN** 旧凭据 MUST 始终被拒绝；新凭据在Node仍disabled时 MUST 被拒绝，合法激活后才可heartbeat；Device的父归属 MUST 不变

#### Scenario: Concurrent disable and credential issue
- **WHEN** 停用、凭据签发/撤销和heartbeat通过独立数据库连接并发执行
- **THEN** 结果 MUST 对应一个合法事务顺序；停用先于新签发时新凭据仍不能用于disabled Node，签发先于停用时该凭据 MUST 被撤销；停用提交后的新请求 MUST 不更新观测；事务失败 MUST 不留下只停用但未撤销的部分结果

### Requirement: Bounded trustworthy heartbeat observations
D13默认心跳发送间隔 SHALL 为30秒；云端 SHALL 允许网络抖动及有界重试，不要求恰好30秒收到请求。有效active Node的heartbeat SHALL 持久记录服务端UTC last_seen_at及最近一次有界health/版本/自报配置观测；客户端时间 MUST NOT 替代接收时间。online SHALL 仅在Node active且0≤服务端距最近有效heartbeat<90秒时为true。失败、超时或超窗 MUST NOT 自动修改行政status；自报值 MUST NOT 改desired config_revision、归属或权限。响应 SHALL 说明服务端last_seen_at、online及30秒发送/90秒在线策略；90秒 MUST NOT 被表述为可用性SLA。

#### Scenario: Self reported time and configuration
- **WHEN** 有效节点提交software_version、health状态、observed_at_raw或reported_config_revision
- **THEN** 服务 MUST 仅更新本节点观测；使用云端接收时间判在线，自报时间/高配置版本 MUST NOT 激活节点、变更desired版本或写入其他节点

#### Scenario: Bounded input and restart
- **WHEN** heartbeat含未知/越界字段、健康对象超过8KiB，或服务在合法heartbeat后重启
- **THEN** 无效请求 MUST 返回422且不更新last_seen_at；重启后合法最近观测/凭据状态 MUST 保留，90秒边界 MUST 使online为false，查询在线状态 MUST 不要求定时任务改行政状态

#### Scenario: Default cadence with jitter and bounded retry
- **WHEN** 模拟客户端按默认30秒节奏发送，并在网络抖动后以有限次数/超时预算重试合法心跳
- **THEN** 云端 MUST 对每次有效请求重新认证，以服务端接收时间更新last_seen_at；HeartbeatRead MUST 返回edge_node_id、last_seen_at、online、heartbeat_interval_seconds默认30及online_window_seconds为90，不将客户端时间或重试当作凭据续期

#### Scenario: Offline window does not disable the node
- **WHEN** active Node距最近有效心跳分别不足90秒、恰好90秒、超过90秒，随后收到有效心跳或继续失败
- **THEN** online MUST 分别为true、false、false；有效心跳可恢复online，但失败/超窗/重试耗尽 MUST 不改变行政status或恢复已停用Node权限，在线窗口 MUST 不作为服务SLA

### Requirement: Durable request idempotency
Node/Device创建及凭据签发 SHALL 要求有效Idempotency-Key，并按Tenant/Site、当前User、operation和目标资源隔离。相同键/规范化可写参数的并发或重启重试 MUST 只产生一个逻辑资源；异参 MUST 返回409。幂等结果 SHALL 持久保留且本Change不自动淘汰；重放 MUST 重新认证/授权，记录 MUST 不含secret或完整敏感请求体。

#### Scenario: Retried creation and rollback
- **WHEN** 相同主体/operation/目标的同键同参Node或Device创建通过不同连接并发，或在提交后丢失响应并重试
- **THEN** MUST 仅有一个资源与一个已完成幂等记录，重试返回201及同一资源ID/当前可见状态；资源和幂等记录 MUST 同事务提交，失败 MUST 二者均无残留

#### Scenario: Key conflict or revoked access
- **WHEN** 同一作用域键携带不同参数，或原管理员失去当前管理权限后重放原请求
- **THEN** 前者 MUST 返回409 idempotency_conflict；后者 MUST 按当前身份/角色拒绝，不能由缓存绕过撤权；不同主体或operation MUST 不共享结果

#### Scenario: One time credential response
- **WHEN** 一次凭据签发已经提交，客户端以相同键/参数重试或并发重试
- **THEN** MUST 不再次签发或重放secret，仅在当前管理员仍有权限时返回409 credential_secret_not_replayable及其可见credential_id；secret MUST NOT 进入幂等缓存
