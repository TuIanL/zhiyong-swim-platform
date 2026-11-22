# Design

## Context

见 [Proposal](proposal.md) 的问题与范围；行为边界以 [Edge Runtime Persistence Spec Delta](specs/edge-runtime-persistence/spec.md) 为准。当前仓库的 Edge Runtime 是 README scaffold。Cloud 已有独立 Registry、身份、Session、媒体授权和 M3 上传实现；Cloud 任务/同步服务端尚未实现。M4.1 要求持久 Inbox/cursor、接单/事实 Outbox 原子提交、按 Assignment 序号、精确收据匹配、离线继续及显式 `safety_hold`。

设计约束：Edge 不共享 Cloud ORM/数据库；一个 Edge Runtime 是先按单进程模块化应用建设；本地业务状态由数据库持有，大媒体文件在数据库外；数据库和文件系统没有共同原子提交；M4.2 使用 CPU/本地持久卷与 Mock 对端，生产部署配置仍未定。

## Goals / Non-Goals

**Goals:**

- 建立清晰的本地持久化模块边界，保证 Inbox/cursor、业务事实/Outbox 和逐 Assignment 连续序号具备单事务原子性。
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
| `LocalCommandInbox` | `event_id` PK；唯一 `(node_id, command_sequence)`；索引 `(assignment_id, command_sequence)` | 保存完整规范化命令、SHA-256 fingerprint、版本、scope、接收/应用时刻及结果；同 ID 异内容不得替换原值 |
| `CommandCursor` | `node_id` PK；`last_applied_sequence >= 0`；当前固定轮次可有 `round_through` | 只代表本地原子应用到的命令位置；不能用 Cloud 已 ACK 推断本地状态 |
| `LocalTrainingTask` | Cloud `task_id` PK；保存外部 Tenant/Site/Session IDs | 分离 Cloud 下发状态、Edge 本地接单/执行 phase、检查点版本和最近命令版本 |
| `LocalAssignment` | `assignment_id` PK；v1 `task_id` 唯一；`next_event_sequence` 单调 | 保存 Node/task 关联、序列分配、执行 run ID/attempt、checkpoint 和局部 recovery 状态 |
| `LocalCaptureFact` | `capture_id` PK；唯一 `(tenant_id,site_id,node_id,assignment_id,capture_id)` | 保存 M4.1 白名单的来源 Device、已知 UTC/原始设备时间、有限 metadata 和可空 file_id |
| `LocalEventOutbox` | `event_id` PK；唯一 `(assignment_id,sequence)`；索引 `(delivery_state,next_attempt_at)` | 保存不可变 canonical envelope/fingerprint；传输状态、尝试预算与匹配收据是可变的投递元数据 |
| `LocalSafetyHold` | `hold_id` PK；按 Node/scope 索引 active hold；hold/release 保留历史 | 保存已验证原因、来源引用、时间、操作者引用和显式释放原因；每次变更可审计 |
| `LocalFileRecord` | `file_id` PK；staging/final 相对路径唯一；索引 `(state,created_at)` | 保存期望/观测 size、SHA-256、文件状态、capture/assignment/task 关系及阶段时间 |
| `LocalRecoveryRecord` | `recovery_id` PK；scope/state 与来源记录索引 | 幂等记录缺口、坏摘要、孤立文件、未知 Schema 等诊断；含脱敏证据及人工处置历史 |

序号由 `LocalAssignment` 单独分配而非全局序列；插入 Outbox、推进 next sequence 和提交业务事实在同一事务内。`event_id` 在该事务首次产生并持久保存。Outbox envelope 列在应用层不可更新；仅发送状态、尝试、收据和诊断字段可变。Cloud IDs 都是外部标识符，不设跨数据库外键。

持久事实包括所有 Inbox/envelope、cursor、已接单与执行检查点、CaptureFact、Outbox 原件、文件关联、active safety hold 和未结 RecoveryRecord。连接状态、进程对象、HTTP 客户端和可由账本重建的缓存不持久化。Outbox 至少保留到精确匹配收据，M4.2 不提出清理已确认事实或删除原始文件的策略。

### C. 本地事务边界

| 操作 | 同事务写入 | 提交之后 |
| --- | --- | --- |
| 接收命令 | Inbox 原 envelope + 命令本地效果/Task 状态 + `CommandCursor` | 仅发送最新连续 `through` ACK；丢响应可从持久 cursor 重发 |
| 业务接单 | 本地 Assignment/Task 接单状态 + sequence=1 的 `training_task.accepted` Outbox | 允许离线调度；事务失败时不接单/不执行 |
| 采集事实 | LocalCaptureFact + `LocalFileRecord=ready` + Outbox envelope + Assignment sequence | 文件/事件可被本地读和重试；上传媒体仍为独立授权流程 |
| 真实任务终态 | LocalTrainingTask/Assignment 终态 + 原 outcome 的 Outbox envelope + sequence | 终态只写一次；迟到事实不删除或改写 Cloud cancelled 的结果 |
| 收据确认 | 精确 request scope 与 ID/sequence/disposition 通过后的投递状态、原收据 | 单独更新 delivery metadata，不修改 event envelope |
| 挂起/解挂 | `LocalSafetyHold` 审计记录 + Assignment 调度门槛 | hold 持久生效；重启不清除 |

SQLite 写事务串行完成；具体实现应在读取/比较 cursor 后用一个写事务提交所有相关行，不能把 ACK 网络调用放进数据库事务。网络请求失败不会回滚已提交的 Inbox/Outbox。提交后响应丢失时只重发原命令水位/事件；Cloud response 仅在与发请求时认证 scope、本地 envelope 及原 request correlation 完全匹配时确认对应 Outbox 项。

### D. 本地数据库、版本与初始化

隔离 CPU profile 推荐本地 SQLite 文件数据库和独立 SQLAlchemy/Alembic 环境。SQLite 支持单机事务与零服务依赖，适合作为 M4.2 文件库/重启验证；SQLAlchemy/Alembic 与 Cloud 现有 Python 工具链一致，但 Edge 维护自己的 package、Base/metadata、版本目录和 Alembic 配置，不能引用 Cloud schema。迁移只有显式命令运行，应用启动只校验版本和 ready 条件；失败保持原库并退出 not-ready。

文件库采用本机持久卷，显式配置 `EDGE_DATA_DIR`，其下建议分 `db/edge-runtime.sqlite3`、`files/staging/`、`files/objects/`、`files/quarantine/`。隔离 profile 可显式设置 SQLite WAL、`synchronous=FULL`、外键检查与有界 busy timeout；测试应重新启动进程而非仅重建连接。备份需要通过 SQLite 一致性备份/快照机制涵盖 DB 与文件目录，并在恢复时重新校验对应关系。

SQLAlchemy Core/ORM + Alembic 的版本依赖必须放在 `services/edge-runtime/` 独立锁文件中。SQLAlchemy 当前 MIT、Alembic BSD-3-Clause。Python `sqlite3` 手写迁移依赖少，但会自建版本升级及数据库抽象；以当前 Edge 需要可版本化 Schema 且保留生产 PG 评估为由，本 Change 推荐 SQLAlchemy/Alembic。当前 Cloud pins 可参考，不能直接复用 Cloud 安装环境或锁定结果。

PostgreSQL 在多进程写入、备份/监控和现场运维能力清晰时可能更合适，但 M4.2 测试需要额外数据库服务，当前并无多节点共享写或生产负载证据。故隔离测试不依赖 PostgreSQL，生产选型留待负责人结合资源、可靠性、部署复杂度评估。Redis 不能作为 durable inbox/outbox 或 task truth；SQLite 已有持久队列，不因未来方案草案中出现 Redis 就把它加为必需依赖。Redis 各版本许可有变化，若未来确有需求应按精确版本审查许可。

### E. 本地文件与数据库一致性

把文件数据库和大文件放在同一显式 Edge 数据根目录，但 DB 不存文件 bytes。`staging/` 与不可变 `objects/` 必须同一文件系统，保证本地 atomic rename 条件；相对路径以数据根目录解析，拒绝目录穿越和符号链接替换。`LocalFileRecord` 是 staging intent 和恢复凭证。

发布过程：

1. 先提交 staging FileRecord intent 和 file_id/最终路径/关联业务事实标识。
2. 以唯一临时名写文件，flush/fsync，计算大小和 SHA-256；需要预期摘要时必须相等。
3. 提交 `staged_verified` 状态，随后同卷原子 rename 到唯一最终路径，并 fsync 文件和父目录。
4. 最终 DB 事务一起写 `FileRecord=ready`、LocalCaptureFact 和不可变 Outbox；这一提交之前任何消费者都不得引用对象。
5. 启动恢复按 FileRecord 逐个核对 staging/final 两处文件、完整大小和 hash；只有全部匹配才推进可用状态。

| 崩溃窗口 | 恢复处理 |
| --- | --- |
| intent 前/目录扫描发现无登记文件 | 按孤立候选登记，隔离且不提供引用；不因名字/年龄自动删除 |
| 临时文件写入中 | DB intent 存在但缺少验证 hash；标记 `recovery_required`，保留 temp/original 文件 |
| temp fsync 后、DB 记录校验值前 | 重新计算并按 intent/已知目标验证；证据不全则挂起，不猜测归属 |
| verified temp 后、rename 前 | 重算并匹配持久摘要后重试 rename；不匹配就隔离 |
| rename 后、最终 DB 提交前 | final 仍对应 verified staging intent 时，重验 hash 并补最终 DB 事务；不重写事实/序号 |
| 最终事务提交失败或进程退出 | SQLite 回滚到前态；按上一行使用持久 intent 收敛，不删除 final |
| 最终 DB 提交成功后退出 | 启动重验；一致则恢复引用，不一致则 `recovery_required` 并阻止读取/执行 |
| DB row 指向缺失/损坏文件 | 保留 DB/文件证据，标记异常，不以 Cloud ACK 或重新录制覆盖旧引用 |
| file 无 DB row | 隔离 orphan、登记人工恢复；M4.2 不自动清理任何原始视频 |

本设计不声称数据库与文件系统具有同一原子事务，也不通过两阶段提交模拟。损坏文件、恢复失败或缺少期望摘要时，选择停止使用并留证；生产保留/删除政策另行批准。

### F. 幂等、重试、收据与故障隔离

- 按 M4.1 对完整事件 envelope 做严格白名单与规范化，保存最终 UTF-8 内容和 SHA-256 fingerprint。字段排序、等义 UTC 表示等规则复用 `docs/contracts/cloud-edge-sync-v1.md`，不能另定义 Cloud 协议。
- 收到重复同命令/事实时比较 scope、ID、sequence 与 fingerprint；同内容沿用原结果，异内容保留 original 并将受影响流标记异常。
- `LocalEventOutbox` 对每 Assignment 只发送头部未确认事实，不同 Assignment 可独立进行。成功仅凭匹配的结构化收据；Cloud 游标可做对账线索，不能清理本地 Outbox。
- 429 尊重有效 `Retry-After`；瞬态失败采用有界指数退避+抖动。每轮预算耗尽暂停快速发送但保留队列。永久 4xx/完整性冲突进入 `recovery_required` 或人工处理，不修改 envelope/跳序。
- health/diagnostic 聚合 pending 数量、最老 pending、各流头序号、`safety_hold` 与 open recovery 数，不输出 token、完整事件、用户信息或原始路径。

隔离 profile 的 P01–P10 仅用于开发/测试：P01 连接 2 秒，P02 总请求 5 秒，P03 初始退避 1 秒，P04 上限 30 秒，P05 ±20%，P06 首次之后至多 3 次或 30 秒先到，P07 有效对账/显式恢复/60 秒冷却探测后才重置，P08 每 Assignment 100 件或最老 300 秒告警，P09 正常 15 秒并在网络恢复时合并立即对账，P10 不可恢复缺口挂起且单次人工操作 300 秒后仍挂起。P04 的 `Retry-After` 即便超过本轮 budget 也要尊重；预算耗尽保留后续时机。任何配置不得成为生产默认。

### G. 离线、取消与恢复顺序

启动恢复按以下顺序运行：加载明确数据目录与 Schema → 文件账本对账 → 命令/cursor 连续性检查 → Outbox/Assignment 账本检查 → 恢复 hold/recovery 记录 → 仅对可证明安全的已接单状态恢复 worker。恢复扫描期间 readiness=false，不启动可能引用未验证文件的任务。

普通断网、凭据自然过期和仅撤钥只暂停 CloudAdapter，不清除已接单本地资格；未接单 Assignment 仍等待有效控制流。单个 401 不区分到期/撤销/停用，也不产生 `safety_hold`。MockCloudAdapter 只能注入经验证的 Node disabled 或可信本地停机语义，不声称存在生产通知通道。

应用取消命令时，Inbox、Task/Assignment 的 cancellation gate、cursor 同事务。尚未开工任务立即失去开工资格；运行任务收到 cooperative stop 请求并保存 checkpoint。只有执行器证明确实安全停下，状态提交后才产生 outcome=`stopped_by_cancel` 的终态 Outbox。取消之前已产生的事实、取消之后合法迟到的事实以及待确认 Outbox 都保留。M4.1 中 Cloud 合法终态优先、取消事实不回滚 Cloud projection 的服务器侧裁定不在 Edge 实现。

`safety_hold` 与任务取消是两个不同因果。hold 会阻止所有新开工，要求在运行任务的安全检查点暂停；不能伪造 `stopped_by_cancel`。解挂需追加可审计 actor reference、时间、原因且验证恢复条件。M4.2 测试以显式测试 operator context 演练；正式操作者身份、权限来源和 UI 留后续安全审查。

### H. 运行配置和诊断面

隔离运行 profile 由显式 `EDGE_DATA_DIR`、SQLite profile、MockCloudAdapter、FakeClock/FakeNetwork 和 DeterministicWorker 组成；文件/数据库目录不会落入 Cloud `var/` 或开发者 repo。迁移命令与 server command 分开。运行期发现新库但未初始化时只报 not-ready；不在 web startup 自动跑迁移。

最小 health/readiness/diagnostics 在隔离 profile 仅监听 loopback：存活状态独立于 Cloud 网络，ready 检查 Schema 与数据卷，diagnostics 只读且脱敏。此 endpoint 不是 Venue Console 或生产控制面。具体场馆 LAN 绑定、身份认证、TLS 和现场运维入口仍待批准。

数据库里只保存 Node ID 与必要 scope ID，不保存 EdgeCredential 明文；凭据由未来明确的 SecretProvider/OS secret store 注入，并禁止出现在日志/诊断。M4.2 Mock 不需真实令牌。生产 secret store、轮换/投递是另一个安全边界。

### I. M4.1、Cloud、M1–M3 兼容性

- D1–D5 由本 Change 的本地行为 Delta 落实；不重定义 v1 command/event JSON、8192-byte 信封、50/page、序号或 ACK 语义。
- Cloud 是 TrainingSession/Task/Assignment、取消和授权正式权威。Edge 保存 local command receipt、本地运行状态和事实，不直接更新 Cloud 状态。
- Inbox/outbox/本地 cursor 不写 Cloud Database；不新增 Cloud API/OpenAPI/migration 或修改六份 Cloud 主规格。
- Event receipt、local file publication、M3 upload, cloud asset ready 和 read grant 独立。M4.2 仅本地 file record；M4.4 仍需测试 M1–M7 上传/续传。
- M4.2 隔离 Edge tests 与现有 Cloud CI 分开识别；现有 Cloud CI 结果只代表 M1–M3 兼容基线，不作为 Edge runtime 运行证明。

### J. 隔离测试与故障注入

本 Change 的设计测试使用持久 SQLite 数据文件、持久临时/最终文件目录、可注入 clock/network、MockCloudAdapter 和合成 payload；独立子进程重启时复用相同数据目录。测试核心场景列入 Tasks 验收矩阵，包括：干净/重复初始化、Schema 升级、命令提交前/后 ACK 重启、接单与 Outbox 原子性、同 ID 重试/异参、Assignment 序号、丢回执、每个文件崩溃窗口、执行中重启、hold 重启保持、取消后迟到事实、预算耗尽、recovery_required 人工恢复、Assignment 隔离及无公网 health。

M4.2 验收到隔离适配器边界即止。无 Cloud 服务、无两套真实进程 HTTP 联调、无摄像头/GPU、无生产环境配置或数据；M4.4 另绑定真实提交 SHA 与网络集成证据。

## Risks / Trade-offs

- **SQLite 单写入者和单节点特性** → 把 M4.2 profile 限制为单 Edge Runtime 应用；出现多独立写进程/现场运维证据后评估 PostgreSQL，不宣称 SQLite 已获生产批准。
- **WAL/文件卷掉电和硬件缓存行为未知** → 选择 `synchronous=FULL`，每个发布窗口故障注入；目标现场磁盘的断电耐久仍需硬件验收。
- **文件 rename 与数据库提交不能原子化** → 持久 staging intent、hash、不可变路径、恢复扫描；任何不确定文件隔离且不自动删除原件。
- **Cloud 接口当前不存在** → MockCloudAdapter 对照签认契约行为；M4.2 不把模拟结果报为 M4.3/M4.4 完成。
- **生产 Redis 许可/运维与本地事实层重叠** → 首片不用 Redis；未来启用前按确切版本及许可证审查实际必要性。
- **安全通知不可达** → 只处理可信验证的测试/本地来源；不从断网或 401 推断停用，生产远程通知单独评审。
- **恢复扫描耗时或发现损坏** → readiness 保持 false；分 Assignment/文件隔离诊断，恢复失败时保留整个原目录供人工处置。
- **操作者身份/访问策略未批准** → diagnostics loopback、只读、脱敏；解挂 API 与正式授权集成不得暴露为场馆 LAN 控制面。

## Migration Plan

本 Change 为提案，不实施迁移或部署。后续 Apply 若获单独授权：

1. 在 `services/edge-runtime/` 创建独立 package、SQLite profile、Schema 初始 revision 与显式初始化/升级入口，不改 Cloud Alembic 环境。
2. 对全新临时目录跑初始化、重复初始化与版本升级/失败演练；服务启动只验证已初始化 Schema。
3. 逐步接入 Inbox/cursor、Task/Assignment、Outbox、FileRecord、SafetyHold/RecoveryRecord 的事务接口，再加 adapter/worker/clock injection。
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
