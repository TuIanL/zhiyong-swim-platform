# M4 v1 云边可靠同步 API 契约

**负责人已签认设计基线 · 后续实施草案**

本文是新任务控制和同步线路、事件信封、收据、错误、样例及运行验收矩阵的唯一契约入口。M4.2/M4.3 按实际承接范围各自提交行为 Delta。R1–R8、19 个原始 Scenario 及 T/A/C/L 编号延续自 [二轮 Propose](https://github.com/TuIanL/zhiyong-swim-platform/commit/a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b)。现有媒体接口和状态以 M3 契约为准。[架构与锁序](../architecture/cloud-edge-sync-v1.md) · [ADR 0004](../decisions/0004-cloud-edge-sync-v1.md) · [既有 M3 契约](cloud-capture-media.md)

## Cloud 控制 API

### D4 云端任务控制与终态

<a name="cloud-control"></a>

#### 创建并指派

- 未来实现入口为 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks`。只允许当前有效 User 会话及目标 Tenant 的 Owner/Admin。无效会话或 Edge 凭据返回 `401`。非成员、不可见 Site、越 Tenant/Site 的 Session、Node 或任务以 `404` 隐藏。同场馆可见但无管理角色的 Coach/Athlete 返回 `403`，Session/Asset 读 grant 不增加控制权限。
- 请求含 `session_id`、`edge_node_id`、`work_kind=capture_demo` 与 `Idempotency-Key`。结构、缺键、非法键和未知字段返回 `422`。对于新写入，在锁后按已有任务、父 Session 状态、Node 状态的顺序校验。已存在任务按 `task_exists` 处理。无现存任务时要求父 Session 属于路径 Tenant/Site 且为 `planned` 或 `recording`，Node 同场馆且为 `active`。Session 已完成或取消，或可见 Node 的行政状态非 active，返回 `409 state_conflict`。心跳 `online` 只供观测。
- 一次提交创建 `task_id`、`assignment_id`、初态 `assigned`、`task_version=1`、节点序号、`training_task.assigned` 下发记录和请求收据，成功返回 `201` 与含任务/分配标识、初态、初始版本及命令序号的收据。任何一项失败则全部回滚，禁止创建未分配的任务或单独重派。
- Q1 确认**整个 v1 生命周期唯一**。同 `(tenant_id, site_id, session_id)` 最多一个任务，同任务最多一个分配，均以数据库唯一约束保护。任务成为 `completed`、`failed` 或 `cancelled` 后仍占名额，任何新键再建均返回 `409 task_exists`。新训练如需另起任务应对应真实的新 Session。活动任务唯一方案已舍弃。
- 创建和取消键都按 `(tenant_id, site_id, user_id, operation, key_digest)` 隔离。先校验当前会话、角色及请求目标可见归属，再查当前作用域收据。同键同规范化参数重放原成功状态和逻辑收据，即使节点或 Session 此后已终结；收据不是当前任务视图。同键异参（含目标、Node 或期望版本）返回 `409 idempotency_conflict`。仅在未命中成功收据时评估新操作的状态门槛。并发主键/唯一冲突应回滚并按当前授权解释为重放或冲突，收据和副作用均至多一次。创建与取消为不同 operation。

#### 取消与竞争

- 未来实现入口为 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks/{task_id}/cancel`，使用相同控制权限和 `Idempotency-Key`。请求只接收 `expected_task_version` 正整数。服务端设置 `operator_cancelled`，父 Session 取消联动路径使用 `session_cancelled`。指定任务必须属于受权的场馆。停用节点的任务仍可由有权操作人取消。
- `assigned/accepted` 且期望版本匹配时，同事务写入 `cancelled`、递增到 v2、追加唯一取消命令并保存收据。返回 `200` 和包含 `task_id`、`assignment_id`、`status`、`task_version`、`sequence`、`cancelled_at`、`reason` 的收据。同键同参重放返回原收据。同键异参先按幂等冲突处理。已取消任务用新键、期望版本为取消前版本或当前取消版本时，返回原取消结果，取消版本、时间、原因和命令数量保持一致。可取消或已取消的任务遇到其它期望版本时返回 `409 version_conflict`。`completed/failed` 的新取消返回 `409 state_conflict`，无任务或命令写入。
- 分配、终态投影及父 Session 取消先序列化父 Session，再锁受影响的任务行。先提交的合法终态生效。父 Session 先取消时，同事务取消未终结任务并追加命令，同时按既有 M3 语义收口未完成媒体。任务先完成时，合法的父 Session 取消继续独立处理，保留任务和既有媒体历史。单独任务取消只控制该分配。
#### 取消后的离线补投与安全停止

<a name="late-cancellation-replay"></a>

- Cloud 按当前有效 Node 身份核对 Tenant、Site、Node、Session、Task 与 Assignment，再校验 Event ID、序号与因果。对 Task 已合法取消的新事件，同一 Assignment 的合法连续上行事实在同一事务写入 Inbox、原序号、收据及最小审计。迟到 `training_task.accepted`、后续 `capture.recorded` 和合法 `training_task.finished` 均返回 HTTP 200、`disposition=conflict_recorded`、`code=task_cancelled`。收据保留原 `event_id`、`assignment_id`、`sequence`。Task 正式终态保持 `cancelled`，不重建 Task 或 Assignment，不创建正常采集投影、上传意图或 `VideoAsset.ready`。
- 因果来自同一 Assignment 已消费的 Inbox 接单事实。处置为 `applied` 或 `conflict_recorded` 的合法接单都可作为后续 `capture.recorded`、`training_task.finished` 的接单前置。该证据与正式 Task 投影分开保存，其他 Assignment 的接单不能借用。Cloud 保存节点作用域、身份已核验的分配关联、事件 ID/类型/序号、原命令版本、信封指纹、服务端入库时间和处置。采集另留来源设备及 capture ID，终态另留实际 outcome。审计保留最小事实，遵守事件白名单和原片本地边界。
- 对首次消费的合法连续 `capture.recorded`，若 Task 已合法取消且同归属的来源 Device 也已停用，收据的单一 `code` 固定为 `task_cancelled`。同一消费事务的内部冲突审计使用有序字符串数组 `conflict_reasons`，值恰为 `["task_cancelled","device_disabled"]`。第一项为对外收据原因，第二项为设备停用原因，元素值和顺序固定，不重复。该字段只定义内部审计的逻辑表示，API 收据沿用原字段，物理存储由 M4.3 定义。该事务仅消费一次序号，无正常采集投影。仅设备停用冲突仍按 Q7 返回 `device_disabled`。同 ID、同内容且当前身份和归属有效的重放返回原持久化收据，即使设备状态随后改变也不重算处置或重写审计。见 [W3.1](#w3-vectors)。
- `completed` 与 `failed` 记录实际完成或失败的 Edge 终态。Edge 应用取消和写执行终态使用本地持久记录定序。终态已产生时，即使随后收到或应用取消，仍补投原终态、原序号和原命令版本。Cloud 已取消或 Edge 尚未收到命令，以及仅收到 HTTP 结果或发出 Command ACK，都不能产生 `stopped_by_cancel`。
- `stopped_by_cancel` 只由 Edge 已持久应用同一 Assignment 的取消命令、且执行器因该命令实际安全停止后产生。Edge 持久关联取消命令版本与实际停止事实；沿现有信封上报对应的 `task_version`（v1 为 2）及 `outcome`。Cloud 核对该分配的已提交取消命令、版本及先前合法接单，持久审计该版本、取消原因/命令关联及停止 outcome，再以同一 `task_cancelled` 冲突收据消费序号。Command ACK 的到达不是上行验证前置，因其可丢失。一般本地安全挂起按 [D5](../architecture/cloud-edge-sync-v1.md#offline-safety) 处理。
- 已认证且归属正确的同 ID、同内容重放返回原逻辑收据，不再消费或写审计。同 ID 异内容或同序号换 ID 为 `409 event_conflict`，缺序为 `409 sequence_gap`。连续序号引用未来版本、缺少同分配已消费接单、报告第二个执行终态，或 `stopped_by_cancel` 缺少相符取消命令及版本时，返回 `422 validation_error`。无效身份和越域分别返回 401/404。这些拒绝均不消费序号或生成成功收据。完整轨迹见 [W1.1–W1.7](#w1-vectors)。

## 事件和同步线路

### D2 v1 信封、流与负载

<a name="event-envelope"></a>

v1 请求使用严格 JSON 对象和字段白名单，事件版本为整数 `schema_version=1`。已签认的单事件上限为 8 KiB，每个下发页最多 50 条，整数使用 JSON 安全整数范围。Q6 的具体超时、退避与恢复参数仅适用于[已签认的隔离开发与测试配置](../architecture/cloud-edge-sync-v1.md#timing-register)。上行每请求一事件，避免批次部分提交语义。

| 字段 | 规则 |
| --- | --- |
| `event_id`, `type`, `schema_version` | 生产端首次原子持久化时生成 UUID。重试复用完整信封。事件 ID 在各接收账本内唯一，版本或字段变化需按兼容规则显式处理 |
| `tenant_id`, `site_id`, `edge_node_id` | Cloud 从当前节点凭据绑定取得并逐项校验；Edge 以本机受控绑定核对下行。请求提供的值只是声明 |
| `session_id`, `task_id`, `assignment_id` | Cloud 生成稳定 UUID。任务与 Session 分离。Q1 确认每个 Session 整个 v1 生命周期最多一个任务、每任务固定一次分配和一个节点。终态保留名额，分配身份关联作用域及父任务 |
| `task_version`, `sequence` | `task_version` 记录 Cloud 命令版本，分配为 1，首次取消为 2；上行回显生成事实时本地已应用的版本。下行 `sequence` 为节点流序号，上行 `sequence` 为分配流序号，两个方向分别从 1 开始严格递增。成功回报或 ACK 不会制造新的命令版本 |
| `occurred_at`, `payload` | `occurred_at` 是生产方声明的 UTC 时刻，用于诊断；Cloud 单独记录 `received_at`。任务竞争、凭据截止和重放排序不取客户端墙钟。载荷只接受下表字段 |

| 方向与类型 | 载荷 | 处理 |
| --- | --- | --- |
| Cloud → Edge `training_task.assigned` | `work_kind=capture_demo`（合成验收工作类型） | 持久保存为待业务接单。追平本轮固定控制水位后才可提交本地接单记录及上行事件 |
| Cloud → Edge `training_task.cancelled` | `reason` 枚举 `operator_cancelled` / `session_cancelled` | 持久取消。待执行任务停止启动，运行中的任务协作停止 |
| Edge → Cloud `training_task.accepted` | 空对象 | 上行首条。保存本地已接单的事实 |
| Edge → Cloud `capture.recorded` | `capture_id`、`device_id`、可选 `captured_at_utc` 与 `device_observed_at_raw`（≤64 字符） | 每次采集一次 ID，至少记录来源。允许两个时间字段都缺省以表达未知；原始设备时间不被服务端时间填补 |
| Edge → Cloud `training_task.finished` | `outcome=completed/failed/stopped_by_cancel` | 每个已接单分配最多一个真实执行终态，原信封可重复投递。Cloud 按 D4 和提交顺序投影或记录冲突。 |

接收端按已验证、规范化的不可变信封计算内容指纹。字段顺序和 JSON 空白不改变含义，重复键与未知字段拒绝，UUID 规范为小写连字符格式，UTC 时刻统一为等义的 Z 表示，可选时间字段缺失时统一省略，显式 null 拒绝。原始设备时间字符串按原值保留。规范化正反例见[本契约样例](#examples)。Inbox 主键为 `event_id`，另用作用域、分配及序号做唯一约束；同序号异 ID 和同 ID 异信封均为完整性冲突。采集另按 `(tenant_id, site_id, edge_node_id, assignment_id, capture_id)` 保证同一业务事实只有一份；两个独立采集可有相同文件哈希。请求级 `Idempotency-Key` 继续服务已有管理和上传接口，独立于事件去重。

### D3 事务、传输与 ACK

<a name="delivery"></a>

| 概念 | 持久边界 | 可证明的事实 |
| --- | --- | --- |
| 持久接收 | Edge 事务提交命令 Inbox、命令本地效果（如待接单或取消标记）及连续游标 | 此命令已可从本地账本恢复。收包、解析或尚未提交的事务均不足以推进游标 |
| Command ACK | Edge 在上一步提交后发送 `through`，Cloud 记录已确认命令水位 | 此水位以内的命令已在 Edge 连续持久应用。Command ACK 丢失可重发，ACK 成功与否不影响已经持久化的本地接单 |
| 业务接单 | 追平一轮固定水位后，在本地确认任务未取消、无安全挂起且接单资格已在本轮有效同步中得到确认。事务写入本地已接单状态与 `training_task.accepted` Outbox | 允许离线调度该任务。Cloud 只有提交上行 `accepted` 事件后才能把任务投影为 `accepted`。若追平前断网或失去有效认证，本轮待接单项留待下次认证同步 |
| 实际执行 | Edge 调度器在分配级串行化下复核已接单、无已应用取消、无安全挂起，持久取得执行资格，用相同执行身份启动。重启按检查点恢复或转人工 | 执行由本地状态与执行器证据证明。v1 无独立上行开始执行事件；接单回报、Command ACK 和 HTTP 200 均不能证明实际开工 |

Cloud 对上行事件的收据独立于 Command ACK。上行收据只确认指定事件已投影或已记录冲突。

Q4 确认 Edge 使用有效节点身份主动发起 HTTPS/TLS 拉取与回报。Cloud 和 Edge 均以各自持久数据库作为队列与收据的事实源；消息队列和常驻推送服务无需成为首片依赖。

| v1 待实施路由 | 请求与响应边界 |
| --- | --- |
| `GET /api/v1/edge/sync/commands?after=0&through=…` | 从本地已持久应用游标读取下一页，只返回当前节点的命令。首请求返回页及固定追平目标 `through`，后续页以该值为上界。快照后新提交的指令下轮获取 |
| `POST /api/v1/edge/sync/command-acks` | `{through: N}` 确认本地连续持久消费到 N。Cloud 推进本节点交付水位但不得回退，返回当前 ACK 水位；超过已知节点流尾的值拒绝 |
| `POST /api/v1/edge/sync/events` | 认证、作用域和信封检查后按序消费。200 携带 `event_id`、`assignment_id`、`sequence`、原处置 `disposition=applied/conflict_recorded`、可选有界 `code`。同内容重投返回同一逻辑收据。200 的冲突收据确认已记录和结案，发送端保留冲突线索 |
| `GET /api/v1/edge/sync/reconcile?assignment_id=…` | 返回节点命令头和 ACK 水位。指定本节点分配时附 `next_edge_seq`、`task_version`、`projection_revision`、`status`（当前任务状态）；无分配查询时只返回节点水位。边缘发送端以当前投影对账，ACK 重放不携带覆盖性任务快照 |

- 先校验当前身份与可见归属，再查旧收据。认证失败 `401 edge_unauthorized`，越范围 `404`。不支持的版本、方向或格式返回 `422`。序号空洞返回 `409 sequence_gap` 及期望序号；事件身份冲突返回 `409 event_conflict`；不可从现存历史恢复的游标返回 `409 recovery_required`。上述错误不推进 Inbox 或交付水位。结构合法、权限匹配但与已提交业务终态冲突的下一条事件，原子记录 `conflict_recorded` 并消费该序号。
- Cloud 任务命令及下发日志同事务提交，序号以事务内节点流计数分配，回滚不留空洞。Edge 连续应用命令时提交 Inbox、命令效果和本地游标，提交后才发送游标 ACK。命令重复接收只返回已持久处理进度。业务接单和调度按本节四个边界推进。
- Edge 每条本地采集或终态与 Outbox 同事务入库。Cloud 将 Inbox 收据、流位置、任务投影或结构化冲突记录同事务提交，再返回收据。发送端按[收据匹配规则](#receipt-scope)验证后才在本地确认对应待发项。同条件重复接收仍计一次业务效果，两个方向都允许至少一次投递。并发重复、重启及超时后仍按已提交结果恢复。
- 发送端每条流只派送头部未确认项，分配间不要求总顺序。超时、断网、429/可重试 5xx 使用带抖动的有上限指数退避，429 尊重服务端提示。耗完一轮预算后保留记录与下一次尝试时机。422、404 或完整性冲突暂停对应流，保留人工诊断入口。永久拒绝不能将原 ID 改载荷重发或跳号。其它分配可继续。
- 重连先用本地游标拉取指令直至固定水位，再补送 Command ACK 并按序重放本地 Outbox。Command ACK 丢失时重发已持久接收的水位。上行收据丢失时重投原事件。最后读取对账结果，比对双向水位、当前任务投影和本地待发记录。投影依据递增的 `projection_revision` 应用；Cloud ACK 水位只作线索。Cloud 期望序号领先时仍需补取具体收据，不能仅凭水位删除未确认项。已有节点缺少已初始化的本地账本时，启动应挂起并报告恢复需求，禁止自动用空库从零重放。只有已验证为新绑定的节点能初始化零游标。存在无法补齐的本地缺口或超出可重放历史时，同样挂起受影响的节点/分配并人工恢复；v1 无跳游标重置。


### 上行收据作用域匹配

<a name="receipt-scope"></a>

Cloud 以当前有效的节点认证绑定推导 Tenant/Site/Node，客户端在信封中声明的字段只用于比对。Edge 将发请求时的认证作用域和具体请求关联到不可变的本地 Outbox 信封。处理成功响应时，先核对该请求的 Tenant/Site/Node 与本机当前认证上下文及待发信封一致，再核对响应的 `assignment_id`、`event_id`、`sequence` 与该待发项一致，且 `disposition` 为 `applied` 或 `conflict_recorded`。网络层必须能关联响应和具体原请求，不按到达顺序推定。相同 Node 重新认证后，对账并从当前绑定重发原信封。

全部匹配时，仅确认该 Outbox 项并保存原处置。作用域、任一 ID、序号或处置不符，以及无法关联原请求时，保留待发状态和诊断线索。重复的同一匹配收据幂等。水位和普通 HTTP 200 不能代替匹配收据。响应继续只携带 `event_id`、`assignment_id`、`sequence`、`disposition` 和可选 `code`。[S1 定向向量](#s1-vectors)

### 响应与结构化错误

<a name="errors"></a>

控制和同步请求按适用线路使用 User 或 Edge Bearer，每次查当前身份和资源。输入和响应 JSON 字段由以下表格及样例约束。复用既有 `detail.code` / `detail.message` 错误对象，消息供诊断。调用方依据 HTTP 状态和稳定 code 分支处理。只有相同已授权作用域下的 `sequence_gap` 可附 `detail.expected_sequence`。

| 输入或结果 | 状态与 code | 水位及业务写入 |
| --- | --- | --- |
| 未认证、凭据到期/撤销/Node 停用 | 401，User 用 `unauthorized`，Edge 用 `edge_unauthorized` | 无写入、无收据 |
| 资源不存在或越作用域 | 404 `not_found` | 无资源详情、无写入 |
| 可见场馆内 User 角色不足 | 403 `forbidden` | 无写入 |
| 信封超过 8192 字节 | 413 `event_too_large` | 读取阶段拒绝超限信封，422 用于限额内的格式错误，错误不透露资源状态；无写入 |
| 无效键、重复 JSON 键、非法枚举、未知字段、方向或版本不支持、页数非法、D4 因果校验不通过 | 422 `validation_error` | 不消费序号，无成功 ACK 或收据 |
| 上行序号有缺口，或 `through` 超当前可确认命令头 | 409 `sequence_gap` | 上行附期望序号；不越缺口。下行从已提交本地水位重拉 |
| 历史或本地账本无法恢复 | 409 `recovery_required`（本地对应同名状态） | 挂起受影响的节点流或分配并保留全部证据 |
| 同事件 ID 异信封，或同序号异事件 ID | 409 `event_conflict` | 原收据/投影不变 |
| 任务控制重放冲突或非法状态 | 409，按 D4 返回 `idempotency_conflict` / `task_exists` / `state_conflict` / `version_conflict` | 无新任务、命令或业务状态 |
| 合法上行被应用，或确认为有权领域冲突 | 200，`disposition=applied/conflict_recorded` | 提交 Inbox、消费序号，后者只写最小审计；`code` 可为 `task_cancelled`、`device_disabled` |
| 网络失败、可重试 5xx、限流 429 | 瞬态失败；429 尊重有效的 `Retry-After` | 原信封留队，有界重投；不凭失败判断服务端是否已提交 |

上行 8 KiB 计单个 JSON 信封的 UTF-8 实际字节数，包含载荷和空白，排除 HTTP 头。下行按同一单事件上限编码，页结果最多 50 条。命令页返回 `commands`、固定 `through`、本页连续尾部 `next_after`。ACK 请求只接收 `through`，成功返回 `acked_through`。对账返回 `command_head`、`acked_through`，有 `assignment_id` 时追加该分配的 `assignment_id`、`task_version`、`projection_revision`、`status` 和 `next_edge_seq`。第一次 GET 命令省略 `through`，后续带回服务端给定的水位。任何 GET 或重投均需重验当前节点和范围。

### 规范化与事件指纹

校验前拒绝重复 JSON 属性（包括解码后同名），按严格白名单解析。UUID 规范为小写连字符形式。带明确时区的时间统一为 UTC `Z`，秒小数最多六位并去掉尾随零。可选时间缺失时省略，显式 null 拒绝。原始设备时间保留解码后的字符串内容，不进行 Unicode 转写或推断。整数范围为 0 到 2^53−1，序号和版本从 1 开始，游标允许 0。拒绝浮点、布尔或字符串冒充数值。

接收端对规范化后的完整信封计算 SHA-256。键按字典序排列，紧凑 UTF-8 JSON，非 ASCII 字符直接编码，控制字符、引号与反斜线按 JSON 转义，`/` 不转义。指纹不在网络中作为授权凭据。字段排序、JSON 分隔空格和等义 UTC 表示均不改变规范化值。更换事件 ID、流位置、时间的实际值或内容会改变逻辑信封。

## Q5 B 人工批准的上传路径

<a name="approved-media"></a>

M4.4 必验独立人工批准路径。事件同步协议白名单不接受批准对象、原片、上传令牌或签名 URL。测试操作者在已授权会话中确认具体待上传资产、目的和当前权限。测试编排记录 Tenant、Site、Session、`capture_id`/本地资产标识、预期 SHA-256 与大小、目的、现有发起身份及批准引用。获得 M3 返回后将该记录绑定具体的 `asset_id` 和 `upload_session_id`。批准与实际文件不匹配时停止，不静默换件或扩大范围。

| 独立步骤 | 所用 M3 接口与约束 |
| --- | --- |
| 批准前 | M4 回报采集和任务执行事实，Cloud 可以 ACK。无 UploadSession 或字节请求 |
| 人工执行已批准的上传 | 测试中选用有 S-manage 的既有 User 凭据，调用现有 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/upload-sessions`。传经验证 fixture 的 `expected_size_bytes`、`expected_sha256` 等原字段与独立 `Idempotency-Key`。记录服务端生成的 Asset/UploadSession。User 是 M3 发起主体，测试身份并非生产审批角色 |
| 传输、恢复 | 原发起者使用现有 `part-urls`、签名 PUT、`PUT …/parts/{part_number}` 确认和 `GET …/parts` 对账，复用同意图与版式。每次授权按 M3 检查。撤权后不能从同步取得补签、确认或完成许可。已经签发的 URL 仍受自身 TTL 及现有对象约束 |
| 校验与发布 | `POST …/complete` 接受为 `completing`。实际对象版本、SHA-256、长度和媒体有效性由原 M3 流程验证，最终再核对现行身份与授权后成对写 `completed/ready`。待验证时撤权只能按 M3 的失败规则收口 |
| 本地保留 | M3 完成和 M4 ACK 分别记录，原件继续保留。已取消 Session、发起人限制、授权失效与 URL 生命周期沿用 M3 |

测试如另跑 Edge 发起变体，复用现有 `/api/v1/edge/sessions/{session_id}/upload-sessions` 及原发起 Node、设备来源、凭据生命周期校验；测试所需用户凭据不交给 Edge 同步客户端。真实视频审批、隐私及生产前置见 [ADR 0004](../decisions/0004-cloud-edge-sync-v1.md#production-gates)。

## 设计基线的需求与场景

<a name="requirements"></a>

### Requirement: R1 Scoped identities and immutable envelopes

同步 SHALL 采用版本化、按方向白名单校验的信封。固定事件 ID、节点归属、任务与分配标识、流版本及载荷 MUST 在重投时保持一致。Cloud MUST 在读取业务数据、写入或返回旧收据前，以现行节点身份和资源关系核验归属。

#### Scenario: S1.1 Scope and actor mismatch
- **WHEN** 用户会话调用节点同步，或有效节点访问其他机构、场馆、节点的分配、设备或流
- **THEN** 服务 MUST 分别返回 401 或隐藏资源的 404，不返回收据，不推进游标，不改变任务投影。

#### Scenario: S1.2 Unknown version or wrong direction
- **WHEN** 已认证且归属匹配的信封使用不支持的版本、反向事件或未知字段
- **THEN** 接收方 MUST 拒绝应用且保留未确认事件。协议或格式错误返回可诊断结果，事件不得取得成功 ACK 或被静默跳过。

### Requirement: R2 Commands and facts have separate authority

Cloud SHALL 下发任务分配和取消，Edge SHALL 回报持久接收、采集元数据和执行终态。两端 SHALL 按权威字段分别存储控制意图和观察事实。任务回报 MUST 仅作用于对应任务的投影，正式 Session、授权、媒体可用状态和已发布报告继续由各自云端业务路径决定。

#### Scenario: S2.1 Capture stays local by default
- **WHEN** Edge 回报与已分配任务关联的合法采集元数据
- **THEN** Cloud MUST 记录该采集事实。该事件 MUST NOT 创建上传意图、传输原片、创建 `ready` 资产、推进正式 Session 或授予读取权限。

#### Scenario: S2.2 Execution does not publish results
- **WHEN** 已接收任务的合法成功回报投影为任务完成，或 Edge 尝试通过事件写入分析结果、报告或媒体验证字段
- **THEN** 合法回报 MUST 只更新任务视图。越界字段或事件 MUST 被拒绝。M3 已验证对象才可进入原有 `ready` 流程，报告发布需要独立的授权链。

### Requirement: R3 Durable enqueue and acknowledgement

生产端 SHALL 在同一事务保存业务变化与待发送事件。接收端 MUST 在同一事务持久记录去重结果及其业务作用，并在提交后才确认。Command ACK MUST 只表示 Edge 已将连续命令、其本地效果与游标持久提交。业务接单以独立的本地事务及 `training_task.accepted` 表示，实际开始执行还有专门的本地门槛。

#### Scenario: S3.1 Transaction failure has no partial effect
- **WHEN** 任何一端在生产业务变化与 Outbox 提交前或消费收据与业务结果提交前中断
- **THEN** 重启后 MUST 观察到同事务内容皆可见或皆不可见。未提交的消费 MUST NOT 返回成功 ACK。

#### Scenario: S3.2 Commit succeeds and acknowledgement is lost
- **WHEN** 接收端已提交但响应丢失，生产端用相同身份、事件 ID 和内容重投
- **THEN** 接收端 MUST 返回相同逻辑收据或游标确认，业务效果至多一次。Edge MUST 能补送下发 ACK，且重复命令不重复接单。

#### Scenario: S3.3 Same identity with changed content
- **WHEN** 当前有权节点复用已登记事件 ID 并修改内容、流、序号或归属，或用不同事件 ID 占用已消费序号
- **THEN** 接收端 MUST 返回完整性冲突，保留原收据与投影，不承认为重复成功；发送端 MUST 保留待诊断项。

### Requirement: R4 Ordered replay and reconciliation

下发 SHALL 使用节点级单调游标，Edge 上行 SHALL 使用分配级连续序号。同一流 MUST 依序消费，时间戳仅供审计。重连 SHALL 先同步缺失的控制指令，再补投持久事实并核对收据、游标与当前投影。

#### Scenario: S4.1 Gap and reordered delivery
- **WHEN** 任一流先收到后续项，前项缺失
- **THEN** 接收端 MUST 指出期望位置或要求重拉，不越过缺口。补齐后重放 MUST 得出与按序投递相同的有效投影。

#### Scenario: S4.2 Reconnect with both sides behind
- **WHEN** 断网前有未确认的回报，断网中 Cloud 又提交了新的任务控制指令
- **THEN** Edge MUST 从本地已提交的游标补拉有效指令，再使用原 ID 重放 Outbox。Cloud MUST 返回当前权威投影供对账，历史 ACK 不得覆盖该视图。

#### Scenario: S4.3 Cursor no longer recoverable
- **WHEN** 本地游标丢失或请求位置超出可重放历史，且无法凭已验证的持久状态补齐
- **THEN** 系统 MUST 报告需人工恢复、保留任务与待发送事件，不得快速跳过命令或把云端游标冒充本地持久凭据。

### Requirement: R5 Local continuity and bounded retry

已业务接单的任务 SHALL 在一般断网或凭据自然过期时按本地状态继续，并持久记录事实。网络失败 SHALL 以有界退避重试，预算用完后保留队列。待接单任务 MUST 经控制流追平并提交业务接单事务才可启动。已验证的节点停用或本地停机指令 MUST 阻止新开工，并触发运行中的任务安全停止，细节见设计 D5。

#### Scenario: S5.1 Offline restart and retry exhaustion
- **WHEN** 已业务接单的任务开始执行后 Edge 断网、进程重启且达到一轮重试预算
- **THEN** Edge MUST 从本地状态恢复同一任务或标记需人工恢复，保留待同步事实及原 ID，禁止静默丢弃。待接单任务不得仅凭持久接收、ACK、重启或时钟变化而启动。

#### Scenario: S5.2 Permanent rejection needs review
- **WHEN** 上报遇到不可重试的格式、归属或完整性错误
- **THEN** Edge MUST 保留未确认记录和脱敏原因，停止该流盲重试并允许其他无关流继续。未获结构化终态收据不得视为已送达。

### Requirement: R6 Cancellation and completion serialize at Cloud

同一任务的 Cloud 取消及终态回报 SHALL 受同一条件化状态转换约束。Cloud MUST 保留先提交的合法终态以及后到、经过授权的冲突事实。Edge 在持久应用取消后 MUST 禁止该分配新开工，并协作安全停止仍在运行的执行；已形成的本地事实仍可按契约回报。

#### Scenario: S6.1 Cancellation wins before completion
- **WHEN** Cloud 任务取消先提交，或父 Session 取消先提交并在同事务封住该未终结任务，随后收到合规的成功回报
- **THEN** Cloud MUST 保持任务 cancelled，持久记录冲突并返回冲突收据。Edge MUST 保留本地产物，Cloud 不得据此发布产物或将任务改回 completed。

#### Scenario: S6.2 Completion wins before cancellation
- **WHEN** 合法终态回报在 Cloud 已提交为 completed，随后提交任务取消请求
- **THEN** 任务取消请求 MUST 报告状态冲突且不产生取消指令。独立的 Session 取消按既有规则处理，既有任务成功事实仍可审计。

#### Scenario: S6.3 Cancel arrives before dispatch starts
- **WHEN** Edge 在同一次补拉中发现一个尚未业务接单的分配及其后续取消，或在已业务接单但尚未开始时持久应用取消
- **THEN** Edge MUST 记录取消并阻止新执行。对已经执行过的本地事实 MUST 保留可追溯记录。

### Requirement: R7 Credential recovery preserves node boundaries

同步 SHALL 使用试图访问当时仍有效、已注册且 active 的节点身份。自然过期、凭据撤销或节点停用均 MUST 拒绝同步与旧收据读取，通信 MUST NOT 延长凭据期限。Edge 的本地执行/安全停止由已验证的本地可知状态按 [D5](../architecture/cloud-edge-sync-v1.md#offline-safety) 决定，单一 401 不推断原因。受控重新签发后的原节点 SHALL 可以重放原有事件；不同节点 MUST 无法继承队列或确认游标。

#### Scenario: S7.1 Credential expires while isolated
- **WHEN** active 节点断网 35 天并以原凭据重连，或在服务端 UTC 恰好到达失效时请求重放
- **THEN** Cloud MUST 返回 401，无新收据与业务写入。Edge MUST 暂停云端同步并保留本地任务和 Outbox，等待受控更新凭据。没有独立安全停止指令时，已接单任务仍可本地执行。

#### Scenario: S7.2 Reissue for the same node
- **WHEN** 有权人员受控签发相同节点的新凭据并更新本机，节点处于 active 且当前资源权限仍有效
- **THEN** 节点 MUST 能按原标识和游标对账并恢复投递。旧凭据及其他节点的新凭据 MUST 仍无法访问这些收据、任务或历史。

### Requirement: R8 Existing media and identity contracts continue to apply

同步事件 SHALL 只包含允许的有界元数据。另行获准的二进制传输 SHALL 复用 M3 UploadSession 与既有身份、资源、有效期及整对象验证约束。同步 ACK MUST 只确认事件处理结果。按 Q5=B，M4.4 SHALL 单独验收明确人工批准的合成视频 M3 上传。批准绑定 Session、具体资产及用途，M3 执行现行授权复核。

#### Scenario: S8.1 Distinct media and event acknowledgements
- **WHEN** 采集事件已 ACK，但视频尚未获准上传，或已获准上传并处于 `completing`
- **THEN** Edge MUST 保留本地副本。Cloud MUST 不把事件 ACK 或分片完成当作 `ready`，且短期授权、撤权和整对象校验继续生效。

#### Scenario: S8.2 Legacy clients and resources remain compatible
- **WHEN** M1–M3 客户端继续使用原身份、Session、幂等上传或媒体读取操作，或历史 Session 从未分配任务
- **THEN** 原有请求和状态语义 MUST 保持兼容。服务 MUST 不为旧行自动生成任务、事件、媒体上传或读取权限。

## 协议样例

<a name="examples"></a>

下列样例均使用合成数据。完整的输入、预期结果和后续证据见 [验收矩阵](#acceptance-matrix)，涉及本地确定性与 PG 竞态的细节见 [架构](../architecture/cloud-edge-sync-v1.md)。

### 控制入口与幂等

以下路径的共同前缀为 `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks`，Session 和 Node 位于目标场馆。管理员持有同一有效会话，除针对拒绝的场景外，节点为 active。

```http
POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks
Idempotency-Key: training-task-create-01
Content-Type: application/json

{
  "session_id": "00000000-0000-4000-8000-000000000004",
  "edge_node_id": "00000000-0000-4000-8000-000000000003",
  "work_kind": "capture_demo"
}
```

首次调用返回 `201` 与原始创建收据。示例收据字段如下，`sequence` 是该节点分配命令的序号。

```json
{
  "task_id": "00000000-0000-4000-8000-000000000005",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "task_version": 1,
  "status": "assigned",
  "sequence": 41
}
```

| 向量 | 输入变体 | 期望 |
| --- | --- | --- |
| T2 | 同场馆 Coach 持 Session 读 grant 调用，或同管理员借用其他场馆 Node | 读 grant 调用 403，引用越域资源 404。匿名或节点凭据调用 401 |
| T3 | 无既有任务时，父 Session 为 `completed/cancelled`，或 Node 存在但未激活 | `409 state_conflict`。省略幂等键、未知工作类型或注入 `status` 均为 422 |
| T4 | 同操作者、同键、交换 JSON 属性顺序后重投。Session 已取消或 Node 已停用 | 201 原创建收据，仍只有一个任务、分配和命令。操作者失去当前控制权限即拒绝 |
| T5 | 创建键不变，改为同场馆另一有效 Node；或改为同场馆另一可见 Session | `409 idempotency_conflict`。换操作者时键单独隔离，同资源仍受唯一性保护 |
| T6 | 对该 Session 换新键再次创建，分别从 `assigned/accepted/completed/failed/cancelled` 起始 | 每种状态均返回 `409 task_exists`，全生命周期仍只有一个任务和一次分配 |

取消使用 `POST …/{task_id}/cancel`，首次用新操作键 `training-task-cancel-01`，请求为 `{"expected_task_version":1}`。

成功收据如下。

```json
{
  "task_id": "00000000-0000-4000-8000-000000000005",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "status": "cancelled",
  "task_version": 2,
  "sequence": 42,
  "cancelled_at": "2026-11-18T03:01:00Z",
  "reason": "operator_cancelled"
}
```

| 向量 | 输入变体 | 期望 |
| --- | --- | --- |
| T7 | 首次取消 v1、同键同参、换键重试 v1、换键按 v2 确认 | 均为 200，返回同一已取消结果，版本仍 2、序号仍 42、时间和原因不变 |
| T8 | 同取消键改期望版本或目标；新键且任务仍 v1 但期望 3；新键取消 `completed/failed` | 分别为 `409 idempotency_conflict`、`409 version_conflict`、`409 state_conflict`，均无新命令 |
| T9 | 写 Task 后、写下发或幂等收据前注入失败 | 任务、分配、收据、命令和节点序号整体回滚，同键合法重试可创建一次 |

### 上行事件与收据

这是已经接单的任务产生的序号 2。该分配的上行序号 1 为 `training_task.accepted`，下行节点序号 41 属于独立序列。

```json
{
  "schema_version": 1,
  "event_id": "00000000-0000-4000-8000-000000000011",
  "type": "capture.recorded",
  "tenant_id": "00000000-0000-4000-8000-000000000001",
  "site_id": "00000000-0000-4000-8000-000000000002",
  "edge_node_id": "00000000-0000-4000-8000-000000000003",
  "session_id": "00000000-0000-4000-8000-000000000004",
  "task_id": "00000000-0000-4000-8000-000000000005",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "task_version": 1,
  "sequence": 2,
  "occurred_at": "2026-11-18T03:00:00Z",
  "payload": {
    "capture_id": "00000000-0000-4000-8000-000000000012",
    "device_id": "00000000-0000-4000-8000-000000000007",
    "device_observed_at_raw": "unsynced-camera-001"
  }
}
```

正常情况下，仅产生一条采集事实，收据如下。

```json
{
  "event_id": "00000000-0000-4000-8000-000000000011",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "sequence": 2,
  "disposition": "applied"
}
```

- 重新排序 JSON 字段，或将同一 UTC 时刻表示为 `+00:00` 再发送，返回同一收据。把 `device_observed_at_raw` 改为另一个字符串，或以另一事件 ID 占用序号 2，返回 `409 event_conflict`。
- 先发送序号 2 且 Cloud 期望 1，返回 `409 sequence_gap` 与期望序号 1。补 1 后再投递 2。
- 添加重复 JSON 键、设置 `captured_at_utc: null`、上报 `ready` 或从上行发送下行命令均返回 422。节点授权范围不符返回 404，凭据无效返回 401。以上拒绝均不推进水位。
- 同归属 Device 已停用且无任务取消冲突时，按 Q7 返回 200，收据 `disposition=conflict_recorded` 且 `code=device_disabled`。有效冲突占用该上行序号，普通采集投影不增加。同时存在任务取消冲突时按 [W3.1](#w3-vectors) 处理。

### ACK、接单与实际执行

| 向量 | 轨迹 | 期望 |
| --- | --- | --- |
| A1 | 拉取分配命令 41。先模拟收到 HTTP 响应后、本地事务提交前崩溃，再模拟已提交持久接收后、ACK 发出前重启 | 第一次无游标推进，第二次可补发 `{"through":41}`。两次均未自动接单或开工。Cloud 处理 Command ACK 只更新交付水位 |
| A2 | 页 1 包含分配 41，目标水位 42。页 2 先后测试同分配的取消命令和其他分配的命令 | 有取消时不接单。未取消时追平后才可原子提交接单与 Outbox。提交后断网可执行，Cloud 未收到接单事件前仍为 `assigned` |
| S6.1–S6.3 | Cloud 初始分配 seq=41/v1，已收接单和采集。路径 A 先提交取消 seq=42/v2，再收 Edge 的 seq=3、v1 成功回报。路径 B 先提交该回报，再发起取消。另测分配和取消同轮下发且 Edge 未开工 | A 返回 200 `conflict_recorded` 并保留本地事实，Cloud 保持取消。B 成功回报获 `applied` 后，取消返回 409 且无 seq=42。未开工且取消已应用时，执行计数为零 |

### 下行样例及拒绝样例

已登记 Node 从 `after=40` 发起首次查询。该轮固定水位为 41。Edge 在同事务提交命令与本地水位后才可 ACK 41。后续 M4.2 业务接单及执行仍走 D3。

```json
{
  "commands": [{
    "schema_version": 1,
    "event_id": "00000000-0000-4000-8000-000000000010",
    "type": "training_task.assigned",
    "tenant_id": "00000000-0000-4000-8000-000000000001",
    "site_id": "00000000-0000-4000-8000-000000000002",
    "edge_node_id": "00000000-0000-4000-8000-000000000003",
    "session_id": "00000000-0000-4000-8000-000000000004",
    "task_id": "00000000-0000-4000-8000-000000000005",
    "assignment_id": "00000000-0000-4000-8000-000000000006",
    "task_version": 1,
    "sequence": 41,
    "occurred_at": "2026-11-18T02:59:00Z",
    "payload": {"work_kind": "capture_demo"}
  }],
  "through": 41,
  "next_after": 41
}
```

上行序号 2 先于 1 抵达且身份和资源关系合法，返回 HTTP 409。

```json
{
  "detail": {
    "code": "sequence_gap",
    "message": "上行序号存在缺口",
    "expected_sequence": 1
  }
}
```

同一上行采集 JSON 使用 `"captured_at_utc": null` 时是 HTTP 422，响应 `detail.code=validation_error`。将 `schema_version` 改为 2 或将 `type` 改成上文的下行类型，同样拒绝。若同归属设备已停用、无任务取消冲突且身份与因果合法，返回 200，收据字段仍与原采集对应。

```json
{
  "event_id": "00000000-0000-4000-8000-000000000011",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "sequence": 2,
  "disposition": "conflict_recorded",
  "code": "device_disabled"
}
```

### 人工批准后复用 M3 的样例

轻量上传意图示例使用 [仓库合成 MP4](../../services/cloud/tests/fixtures/synthetic-swim.mp4)，以已获授权的 Session 和指定目的发起。下例为 **既有 M3 User UploadIntentCreate** 请求，测试批准引用、资产标识和用途保存在测试取证记录，调用前核对绑定。未批准时不发此请求。

```json
{
  "expected_size_bytes": 894,
  "expected_sha256": "736313f902d2cb396ffff5500e65a7e48e570a4b7d2e2089846094dd99f7e57b",
  "media_type": "video/mp4",
  "capture_metadata": {
    "device_time_basis": "unknown",
    "video_timebase_kind": "unknown"
  }
}
```

### 凭据、安全停止与待发事实

| 向量 | 轨迹 | 期望 |
| --- | --- | --- |
| C1 | Cloud UTC 到期，或断网 35 天后仅得到通用 401 | 暂停同步并保留原事件。待接单任务继续等待，已接单任务仍可运行 |
| C2 | 管理员向同一节点发出经验证的仅撤钥操作 | 停用旧钥并保留离线执行，持续保存新事实。Cloud 拒绝旧钥的重放和收据读取 |
| C3 | 经验证的节点停用或本地安全停机通知，此时同时有已接单待跑任务及运行中任务 | 持久 `safety_hold`、零新开工、运行中任务安全收口，重启保持挂起与原 Outbox。无任务取消命令时不报告 `stopped_by_cancel` |
| C4 | 先更换同 Node 凭据，再按需验证 Registry 恢复和本地解挂。另用不同 Node 身份验证隔离 | 自然过期或仅撤钥可恢复原账本同步。停用路径在 Node 尚未激活时仍被拒绝，激活且新凭据生效后可对账，但有审计的本地解挂前不得开工。其他节点无法使用原队列 |

### W1 补投正反样例

已取消分配的合法停止回报使用上行信封 `task_version=2`、`sequence=3`、`payload={"outcome":"stopped_by_cancel"}`。Cloud 已提交同分配取消命令，Edge 已持久应用命令且实际安全停止。其合法收据为 HTTP 200：

```json
{
  "event_id": "00000000-0000-4000-8000-000000000013",
  "assignment_id": "00000000-0000-4000-8000-000000000006",
  "sequence": 3,
  "disposition": "conflict_recorded",
  "code": "task_cancelled"
}
```

反例是相同上行位置从未应用取消命令却声称 `stopped_by_cancel`，例如仍上报 `task_version=1`。其 HTTP 422 响应如下，保持期望序号不变，不写 Inbox/Receipt：

```json
{
  "detail": {
    "code": "validation_error",
    "message": "停止事实缺少匹配的取消命令版本"
  }
}
```

## Requirement / Scenario 验收矩阵

<a name="acceptance-matrix"></a>

R/S 编号对应 [本契约的需求与场景](#requirements)，原 8 项 Requirement 和 19 个 Scenario 保留。表内结果是签认后的行为验收预期，故障注入和数据库断言由后续 Change 验证。

| Requirement / Scenario | 契约走读与预期 | 后续运行证据 |
| --- | --- | --- |
| R1 / S1.1 | User token → 401；Node A 请求 Node B 的分配或另一租户/场馆 → 404。没有 ACK、数据外露或业务写入 | M4.3 角色/归属测试，M4.4 双节点隔离 |
| R1 / S1.2 | v2、反向事件或未知字段 → 显式拒绝，游标与 Inbox 不变 | M4.2 下行故障，M4.3 上行协议测试 |
| R2 / S2.1 | 合法 `capture.recorded` → 1 条事实；UploadSession、VideoAsset、Session 状态及 grant 写入为零 | M4.3 投影断言，M4.4 网络与数据库观测 |
| R2 / S2.2 | `finished` 依法完成任务视图；注入 `ready`、分析结果或已发布报告字段 → 拒绝且无副作用 | M4.3 负向载荷与权限回归 |
| R3 / S3.1 | 生产端写业务/Outbox、消费端写 Inbox/投影间注入失败 → 全回滚或同时可见。提交前无成功 ACK | M4.2 文件库崩溃恢复；M4.3 独立 PG 事务；M4.4 进程中断 |
| R3 / S3.2 | 提交后丢 ACK 再重发 → 同一逻辑收据，任务或事实计数仍为 1，命令 ACK 水位单调 | M4.2 重启；M4.3 并发投递；M4.4 真实丢响应 |
| R3 / S3.3 | 同 ID 改内容/位置，或同序号换 ID → 409。保留原投影、序号和接收收据 | M4.2 Inbox 测试，M4.3 事件唯一约束 |
| R4 / S4.1 | 先收到 3、当前期望 2 → 保持进度 1 并报告缺口。补 2 后按序重放 3 | M4.2 乱序下行，M4.3 上行序号，M4.4 双向重放 |
| R4 / S4.2 | 断开时 Cloud 取消一个任务，Edge 有未确认事实。重连走拉取、ACK、重投、对账；权威视图和收据一致 | M4.4 两个服务与独立持久卷 |
| R4 / S4.3 | 本地游标丢失或早于历史 → recovery_required，保持待发项，禁止用云端 ACK 推断本地已执行 | M4.2 卷恢复，M4.3 游标测试，M4.4 缺口演练 |
| R5 / S5.1 | 已业务接单掉线并重启 → 同一执行身份恢复或显式挂起，重试预算耗尽仍保留原事件。只持久接收或 ACK 时还不能开工 | M4.2 可重复启动和断网持久化，M4.4 掉线重启 |
| R5 / S5.2 | 422/404/409 完整性冲突暂停问题流，待人工核对，其他分配继续。无终态收据不销账 | M4.2 重试调度，M4.4 两分配互不阻塞 |
| R6 / S6.1 | 取消先提交 → 晚成功只产生持久冲突收据，任务仍取消，本地事实仍可查。父 Session 取消分支同验 | M4.3 PG 并发、父取消及与 Edge 媒体操作的锁序回归；M4.4 网络分区 |
| R6 / S6.2 | 完成先提交 → 后续任务取消冲突，无取消命令。父 Session 的合法取消保留已完成任务历史 | M4.3 PG 并发与旧 Session 行为回归，M4.4 反向竞态 |
| R6 / S6.3 | 分配与取消同轮补拉，或已接单尚未执行时收到取消 → 新执行计数为零 | M4.2 调度门槛，M4.4 重连控制先行 |
| R7 / S7.1 | 服务端截止和断网 35 天 → 401，旧收据不可取。没有独立安全停止指令时，本机继续已接单工作，待发队列保留 | M4.3 UTC 截止与事务侧效应，M4.4 可控时钟 |
| R7 / S7.2 | 同 Node 受控再签发并满足现行认证 → 原信封重投、继续游标。旧凭据和不同节点均拒绝，停用路径的本地开工仍需显式解挂 | M4.3 身份矩阵，M4.4 同卷恢复 |
| R8 / S8.1 | 事件已确认，无上传授权时无传输；M3 `completing` 时无 `ready`；Edge 无自动删除 | M4.2 本地文件规则，M4.3/M4.4 既有 RustFS 隔离媒体回归 |
| R8 / S8.2 | 保留原身份、Session、上传和媒体读权操作；历史 Session 无须回填任务 | M4.3 SQLite/PG 兼容测试，M4.4 原 CI 回归 |

## 定向验收矩阵

<a name="targeted-matrix"></a>

| 向量 | 行为验收预期 | 后续运行证据 |
| --- | --- | --- |
| T1 | 当前同 Tenant 的 Owner/Admin 向可见 Site 内的 active Node 分配 `planned/recording` Session，201 且一个任务、一个分配、一条命令 | M4.3 API 与数据库 |
| T2 | 无效会话/节点凭据为 401。同场馆 Coach/Athlete（含读 grant）为 403。非成员、不可见 Site 或越范围资源为 404。创建、取消均无副作用 | M4.3 角色、跨 Tenant/Site、同租户跨场馆 |
| T3 | 无现存任务时，`completed/cancelled` Session、非 active Node → `409 state_conflict`。缺键、非法键、无效/越权字段 → 422 | M4.3 输入与前置状态 |
| T4 | 同当前授权主体同键同参创建重放 201 原收据，Session 取消或 Node 停用后仍可按当前权限回放。权限被撤则先拒绝 | M4.3 幂等和实时授权 |
| T5 | 同权限作用域同键异参、包括改 Session 或 Node → `409 idempotency_conflict`。不同操作人或 operation 的键独立，资源约束仍生效 | M4.3 摘要及作用域 |
| T6 | 既有任务任一状态含全部终态，使用新键创建均获 `409 task_exists`，单任务/单分配不变 | M4.3 DB 唯一约束和并发 |
| T7 | `assigned/accepted` 初次合法取消成功。重复取消可用 v1 或 v2 得到原取消结果，原因/时间/版本及取消指令数不变 | M4.3 API、命令日志 |
| T8 | 同键异参取消 → 幂等冲突。期望版本错误 → 版本冲突。已完成/失败的任务取消 → 状态冲突 | M4.3 负向控制 |
| T9 | 注入创建/指派、命令及请求收据提交前失败，全部回滚且节点流无缺口 | M4.3 PG 事务 |
| A1 | 收包崩溃前无 ACK，持久接收后重启可补 ACK。Command ACK 仅推进交付水位 | M4.2 重启，M4.3 ACK 隔离 |
| A2 | 持久接收阶段不可执行。追平且未取消时原子业务接单，实际开工单独记录，Cloud 收到接单回报前仍为 assigned | M4.2 调度，M4.4 双端 |
| C1 | 自然过期、一般掉线或未知 401 暂停同步，已接单任务可继续，待接单项等待，保存事实 | M4.2 本地运行，M4.3 UTC，M4.4 长离线 |
| C2 | 经验证的仅撤钥停止使用该钥，保存新旧待发事实，已接单任务继续 | M4.2 凭据装载，M4.3 撤权 |
| C3 | 已验证停用或有权本地停机持久设置 `safety_hold`，禁止新开工，运行中安全收口并保留检查点。重启不得解除 | M4.2 安全停止和持久化，M4.4 真双端 |
| C4 | 同 Node 再签发及 Registry 激活可恢复对账。停用后的本地开工多一道经审计解挂，其他 Node 不能继承事实 | M4.2 解挂，M4.3 权限，M4.4 恢复 |
| L1 | 同 Node/Session 的 Edge 意图、查询和中止与 M3 终结/M4.3 父取消并发，既有结果合法，无死锁/超时及残留 | M4.3 PG17 双连接 |
| L2 | 同键/异键创建并发，及分配与父取消竞态，一个任务、一个分配，节点序号无空洞 | M4.3 PG17 双连接 |
| L3 | 先取消与先完成顺序均测试，终态及命令唯一，M3 的既有 `completing/ready` 规则继续适用 | M4.3 PG17 真实 API/worker |
| L4 | 撤钥、停用或等待锁跨过到期点与 Inbox 写入/重放竞态，401 路径不写、不泄露历史，先合法提交结果可审计 | M4.3 PG17 双连接与可控 UTC |

[ADR 0004](../decisions/0004-cloud-edge-sync-v1.md) · [协议样例](#examples)


## W1 取消后的离线补投验收

<a name="w1-vectors"></a>

共同起点：Assignment A 绑定已认证 Node N，初始命令版本 1。Edge 已本地持久接单但上报尚未送达，Cloud 先提交该 Task 的合法取消（v2）；单独任务取消和父 Session 联动各运行一遍。上行序号属于 A，与下行游标独立。表中所有成功消费均在同一事务写 Inbox、收据与最小审计，Task 投影保持 `cancelled`。同 ID 同内容重放返回原逻辑收据，不再消费。所有拒绝都保留 Edge 待发项，Cloud 无新增 Inbox、成功收据、序号消费或投影变更。

| 编号 | Edge 原始事实及顺序 | Cloud 终态及序号 | Inbox、收据与重放 |
| --- | --- | --- | --- |
| W1.1 | 本地已接单，`accepted@1/v1` 仍待发，Cloud 先取消 | `cancelled`，上行仍期望 1 | 尚未上报，无 Inbox/收据，重连前保留原信封 |
| W1.2 | 补投 `accepted@1/v1` | `cancelled`，消费 1，期望 2 | 200 `conflict_recorded/task_cancelled`，记 A 的接单因果，重放同收据 |
| W1.3 | 补投 `capture.recorded@2/v1`，使用已消费的 1 作为前置 | `cancelled`，消费 2，期望 3；正常采集投影和上传不变 | 200 `conflict_recorded/task_cancelled`，记来源和采集 ID，重放同收据 |
| W1.4 | 接 W1.2/W1.3，补投收到并应用取消前已完成/失败的 `finished@3/v1`，分别测试两种 outcome | `cancelled`，消费 3，期望 4；不写任务完成或失败投影 | 200 `conflict_recorded/task_cancelled`，审计原 `completed` 或 `failed`，重放同收据 |
| W1.5 | W1.4 的独立分支：接 W1.2/W1.3，实际应用取消 v2 并安全停止，补投 `finished@3/v2`，outcome 为 `stopped_by_cancel`。丢失 Command ACK 时再测一次 | `cancelled`，消费 3，期望 4 | 200 `conflict_recorded/task_cancelled`，保存停止 outcome 及命令关联，重放同收据；无对应取消命令/版本时为 422 |
| W1.6 | W1.4 分支实际完成后收到取消：保留原 `completed@3/v1`，不生成另一个 stop；另注入伪造的第二个 `finished@4/v2` | `cancelled`，原 3 可确认；伪造的 4 不消费 | 3 重放原 200 冲突收据；4 为 422 `validation_error`，无新收据或审计事实 |
| W1.7 | 分别重投原 1–3，改已消费的 ID 内容，以新 ID 占用同号，先发 2，使用失效凭据或其他 Node，使用与 Task/Session 不相符的 Assignment；另测同 Node 的另一个合法 Assignment 无自身接单 | `cancelled`；重放不再次推进，其余不消费 | 正确重放返回原 200 收据；异参/同号换 ID 为 409 `event_conflict`，缺序为 409 `sequence_gap`，失效身份 401，跨 Node/不相符归属 404。同 Node 合法 Assignment 若收到其连续首号采集但没有自身接单，返回 422 `validation_error`，不能借 A 的因果 |

M4.2 验收执行事实与 Outbox 生成，M4.3 验收 Inbox、收据、因果及无投影副作用，M4.4 验收完整离线重连轨迹和稳定重放。

## W3 任务取消与设备停用组合验收

<a name="w3-vectors"></a>

| 编号 | 初始事实和操作 | 必须观察的结果 |
| --- | --- | --- |
| W3.1 | Task 已合法取消。Assignment A 已消费自身 `accepted@1`，当前期望序号 2。用有效 Node 身份补投符合因果的 `capture.recorded@2/v1`，来源 Device 同归属且已停用。保持身份和归属有效，以同 Event ID、同信封重放，另在设备状态改变后再重放一次。 | 首投返回 HTTP 200、`disposition=conflict_recorded`、`code=task_cancelled`，收据含原事件、分配和序号。单事务仅新增一条 Inbox 及对应收据和冲突审计，内部 `conflict_reasons` 严格等于有序数组 `["task_cancelled","device_disabled"]`。序号从期望 2 推进到 3，Task 保持 `cancelled`，无正常采集投影、上传意图或 `VideoAsset.ready`。两次重放均返回原逻辑收据，期望序号仍为 3，原审计数组、Inbox 及正常业务投影均无新增或重写。 |

M4.3 验收单事务消费、双原因审计及收据稳定性。M4.4 在离线补投链路中复测组合条件。

## S1 收据匹配验收

<a name="s1-vectors"></a>

| 编号 | 收据及请求绑定 | Edge Outbox 预期 |
| --- | --- | --- |
| S1-R1 | Tenant/Site/Node 与认证请求上下文和本地信封一致，ID、序号与合法处置均匹配 | 仅确认对应待发项；同收据再到达不二次变更 |
| S1-R2 | 同绑定，`event_id` 不匹配 | 保留原项待发并记录诊断，不确认其他项 |
| S1-R3 | 同绑定，`assignment_id` 不匹配，再独立测试 `sequence` 不匹配 | 两种不匹配均不得确认 |
| S1-R4 | ID、序号相同，但当前认证 Node 与请求或本地信封的 Tenant/Site/Node 绑定不符 | 保留待发项，拒绝跨节点确认 |

S1 定向编号独立于原 Scenario。M4.2 验收本地匹配及幂等，M4.3 验收 Cloud 认证与最小收据投影，M4.4 验收真实往返。

## Q5 B 人工批准媒体联调矩阵

<a name="media-matrix"></a>

M1–M7 均归 M4.4 在隔离 RustFS 上用合成 MP4 和测试身份运行。记录批准动作及其 Session、资产、目的、当前身份绑定。该编号与原 R/S/T/A/C/L 分开。

| 向量 | 测试与预期 | 运行证据 |
| --- | --- | --- |
| M1 | 未批准时上报采集与任务终态。M4 可以回 ACK，UploadSession 创建数、对象写入和原片上传请求均为零 | Cloud/Edge 投影、数据库行数、传输观测 |
| M2 | 人工对该 Session 的指定合成资产、目的和当前授权明确确认。由已有 M3 权限的发起身份创建意图，回链 Asset 与 UploadSession。同键重试只保留一对资源 | 测试批准记录、M3 身份和实际 API/资源 ID |
| M3 | 分片中断及进程重启。保留批准、原意图、已确认分片与幂等键，原发起身份通过 M3 查询/补签和续传 | 同一 upload ID、分片回执、重启证据 |
| M4 | 分片成功和 `completing` 均无 `ready`。M3 对实际对象版本的 SHA-256、大小和媒体有效性验证成功，才成对提交 completed/ready。对错误摘要、大小、媒体格式或对象版本变更单独注入失败并验证不得 ready | worker 前后状态、对象版本和脱敏校验结果 |
| M5 | 撤销或过期后，旧凭据和同步收据不能创建意图、补签、确认或完成。验证提交前丧失授权不得 ready，已签 URL 只按 M3 自身 TTL 生效 | 旧身份拒绝、到期边界、验证回执 |
| M6 | 最终 `ready` 后 Edge 原件仍在且 SHA-256 一致。Cloud 成功回执及 M4 ACK 均不触发自动删除 | 本地存在性、SHA-256、传输与删除观测 |
| M7 | 人工批准专用多分片 MP4。确认第一片后中断并重启上传进程，沿原批准/发起人/UploadSession 对账，只补传缺片，再由 M3 终结 | [M7 取证链路及负向用例](#m7-multipart-resume) |

### M7 多分片输入与取证

<a name="m7-multipart-resume"></a>

894 字节请求样例只用于轻量 API 示例。M7 使用既有有效合成 MP4 加一个合法 ISO-BMFF `free` box，可复用 [现有合成素材生成方式](../../services/cloud/tests/test_media_transfer_storage.py)。以下步骤在隔离环境从仓库根目录执行。生成文件位于临时目录。M4.4 验收固定使用 **ffprobe 6.1.1**，记录其实际版本、媒体格式、视频流、尺寸、时长、字节数和 SHA-256。

```bash
set -e
fixture_dir=$(mktemp -d)
python3 - "$fixture_dir/resume-20mib.mp4" <<'PYTHON'
from hashlib import sha256
from pathlib import Path
import struct
import sys

seed = Path("services/cloud/tests/fixtures/synthetic-swim.mp4").read_bytes()
size = 20 * 1024**2
padding = size - len(seed)
assert padding >= 8
data = seed + struct.pack(">I4s", padding, b"free") + bytes(padding - 8)
Path(sys.argv[1]).write_bytes(data)
print(len(data), sha256(data).hexdigest())
PYTHON
ffprobe -version | head -n 1 | grep -F 'ffprobe version 6.1.1'
ffprobe -v error -show_entries 'format=format_name,duration,size:stream=codec_type,codec_name,width,height' -of json "$fixture_dir/resume-20mib.mp4"
```

当前种子生成 **20,971,520 字节**，SHA-256 为 `ca553583858bab2781f3e8f09cab40c9069a6a4bd93b8d6df540919c92382fb0`。按 M3 当前 16 MiB 布局形成两片，第一片 **16,777,216 字节**，第二片 **4,194,304 字节**。媒体须可探测为有效 MP4。批准前对照实际生成记录和预期值，保留批准时的指纹。

| 阶段 | M4.4 操作及必须取证 |
| --- | --- |
| 人工批准 | 为具体 Tenant/Site/Session、该文件及用途建立唯一测试批准引用，以当前有效且有 M3 权限的发起身份明确创建一个意图。持久记录批准引用、原发起身份标识、`asset_id`、`upload_session_id`、`Idempotency-Key`、长度和 SHA-256。同步事件照常上报，零隐式上传意图。 |
| 首片确认 | 按服务端返回的冻结布局确认 2 个实际 part。签名并 PUT part 1，调用 M3 确认接口，再经 ListParts 读取 part 1 已确认的编号、大小及 ETag。网络观测表明未上传 part 2。 |
| 中断重启 | 在 ListParts 已见首片且 part 2 尚未上传时终止测试上传进程并重启 Edge，保留原片、持久卷、批准记录、分片响应、UploadSession 和意图键。重启从原上下文恢复，同一发起主体、批准、upload ID 和 SHA-256；不产生第二个 UploadSession。 |
| 对账续传 | 原发起者用现有 M3 ListParts 对账本地记录和首片回执，只为缺失的 part 2 签名、上传及确认。用网络观测断言重启后 part 1 新 PUT 为 0、补传数为 1。同一上传在对账、签名或恢复失败时保留原意图和证据，不静默新建。 |
| 校验保留 | 用两个真实 ETag 调用现有 Complete；在 worker 验证前只允许 `completing`，且资产未 ready。由 M3 Worker 验证精确对象版本、完整 SHA-256、大小、媒体有效性及现有授权，再成对提交 `completed/ready`。记录分片数、重启次数、补传数、对象版本、校验结果及本地原件存在与哈希。 |

负向验收独立保留证据：

- 未获批准即试图启动上传时，由隔离编排或上传入口拒绝该动作，零 M3 意图请求与零新增 UploadSession。此门槛属于 M4.4 明确批准编排；现有 M3 API 授权行为不变。
- 批准资产与本地待传文件的 SHA-256 不符时拒绝进入 Complete。另将受控错字节传至仍以原正确 SHA-256 声明的测试意图，验证 M3 的最终校验失败并无 `ready`。
- 首片确认、第二片缺失时，只补传第二片。批准记录缺失时暂停并进入人工恢复，保留原意图与待传事实，通过原批准与现行身份核验后才恢复；权限不扩大。
- 原发起人会话或节点凭据过期、撤销后，按 M3 规则拒绝新的分片 URL、确认和完成，旧签名仅按现有 TTL。挂起时仍保留本地原件。
- 独立注入上传完成但 SHA-256 不符、媒体探测失败的两种场景，断言均无 `ready`。正常验证成功也不触发自动删除本地原件。

M7 是 M4.4 的运行验收要求。文档阶段的夹具生成和媒体探测证据不替代双端传输、分片回执或 worker 实证。
