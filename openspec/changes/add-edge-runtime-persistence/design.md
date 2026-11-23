# Design

## Context

见 [Proposal](proposal.md) 的问题与范围；行为边界以 [Edge Runtime Persistence Spec Delta](specs/edge-runtime-persistence/spec.md) 为准。当前仓库的 Edge Runtime 是 README scaffold。Cloud 已有独立 Registry、身份、Session、媒体授权和 M3 上传实现；Cloud 任务/同步服务端尚未实现。M4.1 要求持久 Inbox/cursor、接单/事实 Outbox 原子提交、按 Assignment 序号、精确收据匹配、离线继续及显式 `safety_hold`。

设计约束：Edge 不共享 Cloud ORM/数据库；一个 Edge Runtime 是单进程模块化应用；本地业务状态由数据库持有，大媒体文件在数据库外；数据库和文件系统没有共同原子提交；M4.2 使用 CPU/本地持久卷与 Mock 对端，生产部署配置仍未定。启动必须先取得数据目录独占进程锁、核对不可变 RuntimeIdentity，再开放账本访问；云端收发另需当前 CloudAdapter 认证作用域与本地绑定一致。

## Goals / Non-Goals

**Goals:**

- 建立清晰的本地持久化模块边界，保证 Inbox/cursor、业务事实/Outbox 和逐 Assignment 连续序号具备单事务原子性。
- 将本地数据目录不可变绑定到一个 Runtime/Node/Tenant/Site 身份，并通过 OS 级排他锁禁止多进程同时消费命令、发送 Outbox 或升级 Schema。
- 对下行分页及每条命令按 M4.1 契约先验证后持久化；持久恢复固定轮次水位并禁止游标越过非法命令。
- 使用可重启进程、持久测试目录、可注入 Clock/Network、MockCloudAdapter 和确定性 Worker 验证提交/重放/恢复行为。
- 把 SQLite 与文件系统分开持久化，并用 `LocalFileRecord` 状态机、校验和启动对账修复非原子窗口。
- 将普通离线、凭据失效、取消和已验证安全停止作为不同的本地状态来源；不通过重启清除挂起。
- 保留 M4.3 Cloud Sync 和 M4.4 双进程联调及真实媒体上传的独立责任。

**Non-Goals:**

- Cloud 任务/取消 API、Cloud Inbox/投影/迁移、云端事务锁序和 PostgreSQL 竞态验收。
- 真实 HTTP 同步服务端、摄像头、完整 Worker 生命周期、AI/姿态算法、M3 上传或 Venue Console。
- 场馆生产数据库/Redis、存储容量/保留策略、生产备份服务或生产远程停机通知。

## Decisions

### A. 总体结构与依赖方向

Edge 内部先作为单个可运行模块化应用；持久化和适配器不由每个业务模块各自连接 SQLite。

```text
Local API / Runtime Coordinator
             |
             v
Command Service -- Task/Assignment Service -- Outbox Dispatcher
        |                    |                       |
        +---------- Local Unit of Work ---------------+
                             |
              +--------------+--------------+
              |                             |
       SQLite Repository               File Store
              |                     staging -> objects
              +-------------+---------------+
                            |
                Recovery / Safety Hold

Adapters: MockCloudAdapter | Clock | Network | Deterministic Worker
```

依赖单向指向 Edge domain interfaces：Command/Task/Outbox/Recovery service 通过 Unit of Work 和 File Store 接口读写 Edge 自己的数据；CloudAdapter、Clock、Network 和 Worker 为运行适配器。业务模块不得导入 `services/cloud` 或对 Cloud DB 建 Session。M4.2 交付 `CloudAdapter` interface 和 deterministic MockCloudAdapter；不交付真实 Cloud HTTP 适配器或远端停机通道。

### B. 数据模型与索引候选

这是逻辑模型，实施时由 Edge 自己的版本化 Schema 确定确切列名/类型。

| 记录 | 主键/约束候选 | 关键职责 |
| --- | --- | --- |
| `LocalRuntimeIdentity` | 单例主键；唯一 `runtime_instance_id`；不可变 `(tenant_id,site_id,node_id)`；`initialized_at`、绑定时 `schema_version`、`identity_state=bound` | 数据目录首次显式初始化时创建；不存 Credential ID/Secret；实际 Schema 版本仍以 Alembic revision 为准；身份不匹配状态不改写原绑定 |
| `LocalCommandInbox` | `event_id` PK；唯一 `(node_id, command_sequence)`；索引 `(assignment_id, command_sequence)` | 只保存通过 M4.1 严格验证并在本地事务应用的规范命令、SHA-256 fingerprint、版本、scope 和结果；异参不得替换原值 |
| `CommandCursor` | `node_id` PK；`last_applied_sequence >= 0`；活动轮次的 `round_through` 可空但一旦开启即持久固定 | 表示本地已原子应用的最高连续命令序号；不能用 Cloud ACK 推断本地状态；未追平固定上界前不接受新的上界 |
| `CommandAckState` | `node_id` PK；`desired_through`、最近尝试/响应水位及时间 | ACK 投递元数据与 Inbox 应用状态分离；目标由已提交 cursor 派生，失败/丢响应可重发，不改变命令、接单或执行状态 |
| `LocalTrainingTask` | Cloud `task_id` PK；保存外部 Tenant/Site/Session IDs | 单独保存 `cloud_task_status`（`assigned`、`accepted`、`completed`、`failed`、`cancelled`）、`cloud_task_version` 与 `cloud_projection_revision`；前者是 Cloud 当前任务投影，后两者分别表示命令版本和投影版本。尚无 Reconcile 投影时 revision 为空，首次有效正整数 revision 初始化它；不冒充 Edge Assignment phase |
| `LocalAssignment` | `assignment_id` PK；v1 `task_id` 唯一；`next_event_sequence` 单调 | Edge phase、取消门、执行 run ID/attempt/checkpoint 与 `recovery_state` 分开；v1 的单 Task/单 Assignment/单 Node 约束继承 M4.1 Q1 |
| `LocalCaptureFact` | `capture_id` PK；唯一 `(tenant_id,site_id,node_id,assignment_id,capture_id)` | 保存 M4.1 白名单的来源 Device、已知 UTC/原始设备时间、有限 metadata 和可空 file_id |
| `LocalEventOutbox` | `event_id` PK；唯一 `(assignment_id,sequence)`；索引 `(delivery_state,next_attempt_at)` | 保存不可变 canonical envelope/fingerprint；传输状态、尝试预算与匹配收据是可变的投递元数据 |
| `LocalSafetyHold` | `hold_id` PK；scope 固定为 Node；同一原因有独立记录；active 状态索引 | 保存每个已验证 Node 停用/可信本地停机原因、来源引用、时间及显式解挂的操作者/原因/时间；解掉一个原因不清除其他原因 |
| `LocalFileRecord` | `file_id` PK；staging/final 相对路径唯一；索引 `(file_state,created_at)` | 保存期望/观测 size、SHA-256、独立本地文件状态、capture/assignment/task 关系、设备元数据阶段和验证时间；本地 `available` 不代表 Cloud Asset `ready` |
| `LocalRecoveryRecord` | `recovery_id` PK；scope type/ID/state 与来源记录索引 | 以 Assignment 为默认局部 scope 记录缺口、冲突、文件异常和人工处理；持久化有界脱敏证据，不把 Assignment 问题升级成 Node 停用 |

序号由 `LocalAssignment` 单独分配而非全局序列；插入 Outbox、推进 next sequence 和提交业务事实在同一事务内。`event_id` 在该事务首次产生并持久保存。Outbox envelope 列在应用层不可更新；仅发送状态、尝试、收据和诊断字段可变。Cloud IDs 都是外部标识符，不设跨数据库外键。

持久事实包括 RuntimeIdentity、所有合法 Inbox/envelope、cursor/活动 `round_through`、分离的 ACK 投递元数据、已接单与执行检查点、CaptureFact、Outbox 原件、文件关联、每个 active Node SafetyHold 和未结 RecoveryRecord。无效或未验证的原始响应不写入业务 Inbox；只写有界错误类别、页/序号、请求关联和内容指纹。连接状态、进程对象、HTTP 客户端和可由账本重建的缓存不持久化。Outbox 至少保留到精确匹配收据，M4.2 不提出清理已确认事实或删除原始文件的策略。

### B.1 RuntimeIdentity 与目录独占

显式初始化仅能对空白数据目录创建一个 `LocalRuntimeIdentity`：`runtime_instance_id`（随机 UUID）、`tenant_id`、`site_id`、`node_id`、`initialized_at`、创建时 Schema `schema_version` 和 `identity_state=bound`。Binding 三元组、`runtime_instance_id` 和初始化时 `schema_version` 在整个目录生命周期不可更新或删除；该版本仅记载初始绑定时版本，当前 Schema 以独立 Alembic revision 为准。常规迁移不重新初始化、不变更身份。Credential ID、token、密钥或可恢复的 Secret 绝不入库。复制来的非空账本缺少身份行、出现多行或身份格式不支持时 fail closed，不能推断或自动补绑。

每次启动和显式 init/upgrade 前先解析并固定数据根目录，取得同一根目录中的 OS advisory exclusive lock。隔离 Unix profile 推荐用 `fcntl.flock(LOCK_EX|LOCK_NB)` 持有打开文件描述符直到进程退出；锁描述符设为不可继承，子进程不得继承数据目录锁。该锁覆盖 Runtime、命令消费者、Outbox Dispatcher、初始化和 Schema 升级。PID/时间只用于诊断，不是锁。内核在进程退出时释放锁，锁文件可留存但不能代表锁仍被持有。不能确认文件锁可靠或无法取得锁时，拒绝提供服务；不得退化成 `asyncio.Lock`、PID 文本检测或让第二 Dispatcher 启动。部署在网络文件系统的语义不由隔离 profile 外推。

启动次序是：取得 OS 锁 → 校验数据目录/活动 Schema → 仅读取 RuntimeIdentity 并比对显式配置的 Tenant/Site/Node → 完成安全恢复扫描 → 打开业务读写服务。任一作用域不匹配时设置运行态 `identity_mismatch`、readiness=false，不创建任务/RecoveryRecord 来改写原身份、不查询 Outbox/Assignment、不接单/执行/发送、不清库。正确配置恢复后仍用原账本。Credential 轮换不属于身份键：当本机配置三元组匹配但无公网或暂时无有效 CloudAdapter 认证时，本地 Runtime 可以按 M4.1 离线规则恢复；云端命令拉取和 Outbox 发送暂停。任何云端收发前须验证当前认证绑定的 Tenant/Site/Node 与本地身份完全一致，否则关闭同步门且不读取待发信封。

### B.2 状态机与作用域

状态不共用一个 `status` 字段：

| 对象/状态 | 合法状态/转移 | 转移触发与阻断规则 |
| --- | --- | --- |
| Runtime readiness | `uninitialized → initializing → recovering → ready`；另有 `not_ready`、`identity_mismatch`、全局 `recovery_required` | 空目录只由显式 init 进入；Schema/身份不符、锁失败、关键扫描未完成均不 ready。Node SafetyHold 与局部 Assignment 故障是并行阻断维度，不必关闭本地 health API |
| Command Inbox | 网络输入的 `received → validated` 仅为内存态；只有同事务已应用行才持久为 `applied`；同内容重放返回已有结果；异内容、序号冲突、非法/不支持版本进入流诊断；无法证明可安全兼容的流持久为 `recovery_required` | 未校验不能插入 Inbox；每条已应用命令与其本地控制效果和 Cursor 同事务。ACK 尝试由 `CommandAckState` 单独记账，不改变 Inbox、Task 或 Worker 状态。阻断保留当前 `round_through`，只可在兼容版本明确支持且验证通过后，或经审计的人工恢复后解除 |
| CommandCursor | `last_applied_sequence` 只按 `n → n+1`；活动 `round_through` 首页检查后持久固定，追平到该值后才能清空并开启下一轮 | 分页响应的 `next_after` 只声明该页尾部位置，不是持久进度。非空页必须等于本页最后命令序号，空页保持请求 `after` 不动；重启一律从 `last_applied_sequence` 续取。超过期待序号的命令不应用、不 ACK；ACK target 等于已提交连续 cursor，Cloud 返回 ACK 水位仅作观察 |
| LocalTrainingTask | 持久 Cloud 快照状态为 `assigned`、`accepted`、`completed`、`failed`、`cancelled`；分别保存 `cloud_task_version` 与 `cloud_projection_revision` | 仅按 Reconcile 的递增 `projection_revision` 应用快照；`task_version` 独立按命令版本规则校验，不能代替投影排序。快照更新不改写 LocalAssignment phase、CaptureFact 或 Outbox；Cloud 合法终态优先，迟到事实只按 M4.1 上报 |
| LocalAssignment | Edge phase `pending_acceptance → accepted → running → completed/failed`；实际安全停机后可 `running → stopped_by_cancel`；恢复维度 `normal ↔ recovery_required` 独立 | accepted 与 accepted Outbox 原子提交；实际开工前重新验证 accepted、未取消、无 Node hold、无局部 recovery block 并持久取得执行资格；终态最多一份；取消提交在先则不发放开工资格 |
| LocalFileRecord | `staging_intent → staged_verified → published → available`；各正向状态均有独立数据库提交点；任一不确定/损坏态转 `recovery_required` 或只读 `quarantined` | rename 与父目录 fsync 成功后，单独提交 `file_state=published`；后续最终业务事务才原子写 CaptureFact/Outbox/Assignment sequence 并把 FileRecord 改为 `available`。只有 `available` 可被 Edge 引用；不等于 Cloud `VideoAsset.ready` |
| SafetyHold / Recovery | Node Hold 每个原因独立 `active → released`；Assignment RecoveryRecord `open → resolved` | 任一 active Node Hold 阻止该 Node 所有新开工；任一 open assignment block 只阻止该 Assignment。解除一个原因不清除其余原因；重启不做隐式解挂 |

### B.3 Cloud Task 投影版本

`LocalTrainingTask` 持久保存 `cloud_task_status`、`cloud_task_version`、`cloud_projection_revision` 三个独立值。状态枚举严格沿用 M4.1：`assigned`、`accepted`、`completed`、`failed`、`cancelled`。尚无 Reconcile 投影时 `cloud_projection_revision` 为空，首次有效正整数 revision 初始化 Cloud 投影；此后仅在 `projection_revision > cloud_projection_revision` 时应用。比较的 Cloud 投影字段为 `task_id/status/task_version`，不包括独立变化的节点水位；相同 revision 且这些字段完全相同是幂等重放，较旧 revision 连同其状态和 task_version 一起忽略；相同 revision 但状态或 task_version 不同属于投影冲突，保留旧快照并写 Task 作用域的 `recovery_required` 诊断。`task_version` 是命令版本，按 M4.1 的非布尔安全整数/正整数版本范围独立验证，并在应用较新投影时不得回退；允许 projection_revision 前进而 task_version 不变，禁止用任一字段代替另一字段排序或验证。更新 Cloud 快照不直接改写 Edge `LocalAssignment` phase、执行检查点、CaptureFact 或 Outbox；Assignment 控制效果仍由对应持久命令和本地事务落实。

“持久 Inbox 已 applied”“命令 ACK 已发送/已知被 Cloud 确认”“Assignment accepted”“Worker running”四种事实有分离字段/实体和提交时点。Command ACK 不创建 accepted 状态；任务状态不可从 ACK 水位反推。

### C. 本地事务边界

| 操作 | 同事务写入 | 提交之后 |
| --- | --- | --- |
| 接收命令 | Inbox 原 envelope + 命令本地效果/Task 状态 + `CommandCursor` | 仅发送最新连续 `through` ACK；丢响应可从持久 cursor 重发 |
| 业务接单 | 本地 Assignment/Task 接单状态 + sequence=1 的 `training_task.accepted` Outbox | 允许离线调度；事务失败时不接单/不执行 |
| 文件进入 `published` | 已发布 final 路径对应的 `LocalFileRecord=file_state=published`、`published_at` 和已验证文件元数据 | 此独立 DB 提交不产生 CaptureFact、Outbox 或 Assignment sequence；对象仍不可供业务引用 |
| 采集事实最终化 | LocalCaptureFact + `LocalFileRecord=available` + Outbox envelope + Assignment sequence | 同一最终事务原子提交；提交后才允许本地引用，上传媒体仍为独立授权流程 |
| 真实任务终态 | LocalTrainingTask/Assignment 终态 + 原 outcome 的 Outbox envelope + sequence | 终态只写一次；迟到事实不删除或改写 Cloud cancelled 的结果 |
| 收据确认 | 精确 request scope 与 ID/sequence/disposition 通过后的投递状态、原收据 | 单独更新 delivery metadata，不修改 event envelope |
| 挂起/解挂 | `LocalSafetyHold` 审计记录 + Assignment 调度门槛 | hold 持久生效；重启不清除 |

SQLite 写事务串行完成。所有会读—比较—写的 Cursor/序号/状态竞争使用独立 SQLite connection 和 `BEGIN IMMEDIATE`（或通过等价双连接屏障证明的 SQLite 写序列化策略）；只依赖进程内互斥锁不构成正确性。唯一约束及带期望旧值的条件更新是第二层防线，必须检查受影响行数。CommandCursor 的比较/推进、Assignment sequence 分配/Outbox 插入/业务事实、重复事实幂等键、cancel gate/执行资格各自处于同一 DB 写事务。不在事务内做网络、Worker、文件写入或 fsync。`SQLITE_BUSY` 只可作有界整事务重试；已提交后超时重试按唯一键返回原结果，不重复效果。网络请求失败不会回滚已提交账本；提交后响应丢失时只重发已存水位/原事件。Cloud response 仅在发请求时认证 scope、本地 envelope 和原 request correlation 全匹配时确认对应 Outbox。

`BEGIN IMMEDIATE` 避免两个独立连接同时拿旧序号后再升级写锁；每 Assignment `next_event_sequence` 使用唯一 `(assignment_id, sequence)` 约束及 `UPDATE ... WHERE next_event_sequence = expected` 条件更新，只有 rowcount=1 的事务可追加该序号。并发重复事实用 `(tenant_id,site_id,node_id,assignment_id,capture_id)` 唯一键竞争，失败方回滚后重新读出获胜事务的原结果。任务开工与取消先后由同一 Assignment 写事务决定：取消先提交则启动资格更新失败；开工资格先提交则同一 `run_id` 成为本地运行事实，之后的取消只请求合作停止，且只有执行器确认安全停下才产出 `stopped_by_cancel`。单流冲突或 busy 不能阻塞其他 Assignment；没有网络 I/O 的数据库竞争仍受单个写事务边界约束。

### D. 本地数据库、版本与初始化

隔离 CPU profile 推荐本地 SQLite 文件数据库和独立 SQLAlchemy/Alembic 环境。SQLite 支持单机事务与零服务依赖，适合作为 M4.2 文件库/重启验证；SQLAlchemy/Alembic 与 Cloud 现有 Python 工具链一致，但 Edge 维护自己的 package、Base/metadata、版本目录和 Alembic 配置，不能引用 Cloud schema。迁移只有持有同一 OS 独占锁的显式命令运行，应用启动只校验版本和 ready 条件，不执行升级；旧/未知版本保持 not-ready。

Schema 升级建议使用“SQLite Backup API 一致快照 → 独立候选库升级 → 校验 → 原子切换”而不是原库原位 DDL：在 OS 锁内列出当前 revision 并检查 SQLite 连接；使用 SQLite `Connection.backup()`（含 WAL 一致状态）建立保留的升级前快照，不对仍运行的 WAL 数据库做普通文件 `cp`；对快照执行 `integrity_check`、`foreign_key_check`、revision/表/索引/唯一约束检查，再在候选副本跑目标 Alembic revision。候选库必须关闭连接、核对 revision、约束及本 Change 的数据不变量（身份唯一、Cursor 非负/round 上界关系、Outbox 序号无重复/无缺口、envelope fingerprint、文件关联），并生成候选摘要。

验证通过后，先 fsync 候选文件和同卷父目录，写入并 fsync `upgrade-manifest`（operation id、源/目标 revision、活动原库/一致快照/候选路径及摘要、`prepared` 阶段），确认没有 DB 连接并完成可验证的 WAL checkpoint，再用同文件系统原子替换活动 DB，fsync 父目录并回读核对目标 revision/完整性；manifest 的 `activated` 记录只在核对后更新。替换原语失败则原库仍活动。进程在原子替换前后任一窗口（含替换已完成、manifest 尚未更新）崩溃时，启动在同一锁内读取 manifest 和唯一活动 DB 的 revision/摘要：源 revision/摘要仍活动时保留源库并保持 not-ready，等显式 resume/rollback；目标 revision 与已验证候选摘要一致且完整性通过则可识别为切换已完成并完成审计记录；任何不匹配或无法唯一识别都保持 not-ready 并保留原库、快照、候选库和 manifest，禁止自动新建空库或猜测。

DB 备份/候选失效、DDL 中止、revision 写入失败、候选验证失败、切换前退出均不得修改活动原库。切换后也保留升级前快照和日志作为本 Change 的审计/恢复证据；本设计不设生产备份保留期限或 RPO/RTO。恢复命令需要显式选择原库/候选库并验证后才可开放 Runtime。

文件库采用本机持久卷，显式配置 `EDGE_DATA_DIR`，其下建议分 `db/edge-runtime.sqlite3`、`files/staging/`、`files/objects/`、`files/quarantine/`。隔离 profile 可显式设置 SQLite WAL、`synchronous=FULL`、外键检查与有界 busy timeout；测试应重新启动进程而非仅重建连接。备份需要通过 SQLite 一致性备份/快照机制涵盖 DB 与文件目录，并在恢复时重新校验对应关系。

SQLAlchemy Core/ORM + Alembic 的版本依赖必须放在 `services/edge-runtime/` 独立锁文件中。SQLAlchemy 当前 MIT、Alembic BSD-3-Clause。Python `sqlite3` 手写迁移依赖少，但会自建版本升级及数据库抽象；以当前 Edge 需要可版本化 Schema 且保留生产 PG 评估为由，本 Change 推荐 SQLAlchemy/Alembic。当前 Cloud pins 可参考，不能直接复用 Cloud 安装环境或锁定结果。

PostgreSQL 在多进程写入、备份/监控和现场运维能力清晰时可能更合适，但 M4.2 测试需要额外数据库服务，当前并无多节点共享写或生产负载证据。故隔离测试不依赖 PostgreSQL，生产选型留待负责人结合资源、可靠性、部署复杂度评估。Redis 不能作为 durable inbox/outbox 或 task truth；SQLite 已有持久队列，不因未来方案草案中出现 Redis 就把它加为必需依赖。Redis 各版本许可有变化，若未来确有需求应按精确版本审查许可。

### E. 本地文件与数据库一致性

把文件数据库和大文件放在同一显式 Edge 数据根目录，但 DB 不存文件 bytes。`staging/` 与不可变 `objects/` 必须同一文件系统，init 和每次 publish 前比较两个目录的 `st_dev`；不相等或出现 `EXDEV` 时拒绝发布。所有路径是相对数据根目录的规范路径；拒绝绝对路径、`..`、符号链接组件、根目录被替换和目录外解析。实现以已打开的目录文件描述符和 `openat`/`O_NOFOLLOW` 等平台等价机制完成检查/创建；只做字符串 `resolve()` 后再按路径打开不足以抵御替换竞态。`LocalFileRecord` 是 staging intent 和恢复凭证。

发布过程：

1. 先提交 staging FileRecord intent 和 file_id/最终路径/关联业务事实标识。
2. 以唯一临时名写文件，flush/fsync，计算大小和 SHA-256；需要预期摘要时必须相等。
3. 提交 `staged_verified` 状态。
4. 使用同卷、原子且 no-replace 的发布原语 rename 到唯一最终路径，并 fsync 文件和源/目标父目录。目标已存在时不覆盖；若目标平台无可靠 no-replace 原语则 fail closed，不用 check-then-rename 或 copy+delete 伪装原子性。
5. rename 与目录 fsync 均成功后，单独提交 `FileRecord=file_state=published` 及其发布时间/文件元数据。该提交点是 `published` 的定义；此事务不生成业务事实或序号，文件仍不可被 Worker/API 引用。
6. 在另一个最终业务事务中一起写 `LocalCaptureFact`、不可变 Outbox envelope、Assignment sequence，并把 FileRecord 改为 `available`。只有该事务提交后才允许本地引用；本地 `available` 不代表 Cloud MediaObject 或 `VideoAsset.ready`。
7. 每次启动按 FileRecord 扫描阶段、路径、size 和元数据；未完成/上次异常关联/未结恢复/元数据异常的文件须完整重算 SHA-256，普通历史文件走分级快速检查和定期完整性巡检（见 K.4）。

| 崩溃窗口 | 恢复处理 |
| --- | --- |
| intent 前/目录扫描发现无登记文件 | 按孤立候选登记，隔离且不提供引用；不因名字/年龄自动删除 |
| 临时文件写入中 | DB intent 存在但缺少验证 hash；标记 `recovery_required`，保留 temp/original 文件 |
| temp fsync 后、DB 记录校验值前 | 重新计算并按 intent/已知目标验证；证据不全则挂起，不猜测归属 |
| verified temp 后、rename 前 | 重算并匹配持久摘要后重试 rename；不匹配就隔离 |
| rename 和目录 fsync 后、`published` DB 提交前 | 持久状态仍为 `staged_verified`；依据 intent、final path 和摘要重验，幂等提交 `published`，不生成 CaptureFact/Outbox/sequence |
| `published` 提交后、最终业务事务前 | 重验 final 后原子补做 CaptureFact、Outbox/sequence 和 `available`；唯一事实键保证最多一次，不重复追加序号 |
| `published` 提交失败或进程退出 | DB 保持 `staged_verified`；按前一行扫描并收敛，不删除 final |
| 最终业务事务提交失败或进程退出 | DB 保持 `published`，不存在半个业务事务；重启校验后幂等重试，不覆盖文件 |
| 最终业务事务提交成功后退出 | 启动重验；一致则恢复引用，不一致则 `recovery_required` 并阻止读取/执行 |
| DB row 指向缺失/损坏文件 | 保留 DB/文件证据，标记异常，不以 Cloud ACK 或重新录制覆盖旧引用 |
| file 无 DB row | 隔离 orphan、登记人工恢复；M4.2 不自动清理任何原始视频 |

ENOSPC、fsync 错误、EXDEV 和路径检查失败都走同一失败闭环：不提交可用 FileRecord/CaptureFact/Outbox，不覆盖最终文件、不删除 staging/original bytes；若数据库尚可写则写 Assignment 级 RecoveryRecord。若磁盘/SQLite 同时满到无法写 RecoveryRecord，预先持久化的 staging intent 仍是恢复锚点，Runtime 报 `not_ready` 并输出无敏感内容的操作错误；下次具备写入空间时再幂等派生 RecoveryRecord，不谎称故障记录已经入库。目标目录已存在、符号链接、路径越界、硬链接/重复路径归属不符均进入只读异常，不读或引用根目录外内容。

本设计不声称数据库与文件系统具有同一原子事务，也不通过两阶段提交模拟。损坏文件、恢复失败或缺少期望摘要时，选择停止使用并留证；生产保留/删除政策另行批准。

### F. 幂等、重试、收据与故障隔离

- 按 M4.1 对完整事件 envelope 做严格白名单与规范化，保存最终 UTF-8 内容和 SHA-256 fingerprint。字段排序、等义 UTC 表示等规则复用 `docs/contracts/cloud-edge-sync-v1.md`，不能另定义 Cloud 协议。
- 收到重复同命令/事实时比较 scope、ID、sequence 与 fingerprint；同内容沿用原结果，异内容保留 original 并将受影响流标记异常。
- `LocalEventOutbox` 对每 Assignment 只发送头部未确认事实，不同 Assignment 可独立进行。成功仅凭匹配的结构化收据；Cloud 游标可做对账线索，不能清理本地 Outbox。
- 429 尊重有效 `Retry-After`；瞬态失败采用有界指数退避+抖动。每轮预算耗尽暂停快速发送但保留队列。永久 4xx/完整性冲突进入 `recovery_required` 或人工处理，不修改 envelope/跳序。
- health/diagnostic 聚合 pending 数量、最老 pending、各流头序号、`safety_hold` 与 open recovery 数，不输出 token、完整事件、用户信息或原始路径。

隔离 profile 的 P01–P10 仅用于开发/测试：P01 连接 2 秒，P02 总请求 5 秒，P03 初始退避 1 秒，P04 上限 30 秒，P05 ±20%，P06 首次之后至多 3 次或 30 秒先到，P07 有效对账/显式恢复/60 秒冷却探测后才重置，P08 每 Assignment 100 件或最老 300 秒告警，P09 正常 15 秒并在网络恢复时合并立即对账，P10 不可恢复缺口挂起且单次人工操作 300 秒后仍挂起。P04 的 `Retry-After` 即便超过本轮 budget 也要尊重；预算耗尽保留后续时机。任何配置不得成为生产默认。

### G. 离线、取消与恢复顺序

启动恢复按以下顺序运行：取得 OS 独占锁 → 加载显式数据目录及受支持 Schema → 核对不可变 RuntimeIdentity 与配置 scope → 检查上次关闭标记/升级 manifest → 检查 DB 状态 → 扫描 FileRecord、目录和待恢复事务 → 校验 Inbox/cursor/固定轮次、Outbox/Assignment 序列 → 加载 Node SafetyHold 与 Assignment RecoveryRecord → 仅对证据充分、未取消、无阻断原因的已接单 checkpoint 恢复 Worker。关键扫描未完成期间 readiness=false，Dispatcher、命令消费者和任务启动全部关闭；本地 health/diagnostics 仍可报告 `recovering`。assignment 级错误只隔离该 Assignment；DB/identity/schema/目录全局错误使 Runtime 全局 not-ready。

普通断网、凭据自然过期和仅撤钥只暂停 CloudAdapter，不清除已接单本地资格；未接单 Assignment 仍等待有效控制流。单个 401 不区分到期/撤销/停用，也不产生 `safety_hold`。配置三元组匹配但无有效认证时，local readiness 可以为 ready，cloud sync readiness 单独为 paused；不得拉命令或发送 Outbox，已接单本地任务按账本继续。认证恢复后先验证当前作用域，再对账并重投原 envelope。MockCloudAdapter 只能注入经验证的 Node disabled 或可信本地停机语义，不声称存在生产通知通道。

应用取消命令时，Inbox、Task/Assignment 的 cancellation gate、cursor 同事务。尚未开工任务立即失去开工资格；运行任务收到 cooperative stop 请求并保存 checkpoint。只有执行器证明确实安全停下，状态提交后才产生 outcome=`stopped_by_cancel` 的终态 Outbox。取消之前已产生的事实、取消之后合法迟到的事实以及待确认 Outbox 都保留。M4.1 中 Cloud 合法终态优先、取消事实不回滚 Cloud projection 的服务器侧裁定不在 Edge 实现。

`safety_hold` 与任务取消是两个不同因果。Node 级 `LocalSafetyHold` 每个已验证原因独立持久化；任一 active 原因阻止本 Node 所有新开工并请求运行任务在安全检查点暂停，不能伪造 `stopped_by_cancel`。Assignment 级缺序号、冲突或文件损坏留在 `LocalRecoveryRecord(scope=assignment)`，只阻断该分配，健康分配可继续。解挂只针对明确 hold_id，追加 actor reference、时间、原因及恢复条件证据；解除一个原因不自动解除同 Node 其他原因或 Assignment RecoveryRecord。M4.2 测试以显式测试 operator context 演练；正式操作者身份、权限来源和 UI 留后续安全审查。

### H. 运行配置和诊断面

隔离运行 profile 由显式 `EDGE_DATA_DIR`、SQLite profile、MockCloudAdapter、FakeClock/FakeNetwork 和 DeterministicWorker 组成；文件/数据库目录不会落入 Cloud `var/` 或开发者 repo。迁移命令与 server command 分开。运行期发现新库但未初始化时只报 not-ready；不在 web startup 自动跑迁移。

最小 health/readiness/diagnostics 在隔离 profile 仅监听 loopback。运行状态对外区分 `uninitialized`、`initializing`、`recovering`、`ready`、`not_ready`、`identity_mismatch`、全局 `recovery_required`；Cloud 同步状态、Node SafetyHold 和各 Assignment recovery block 是独立维度。`ready` 代表本地持久服务和必需启动扫描通过，不代表 Cloud 可达；仅 Cloud 认证作用域验证通过时才开放云收发。Node Hold 不必关闭只读 health API，但阻止开工；局部 RecoveryRecord 不阻塞健康 Assignment。diagnostics 只读且脱敏。此 endpoint 不是 Venue Console 或生产控制面。具体场馆 LAN 绑定、身份认证、TLS 和现场运维入口仍待批准。

数据库里只保存 Node ID 与必要 scope ID，不保存 EdgeCredential 明文；凭据由未来明确的 SecretProvider/OS secret store 注入，并禁止出现在日志/诊断。M4.2 Mock 不需真实令牌。生产 secret store、轮换/投递是另一个安全边界。

### I. M4.1、Cloud、M1–M3 兼容性

- D1–D5 由本 Change 的本地行为 Delta 落实；不重定义 v1 command/event JSON、8192-byte 信封、50/page、序号或 ACK 语义。
- Cloud 是 TrainingSession/Task/Assignment、取消和授权正式权威。Edge 保存 local command receipt、本地运行状态和事实，不直接更新 Cloud 状态。
- Inbox/outbox/本地 cursor 不写 Cloud Database；不新增 Cloud API/OpenAPI/migration 或修改六份 Cloud 主规格。
- Event receipt、local file publication、M3 upload, cloud asset ready 和 read grant 独立。M4.2 仅本地 file record；M4.4 仍需测试 M1–M7 上传/续传。
- M4.2 隔离 Edge tests 与现有 Cloud CI 分开识别；现有 Cloud CI 结果只代表 M1–M3 兼容基线，不作为 Edge runtime 运行证明。

### J. 隔离测试与故障注入

本 Change 的设计测试使用持久 SQLite 数据文件、持久临时/最终文件目录、可注入 clock/network、MockCloudAdapter 和合成 payload；独立子进程重启时复用相同数据目录，SQLite 并发场景用两个独立 Connection/Session。Tasks 保留 T-01–T-20，并增加 T-21–T-46 覆盖身份/进程锁、严格命令/固定水位与 `next_after`、Cloud Projection Revision、并发序号、文件系统异常/`published` 提交点、升级中断保护及分级启动扫描和性能记录。测试矩阵按 EPR Requirement 和状态转移拆到各自实现任务，不以 Task 10 取代组内验收。

M4.2 验收到隔离适配器边界即止。无 Cloud 服务、无两套真实进程 HTTP 联调、无摄像头/GPU、无生产环境配置或数据；M4.4 另绑定真实提交 SHA 与网络集成证据。

### K. M4.1 下行协议与固定命令轮次

接收顺序固定为：取得独占锁且本地 RuntimeIdentity 与配置一致 → 校验当前 CloudAdapter 认证 scope 的 Tenant/Site/Node 一致 → 读取分页原始 JSON/字节并检查分页结构和固定 `through` → 校验命令数 ≤50 → 对每条命令测量实际 JSON UTF-8 字节数 ≤8192 → 严格解析/字段与方向校验 → 校验版本、UUID、UTC、整数范围、载荷及资源归属 → 校验节点序号连续性 → 才允许事务写入。

CloudAdapter 必须向 Command Service 暴露可验证原始 JSON 字节或等价保留重复键信息的输入；先将对象解析成普通 dict 再做验证无法发现重复 JSON key，不能作为合格边界。单命令 8192 字节上限包含 JSON 空白和 payload 字节，不包含 HTTP 头；50 是每一分页的条数限制，两者互不替代。超过上限时输入读取本身应有界，不将超限正文缓存进内存/数据库。

命令接收门按以下顺序执行：

1. 在访问任务/Outbox/命令账本前核对本地 RuntimeIdentity 与显式 Tenant/Site/Node 配置；身份不符即 `identity_mismatch` 并停止本轮。
2. 在请求或接受任何下行页前，验证当前 CloudAdapter 认证绑定的 Tenant/Site/Node 与 RuntimeIdentity 完全一致；不一致不读取待发信封、不发起 ACK/上行或命令应用。
3. 对有界流式输入做分页对象/列表形状、`through` 类型/安全范围/不回退和活动轮次一致性预检；页数超过 50 或页结构不合法时整页零应用。
4. 对每条原始命令按实际 UTF-8 字节数限额检查，再做保留重复键信息的严格 JSON 解析、闭集字段/版本/UUID/UTC/安全整数/方向/类型/载荷校验。未知字段立即拒绝，不把未知大字段或超限命令缓存。
5. 校验命令序号连续性及 Node/Tenant/Site/Task/Assignment 归属；只有通过的单条命令才能进入 Inbox/命令效果/Cursor 同一原子事务。每条提交后可发送不超过已提交连续 Cursor 的 ACK；ACK 不参与业务接单/执行状态转移。

若认证响应缺少可验证原始 JSON 字节或等价重复键信息，Adapter 不得将其降格为普通对象后当作有效协议输入。

严格规则完全引用 `docs/contracts/cloud-edge-sync-v1.md`：对象字段闭集、重复 JSON key/未知字段/错误方向/未支持类型或版本拒绝；`schema_version` 必须是整数 1（不能接受布尔值）；UUID 为小写连字符规范；UTC 时间采用契约的等义 `Z` 表示；JSON 整数处于安全整数范围；可选时间缺失统一省略、显式 null 拒绝；命令载荷/枚举/Task 与 Assignment 版本和 Node/Tenant/Site 归属必须符合该契约。命令实际字段和规范化以正式契约及其示例为唯一来源，M4.2 不另起协议。

分页级先验校验包括对象形状、闭集字段 `commands`/`through`/`next_after`、列表形状和页数；请求 `after`、响应 `through`、`next_after` 均须为非布尔 JSON 整数，范围为 0 到 2^53−1，且 `through >= after`。`through` 不回退且活动轮次内必须等于已持久的 `round_through`。`next_after` 必须满足 `after <= next_after <= round_through`。非空页命令序号须从 `after+1` 连续到本页最后一条，且 `next_after` 必须等于该尾序号。空页必须满足 `next_after == after`，不能宣称推进；只有本地 Cursor 已等于 `round_through` 才能结束轮次，若 `after < round_through` 则保持原水位/游标、不 ACK 越位并按有界重试处理，持续无进展转 `recovery_required`。精确重复页仅允许逐条命令与已持久 Inbox 完全同 ID/同内容，按重放幂等，不回退本地 Cursor。任一分页游标/尾部校验失败，整页零应用、零 Cursor 变化。`next_after` 是服务端页位置声明，不持久化为本地已应用进度；下一次进程启动/故障重试一律以持久 `last_applied_sequence` 构造 `after`。若一个新轮次首响应全部通过这些分页级检查，则在处理第一个命令前单独原子持久化 `round_through`；重启必须继续该上界，不能另取水位覆盖。分页合法后，逐条命令完整校验，再对连续序号应用独立原子事务。若 N 非法、缺失、异 ID 占同序号或同 ID 异内容：N 前已提交的合法连续前缀保留；N 不写入 Inbox/效果/Cursor，N 后均不应用；ACK target 只能是 N−1；流保留在同一 `round_through` 并转为诊断/`recovery_required`。重复同 ID/同内容/同序号重放原结果但不二次执行；不得跳过 N 等待后续命令。诊断只记录错误类别、期望/观察序号、字段路径和正文指纹等有界脱敏信息，不存完整未经信任的 raw page。

`CommandAckState.desired_through` 从 `last_applied_sequence` 派生。网络发送尝试、Cloud 响应水位在单独 ACK 记录中可审计，但不能修改 Inbox `applied` 状态或代表 Task 已接单/Worker 已执行。完成当前固定轮次的唯一条件是本地连续 Cursor 到达该轮 `round_through`；提交完成后才能清空轮次并开始新拉取。

### L. 文件系统错误、Schema 升级与恢复一致性

| 故障 | 持久结果与 Runtime 行为 |
| --- | --- |
| 文件写入中 ENOSPC | intent 已先落库；半成 staging bytes 不可引用，保留来源和已写字节，Assignment 记恢复原因；运行中 DB 也写不了时全局 not-ready，恢复后按 intent 补写有界记录 |
| 文件 flush/fsync 失败 | 不进入 `staged_verified`，不发布、不提交 CaptureFact/Outbox；文件留在 staging 并等待重新验证或人工处理 |
| SQLite DB/WAL ENOSPC 或 fsync/IO 错误 | 事务不作为已提交证据；关闭新写/开工并在重开后查真实账本，不能根据调用返回前的内存结果补发事件 |
| 最终目录空间不足 | 发布失败不覆盖、不删除 staging/original；FileRecord 保持之前阶段并局部阻断 |
| `EXDEV` 或 staging/objects `st_dev` 不同 | 不用 copy+delete 替代原子 rename；保留源、记录诊断并保持不可引用，直到恢复到同卷条件 |
| 路径穿越、符号链接/根目录替换、重复/硬链接异常归属 | 通过目录 fd/no-follow 检查拒绝打开或发布；不读取数据根之外、不覆盖、将受影响 FileRecord 置阻断 |
| 文件缺失/摘要不符/无 DB 记录 | 不引用；逐 Assignment 记 open RecoveryRecord；原数据库和现有字节只读保留，绝不自动删原片 |

升级活动 DB 前先使用 SQLite Backup API 获取一致快照，再在候选库执行迁移；候选 `integrity_check`、`foreign_key_check`、revision、唯一约束、索引和账本不变量全通过前不切换。切换要求单实例锁、所有 DB 连接关闭、WAL checkpoint 核验、候选和活动 DB 同文件系统原子替换，并有 fsync 的外部 `upgrade-manifest`。故障边界明确为：迁移前/中/DDL 后 revision 失败/候选校验失败/切换前崩溃均维持活动原库；切换操作是单次原子 replace，重启只有在目标 revision 与候选摘要匹配时才认定已切换，否则 not-ready 并保留原库、快照、候选、manifest；不静默 resume/rollback。

### M. 启动必需扫描与历史文件完整性策略

每次启动都完成轻量但全覆盖的账本恢复扫描：Schema/revision 和 `integrity_check`；RuntimeIdentity；升级 manifest；上次运行是否 clean；所有活动/未完成 FileRecord 与 staging 文件；所有未结 RecoveryRecord；活跃 Assignment checkpoint 和取消版本；CommandInbox 连续性、`last_applied_sequence`/`round_through` 关系；Outbox 每 Assignment 的唯一连续序列及投递状态；所有 Node SafetyHold；受控数据目录与 `staging`/`objects` 同设备关系；目录枚举中未登记文件。恢复完成前 readiness=false，禁止 Worker/Dispatcher/命令消费者接触未核验条目。Assignment 级单项损坏隔离该 Assignment，其他健康分配不受连带阻断；身份、数据库、Schema 或全局文件根失效阻断整个 Runtime。

每次启动重新计算完整 SHA-256：未完成 staging/publish、上次非 clean shutdown 涉及、活动写入期间、open RecoveryRecord 关联、size/path/设备/权限/mtime_ns 等元数据不符、初次登记/上次 hash 未完成的文件。对 clean shutdown 后不可变、已完整校验、路径/size/mtime_ns/设备号/受控权限均未变且没有异常关联的历史文件，启动可以执行 metadata 快速检查而不全量重哈希；其状态只是 `previously_hash_verified + metadata_consistent`，不得标记为“本次启动已重新验证摘要”。信任假设是单实例锁成立、目录访问受限、文件不可变。mtime/inode/st_dev 任一项都不是密码学完整性证明；潜在外部写入即使保留元数据也可能漏检，因此要提供有界 CPU 的后台/显式完整性巡检，并在任何未来媒体上传/Cloud 发布前完整 hash。若发生任何可疑变化，立即完整 hash并阻断引用直到处理完成。

不用生产 SLA 预设启动速度。T-43 使用固定生成器和可复现 manifest，记录文件数、总字节、大小分布、快速扫描总耗时、完整 SHA-256 耗时、未完成文件恢复耗时、DB 查询耗时、未结记录数及 readiness 完成时刻；分别覆盖全历史 hash 路径和分级快速检查路径。实际现场目标阈值、磁盘规模和巡检周期保留给生产评审。

## Risks / Trade-offs

- **SQLite 单写入者和单节点特性** → 把 M4.2 profile 限制为单 Edge Runtime 应用；出现多独立写进程/现场运维证据后评估 PostgreSQL，不宣称 SQLite 已获生产批准。
- **WAL/文件卷掉电和硬件缓存行为未知** → 选择 `synchronous=FULL`，每个发布窗口故障注入；目标现场磁盘的断电耐久仍需硬件验收。
- **文件 rename 与数据库提交不能原子化** → 持久 staging intent、hash、不可变路径、恢复扫描；任何不确定文件隔离且不自动删除原件。
- **Cloud 接口当前不存在** → MockCloudAdapter 对照签认契约行为；M4.2 不把模拟结果报为 M4.3/M4.4 完成。
- **生产 Redis 许可/运维与本地事实层重叠** → 首片不用 Redis；未来启用前按确切版本及许可证审查实际必要性。
- **安全通知不可达** → 只处理可信验证的测试/本地来源；不从断网或 401 推断停用，生产远程通知单独评审。
- **恢复扫描耗时或发现损坏** → readiness 保持 false；分 Assignment/文件隔离诊断，恢复失败时保留整个原目录供人工处置。
- **操作者身份/访问策略未批准** → diagnostics loopback、只读、脱敏；解挂 API 与正式授权集成不得暴露为场馆 LAN 控制面。
- **OS 文件锁/原子 no-replace 对不同文件系统实现有差异** → 隔离 profile 使用已验证的本机文件系统与 advisory lock；无法证明锁或原子发布语义的平台 fail closed，生产挂载类型另评。
- **分级 hash 存在 metadata 未变化但内容被外部篡改的盲区** → 限制数据目录写权限、只在单实例访问、保留最近完整 hash 时间和差异线索、提供完整性巡检；媒体上传/发布前强制完整摘要，生产巡检周期另批。
- **空间耗尽时无法将故障原因写回 SQLite** → 事先持久的 FileRecord intent 保留补偿锚点，服务 not-ready 并向本地诊断/进程日志报告边界错误；恢复可写后幂等生成 RecoveryRecord。
- **Schema 候选切换与 DB/WAL sidecar 中断** → 只在锁内全连接关闭并验证 WAL checkpoint 后以单个原子替换切换；升级 manifest 和旧快照留存，状态不明确就 not-ready。

## Migration Plan

本 Change 为提案，不实施迁移或部署。后续 Apply 若获单独授权：

1. 在 `services/edge-runtime/` 创建独立 package、SQLite profile、Schema 初始 revision 与显式初始化/升级入口，不改 Cloud Alembic 环境。
2. 在同一 RuntimeIdentity 与 OS lock 保护下对全新临时目录做显式初始化；对非空库先 Backup API 快照、候选升级和校验，再受控切换；服务启动只验证 Schema/Identity，不自动迁移。
3. 逐步接入严格命令验证/分页水位、Inbox/Cursor/ACK 分离、Task/Assignment 状态机、并发事务/序号、Outbox、FileRecord 和 Hold/Recovery 的接口，再接 adapter/worker/clock injection。
4. 以 subprocess + 持久测试目录注入崩溃并验证恢复矩阵；记录每个测试实际提交 SHA。
5. 不向现有用户库/生产路径迁移，不自动导入真实/历史数据。SQLite 到 PostgreSQL 如获批另建独立评估和变更。
6. 失败回滚限于删除本次创建的隔离测试目录；若任何目标目录已有数据，不执行删除或自动降级，先保留并人工恢复。

## Open Questions

以下只影响后续部署/安全或生产选型，可在 M4.2 隔离 profile 之后独立批准；不改变本 Change 已选的隔离行为：

- 生产场馆选 SQLite 还是 PostgreSQL，是否有可观测证据支持 Redis；生产并发/硬件盘/备份/RPO/RTO 的门槛是什么？
- 生产 `EDGE_DATA_DIR`、存储容量阈值、备份保留和业务视频删除策略由谁批准，是否有硬件级掉电保护要求？
- Edge Credential 应由哪种受控 secret store/安装渠道注入；生产本地 diagnostics 的网络绑定、身份验证和 TLS 如何批准？
- 节点停用的可信通知源、现场操作者认证与解挂审计 UI 由哪个后续 Change 定义？
- 完整 Worker 的检查点粒度、不可幂等副作用保护及主机重启后的安全停止证明由 ES-05/ES-06 如何细化？
- 生产挂载类型是否可靠支持 advisory lock 与同文件系统 atomic no-replace rename；历史文件全量校验的现场规模、后台巡检周期和 readiness 性能目标是多少？
