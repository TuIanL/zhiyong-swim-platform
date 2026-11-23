# Tasks

本任务清单是后续独立授权 Apply 的实施与验收计划，不代表本轮已经实现或执行测试。所有隔离配置仅用于普通 CPU、本地 SQLite 文件和 Mock 适配器；生产数据库、凭据入口、数据保留与 LAN 运维策略仍须另行批准。

## 1. Edge 应用骨架与隔离运行入口

- [ ] 1.1 在 `services/edge-runtime/` 建立独立可安装/启动的应用包、独立依赖锁、配置读取和 CLI；启动只校验 Schema，不在启动期间自动建库或迁移；以空 checkout 和显式测试 `EDGE_DATA_DIR` 启动/退出演练及依赖清单检查验收。
- [ ] 1.2 定义 Edge 自有 Domain/Repository、Unit of Work、`CloudAdapter`、Clock、Network 与 Worker 接口，并提供确定性 `MockCloudAdapter`/Worker；运行接口契约单测，确认 Edge 不导入 `services/cloud`、Cloud ORM/Base 或 Cloud Alembic 环境。
- [ ] 1.3 提供仅 loopback 的最小 health/readiness/只读脱敏 diagnostics；通过无公网子进程检查，证明 Cloud 不可达时本地 API 有响应、数据卷或 Schema 不可用时 readiness 为 false，输出不含凭据、完整事件或原始路径。

## 2. 数据目录、SQLite 与版本化 Schema

- [ ] 2.1 实现显式 `EDGE_DATA_DIR` 布局、目录权限/路径校验、独立 SQLite 文件与 Edge 自有 SQLAlchemy/Alembic 配置；初始化和启动校验 canonical root、staging/objects 同卷和独立 migration history，不修改 Cloud 依赖或迁移。
- [ ] 2.2 实现显式 init/upgrade 命令和 OS 锁接入；旧库先经 SQLite Backup API 得一致快照，再在候选库升级/验证/受控原子切换；以 T-01、T-02、T-03、T-41、T-42 验证重复 init 保留数据、候选失败保护及中断恢复，补齐初始化/恢复说明。
- [ ] 2.3 为本地账本实现外部 Cloud ID、唯一约束、索引、Schema 版本及事务不变量；Schema 验证包含 `integrity_check`、`foreign_key_check`、revision 与数据不变量，并在 SQLite 重开后核对原 Inbox/Outbox/序号不变。
- [ ] 2.4 建立单例 `LocalRuntimeIdentity`（runtime_instance_id、tenant/site/node、initialized_at、绑定时 schema_version、identity_state）；用 T-21/T-22 验证同 Node 凭据轮换复用原账本、不同 scope 不 ready 且不读/发旧 Outbox、不改绑定。
- [ ] 2.5 用 OS advisory lock 独占同一 `EDGE_DATA_DIR` 的 Runtime、初始化和升级；两个独立进程/初始化器竞争及进程强制退出后运行 T-23–T-25，验证只授予一个运行权、初始化/升级互斥、内核释放死进程锁。

## 3. Command Inbox 与下发连续游标

- [ ] 3.1 对 CloudAdapter 返回的分页结构/through 做页级预检，再对每条原始命令按 M4.1 验证后保存规范信封/fingerprint；命令 Inbox、命令效果与 cursor 同事务提交，验证提交前崩溃不留半账本（T-04）。
- [ ] 3.2 实现命令重复接收幂等、同 ID/序号异内容冲突留证，以及提交后 ACK 响应丢失时从持久 cursor 重发相同水位；以子进程在持久接收后、ACK 前退出并恢复验证（T-05），并注入丢失 ACK 验证不重复应用命令效果（T-10）。
- [ ] 3.3 实现 `round_through` 固定上界持久化，未追平不得换新水位；逐页验证 `next_after` 与本页连续命令尾部及 round 上界一致，空页不推进；对乱序分页、重复页、缺口及重启恢复测试，并核对 ACK target 不超过本地连续 applied cursor（T-44）。
- [ ] 3.4 按 8192 UTF-8 字节/命令、50 命令/页、schema_version=1、重复键/字段闭集、UUID/UTC/安全整数/方向/载荷规则完成严格 validator；逐项运行 T-26–T-32，验证非法 N 阻止后缀和 ACK 越位，并在 Spec/M4.1 契约样例间做字段对照。

## 4. 本地 Task、Assignment 与执行门槛

- [ ] 4.1 持久化 Cloud `cloud_task_status`、独立 `cloud_task_version`/`cloud_projection_revision` 与 Edge LocalTask/Assignment phase、恢复状态、run ID/checkpoint；Reconcile 只单调应用新投影，快照不改写 Edge 执行事实/Outbox（T-45）。分开表示 Inbox applied、ACK 投递、业务接单和实际开工，以 T-06 验证接单/outbox 同事务且 ACK 不开工。
- [ ] 4.2 实现固定水位追平、未取消且无 active safety hold 的业务接单门槛，以及独立的执行门槛；验证未追平/已取消/已挂起均不接单或开工，接单后断网仍能保留本地状态。
- [ ] 4.3 为确定性测试 Worker 实现持久检查点及进程重启恢复/转 `recovery_required`；使用相同数据目录杀停并重启子进程，验证既有 Assignment 恢复且不从空任务或未证明幂等的副作用重新开始（T-14）；同步更新运行状态文档。
- [ ] 4.4 将取消 gate 与 Worker 执行资格纳入相同 Assignment 数据库串行化边界；用两个独立连接交错提交 T-35，验证取消先提交则拒绝开工、开工先提交则同 run identity 接受安全停止且不伪造 `stopped_by_cancel`。

## 5. Outbox、Assignment 序号与回执幂等

- [ ] 5.1 实现每 Assignment 独立的连续序号和不可变规范事件信封；事实、序号、`event_id` 与 Outbox 必须同事务提交，发送元数据与信封分离；验证连续编号及两个 Assignment 互不争用序号（T-09）。
- [ ] 5.2 实现同事实重复提交返回原事件身份/序号、同 ID 异内容保留原件并转 `recovery_required`；以重复提交与冲突注入覆盖（T-07、T-08），并逐字段检查原 envelope 重试前后字节/fingerprint 不变。
- [ ] 5.3 实现收据按认证 scope、`event_id`、`assignment_id`、sequence、disposition 精确匹配；模拟响应丢失、HTTP 200 但收据错配、重复收据及正确收据，验证只有正确收据销账且重启后可重投原 envelope（T-10）。
- [ ] 5.4 以两个独立 SQLite Connection/Session 并发提交同一 Assignment 的不同事实和同一事实重放；运行 T-33/T-34，验证唯一连续序号、无重复业务效果、失败方读取获胜事务原结果及有界 `SQLITE_BUSY` 重试。

## 6. CaptureFact 与本地 FileRecord

- [ ] 6.1 实现 `LocalCaptureFact` 与 `LocalFileRecord` 状态机；分别持久提交 `staging_intent`、`staged_verified`、rename/fsync 后的 `published` 和最终业务事务的 `available`；逐态验证引用门槛及本地 `available` 不生成 Cloud Asset/ready 事实（T-46）。
- [ ] 6.2 实现同一持久文件系统内唯一 staging 文件、flush/fsync、摘要确认、原子 no-replace 发布及文件/源目标父目录同步；随后单独提交 `published`，最终事务再写 CaptureFact/Outbox/sequence 并置 `available`；验证现存 final 绝不覆盖，发布失败保留原件。
- [ ] 6.3 保持事件 Outbox 与 M3 媒体上传/授权状态分离；测试事件收据不删除或上传原片、不产生 Cloud `MediaObject`/ready/grant，并记录 M4.4 媒体接口边界。
- [ ] 6.4 使用 dirfd/no-follow 或等价路径安全机制拒绝绝对路径、`..`、符号链接、根目录替换及越界引用；运行 T-39 检查不存在对数据根外文件的读取或覆盖。

## 7. 文件与数据库崩溃补偿

- [ ] 7.1 实现每次启动必需的 Schema/Identity/活动 FileRecord/未结恢复/Assignment checkpoint/Inbox-Cursor-Outbox 连续性/Hold/目录关系扫描；readiness 在扫描完成前保持 recovering，不让 Worker/Dispatcher 使用未验证记录。
- [ ] 7.2 为临时写入、rename 前、rename 后 `published` 提交前、`published` 提交后最终 `available` 提交前及最终提交后注入崩溃；复用原目录验证幂等恢复及 CaptureFact/Outbox/sequence 至多一次，覆盖 T-11–T-13、T-46。
- [ ] 7.3 实现孤立文件和孤立数据库记录登记、隔离与人工恢复证据；缺失/损坏文件或孤立文件测试验证原始字节和数据库证据均保留，不自动覆盖、引用或删除。
- [ ] 7.4 注入 ENOSPC、fsync/SQLite IO 错误、EXDEV、目标已存在和符号链接替换；运行 T-36–T-40，验证未生成可引用 CaptureFact/Outbox、原始字节保留、跨卷不 copy-delete、故障原因可以持久或在可写后幂等补录。
- [ ] 7.5 实现历史文件分级核验（未完成/非 clean shutdown/open recovery/元数据变化完整 hash；正常历史项快速 metadata 检查并安排完整巡检）；运行 T-43 记录文件数、总大小、scan/hash/recovery/DB/readiness 耗时且不设生产 SLA。

## 8. 离线恢复、取消与 safety_hold

- [ ] 8.1 实现按原因独立持久的 Node 级 `LocalSafetyHold` 与针对 hold_id 的审计解挂；断网/自然过期/仅撤钥/原因不明 401 不触发，只有可信原因触发，T-15 验证重启保持且解除一项不解除其他项。
- [ ] 8.2 实现取消命令的持久 cancellation gate；未开工任务取消后禁止开工，运行任务需保存 checkpoint 并证明安全停止后才提交 `stopped_by_cancel`；测试未经停止证明不得生成该事实。
- [ ] 8.3 保留已取消 Assignment 的离线迟到事实及原 Outbox，确保可补投但不会重开任务、改写 Cloud 终态或生成新接单；以取消后事实补投测试验收（T-16），并与 M4.1 的 W1 语义逐项对照。
- [ ] 8.4 实现游标缺口、账本冲突、坏摘要、不可解释执行状态的持久 `recovery_required` 与受控人工处置；测试恢复原因跨重启保留、人工动作超时仍挂起、恢复后保留原信封/事实（T-18）。
- [ ] 8.5 将 Node SafetyHold 和 Assignment RecoveryRecord 作用域分开；用 T-15/T-18 验证 Assignment 故障只阻断本分配、Node 任一有效 hold 阻止所有新开工、每个原因独立解除且受影响外的健康分配可继续。

## 9. P01–P10 隔离参数与故障隔离

- [ ] 9.1 以显式隔离 profile 实现 P01–P10 的连接/请求超时、有界退避、jitter、重试预算、Retry-After、冷却探测、积压告警、对账节奏和人工等待上限；FakeClock/固定随机种子验证精确边界，并断言这些值不作为生产默认。
- [ ] 9.2 对每 Assignment 独立推进待发、重试和 `recovery_required`；一个流达到重试预算或永久冲突时保留原事件并允许另一健康 Assignment 继续；以多流注入测试覆盖（T-17、T-19）。
- [ ] 9.3 MockCloudAdapter 支持可控断网、丢 ACK、乱序、重复、拒绝、长 Retry-After、错配收据和同节点凭据恢复情形；按 S1-R1–R4 编写匹配/不匹配收据用例，补充 adapter 场景说明。

## 10. 集成验收、追溯与交付文档

- [ ] 10.1 组合独立子进程、持久 SQLite/文件目录、FakeClock/FakeNetwork、MockCloudAdapter、OS lock 和确定性 Worker，运行 T-01–T-46 全套隔离矩阵；验证无公网 health/本地持久化（T-20），记录真实测试 checkout SHA、结果及 M4.2/M4.3/M4.4 边界。
- [ ] 10.2 更新 Edge Runtime README、隔离运行与人工恢复指南，明确身份绑定/轮换、单实例锁、命令校验、各状态机、升级保护、文件路径安全/完整性策略、初始化/升级/诊断命令及生产待决项；从干净环境逐条照文档执行，不要求 Cloud 或真实场馆硬件。
- [ ] 10.3 完成全模块兼容检查：`git diff --check`、OpenSpec strict、Cloud 源码/六份 Cloud 主规格/OpenAPI/迁移/Cloud CI 未变更检查；报告把 Cloud 既有 M1–M3 回归与 M4.2 Edge 运行验收分开。

## Requirement / Scenario → Task → Test 验收矩阵

### M4.2 Spec Delta Requirement 对照

本 Spec 使用 `EPR-01` 至 `EPR-09` 作为本地追溯简称，顺序对应 `specs/edge-runtime-persistence/spec.md` 中九项 Requirement。测试均为后续 Apply 的计划，当前 Propose 阶段未执行。

| M4.2 Requirement | 场景 | Task | Test/验收证据 |
| --- | --- | --- | --- |
| EPR-01 身份、独立数据边界、Schema/单实例 | 空目录、重复初始化、绑定/轮换/错绑、锁竞争、升级失败 | 2.1–2.5 | T-01–T-03、T-21–T-25、T-41–T-42 |
| EPR-02 严格命令 Inbox/cursor/ACK | 原子提交、协议边界、非法中间命令、固定轮次、页尾 `next_after` 和 ACK 分离 | 3.1–3.4 | T-04、T-05、T-10、T-26–T-32、T-34、T-44 |
| EPR-03 Cloud Task 快照/投影版本与 Edge 接单/执行状态机 | 固定水位、Cloud Projection Revision 重放/乱序、取消、接单同事务、Worker 恢复 | 4.1–4.4 | T-06、T-14、T-16、T-35、T-45 |
| EPR-04 事实/不可变 Outbox/并发序号 | 重复事实、同 ID 冲突、连续序号、迟到事实、独立连接竞争 | 5.1–5.4、8.3 | T-07–T-10、T-16、T-33 |
| EPR-05 Assignment 投递隔离 | 重试预算耗尽、永久拒绝、另一分配继续 | 9.2–9.3 | T-17、T-19；各 Assignment 独立序号/状态与保留事件 |
| EPR-06 文件阶段、`published` 持久提交、路径安全及登记后可引用 | 暂存/发布/available、发布崩溃、ENOSPC/fsync/EXDEV、路径替换、缺失/损坏/孤立 | 6.1–6.4、7.2–7.4 | T-11–T-13、T-36–T-40、T-46 |
| EPR-07 启动恢复、投影版本、Schema 保护与分级扫描 | 投影版本重启、候选升级、切换及 FileRecord 阶段中断、文件 hash/性能 | 2.2、4.1、7.1–7.5、8.4 | T-03、T-14、T-18、T-41–T-46 |
| EPR-08 多原因 Node safety_hold 与局部恢复阻断 | 断网/401、可信停用、多个原因聚合、Assignment 故障隔离、取消安全停止 | 8.1–8.5 | T-15、T-16、T-18、T-35 |
| EPR-09 readiness 与脱敏诊断 | 无公网、身份错配、扫描中、库/文件不可用、hold/局部恢复影响 | 1.3、8.5、10.1 | T-20、T-22、T-43 |

### M4.1 Requirement / Scenario → M4.2 行为 → Task → Test → 责任

每行都标明承担边界：M4.2 落实 Edge 本地持久行为；M4.3 实现 Cloud API、Cloud Inbox/事务/授权和正式回执；M4.4 承担真实两个进程网络、部署联调及媒体上传往返。矩阵中的测试只证明本地 Mock/隔离环境，不替代后两阶段。

| M4.1 Requirement / Scenario | M4.2 对应行为 / Spec | Task | Test | 责任边界 |
| --- | --- | --- | --- | --- |
| A1：持久接收命令 | Inbox、效果、cursor 同一事务（EPR-02） | 3.1 | T-04 | M4.2 本地原子保存；M4.3 提供真实下发；M4.4 验证网络往返 |
| A2：持久进度后 Command ACK | 只 ACK 已提交连续 cursor（EPR-02） | 3.1–3.2 | T-05、T-10 | M4.2 ACK 客户端行为；M4.3 ACK 服务端；M4.4 双进程验证 |
| R3：Inbox、命令效果和下发游标原子 | 事务前后全有或全无（EPR-02） | 3.1 | T-04 | M4.2 Edge DB；M4.3 Cloud 事务不在本变更；M4.4 联调 |
| S3.1：提交后 ACK 丢失/重发 | 重启读取已提交 cursor 并幂等重发（EPR-02） | 3.2 | T-05、T-10 | M4.2 本地重放；M4.3 提供 ACK 接口；M4.4 网络故障 |
| S3.2：提交前崩溃不得 ACK | 回滚效果与 cursor（EPR-02） | 3.1 | T-04 | M4.2 本地事务；M4.3 不涉及；M4.4 可做进程级补充 |
| R4：命令排序、重放与恢复 | 持久 cursor、固定水位、重复幂等（EPR-02/07） | 3.2–3.3 | T-04、T-05、T-10 | M4.2 Edge 排序；M4.3 Cloud 命令序列；M4.4 乱序网络 |
| S4.1：乱序/分页命令 | 只应用连续有序命令（EPR-02） | 3.3 | T-04 | M4.2 消费端；M4.3 分页供给；M4.4 网络乱序 |
| S4.3：重放后游标恢复 | 从持久账本补缺，不把远端 ACK 当本地完成（EPR-02/07） | 3.2–3.3 | T-05、T-10 | M4.2 本地恢复；M4.3 对账 API；M4.4 双端恢复 |
| R5：离线任务与 Assignment 隔离 | 已接单继续本地事实；失败分配不阻塞其他流（EPR-03/05） | 4.2、9.2 | T-14、T-19 | M4.2 本地执行/隔离；M4.3 云端调度；M4.4 离线往返 |
| S5.1：断网后已接单任务恢复 | checkpoint 持久化，重启恢复或人工挂起（EPR-03/07） | 4.3 | T-14 | M4.2 确定性 Worker 基座；ES-05 完整 Worker；M4.4 网络恢复 |
| S5.2：单 Assignment 错误不连坐 | 独立发送游标与恢复状态（EPR-05） | 9.2 | T-19 | M4.2 本地队列隔离；M4.3 Cloud 独立接收；M4.4 联调 |
| R6：取消必须阻止未开工任务 | 持久 cancellation gate，取消后不接单/开工（EPR-03/08） | 4.2、8.2 | T-06、T-16 | M4.2 消费/门槛；M4.3 取消命令权威源；M4.4 竞态验证 |
| S6.3：取消后不可新开工 | 执行前复核取消与 hold（EPR-03/08） | 4.2、8.2 | T-06、T-16 | M4.2 本地门槛；M4.3 正式取消；M4.4 取消竞态 |
| R7：凭据失效与同节点恢复 | 401/自然过期暂停同步，不丢本地状态（EPR-08） | 8.1、9.3 | T-15、T-20 | M4.2 本地离线语义；M4.3 credential 生命周期；M4.4 真实换钥流程 |
| S7.1：自然到期/撤钥行为 | 不因通用认证失败停止已接单任务（EPR-08） | 8.1 | T-15 | M4.2 不猜测撤钥原因；M4.3 授权响应；M4.4 实网演练 |
| S7.2：同 Node 更新凭据后恢复 | 保持原账本/Assignment 绑定 Node，hold 不自动解（EPR-08） | 8.1、9.3 | T-15 | M4.2 本地复用语义；M4.3 重新签发；M4.4 双进程认证恢复 |
| C1：普通断网 | 本地 health、已接单事实与 Outbox 持续可用（EPR-05/09） | 1.3、9.2 | T-19、T-20 | M4.2 本地可用；M4.3 不提供时亦可验证；M4.4 真实断网 |
| C2：凭据自然过期/仅撤钥 | 暂停云同步，不自行停止本地任务/清账（EPR-08） | 8.1 | T-15 | M4.2 本地规则；M4.3 身份/授权；M4.4 真实认证失效 |
| C3：已验证停用 | 持久 `safety_hold`、阻止新开工并保留检查点（EPR-08） | 8.1 | T-15 | M4.2 仅 Mock 验证触发语义；M4.3 权威节点状态；M4.4 安全通知集成 |
| C4：重启不得自动解除/显式解挂 | hold 跨重启、显式操作者/原因/时间审计（EPR-08） | 8.1、8.4 | T-15、T-18 | M4.2 本地状态与测试 operator；M4.3 身份来源不在范围；M4.4 现场安全集成 |
| S1-R1：收据认证 scope 匹配 | 收据 scope 与本地请求 Node/资源归属一致（EPR-04） | 5.3、9.3 | T-10 | M4.2 客户端拒绝错配；M4.3 生成/验证收据；M4.4 网络集成 |
| S1-R2：event_id 匹配 | 只能确认对应原 event_id（EPR-04） | 5.3 | T-10 | M4.2 本地匹配；M4.3 receipt API；M4.4 双端往返 |
| S1-R3：assignment_id 匹配 | 不能跨 Assignment 销账（EPR-04/05） | 5.3、9.2 | T-10、T-19 | M4.2 本地作用域校验；M4.3 云端作用域；M4.4 联调 |
| S1-R4：sequence/disposition 匹配 | 错序或错误处置不得确认（EPR-04） | 5.1、5.3 | T-09、T-10 | M4.2 本地精确确认；M4.3 收据构造/业务处置；M4.4 网络验证 |
| W1.1：取消前离线事实待补投 | 原 Outbox 持久到匹配收据（EPR-04） | 5.1、8.3 | T-16 | M4.2 保留/补投；M4.3 接收并合并；M4.4 联调 |
| W1.2：取消事实与迟到事实有序 | Assignment 序号连续且原 envelope 不变（EPR-04） | 5.1、8.3 | T-09、T-16 | M4.2 本地编号；M4.3 云端排序/裁决；M4.4 乱序网络 |
| W1.3：Cloud 已取消仍保存 Edge 事实 | 保留迟到事实但不改 Cloud 终态（EPR-04） | 8.3 | T-16 | M4.2 Edge 事实保真；M4.3 合法终态裁决；M4.4 双端冲突验证 |
| W1.4：取消后事件不得重开任务 | 只投递事实，不自动接单或改本地取消门槛（EPR-03/04） | 4.2、8.3 | T-06、T-16 | M4.2 本地 gate；M4.3 云端不重开；M4.4 联调 |
| W1.5：丢收据后原事件重试 | 使用原 event_id/sequence/content（EPR-04） | 5.2–5.3 | T-07、T-10 | M4.2 原件重试；M4.3 幂等收据；M4.4 丢响应网络演练 |
| W1.6：收据匹配后才确认 | receipt 精确作用域匹配后更新投递元数据（EPR-04） | 5.3 | T-10 | M4.2 本地销账条件；M4.3 真实收据；M4.4 双端验证 |
| W1.7：单流恢复不丢事实 | 缺口进入人工恢复，其他 Assignment 可继续（EPR-05/07） | 8.4、9.2 | T-18、T-19 | M4.2 Edge 保留/隔离；M4.3 云端补收/对账；M4.4 跨进程恢复 |
| W3.1：复合冲突保留 Edge 原事实 | 同 ID 异内容保留原 envelope/证据并挂起受影响流（EPR-04/07） | 5.2、8.4 | T-08、T-18 | M4.2 本地事实保留；M4.3 Cloud 冲突回执/投影；M4.4 复合竞态 |
| M1：媒体上传建立 | 不建上传会话；FileRecord 只登记本地文件（EPR-06） | 6.1、6.3 | T-11–T-13 | M4.2 本地登记；M4.3 既有 M3 服务；M4.4 媒体上传集成 |
| M2：媒体分片/续传 | 不实现 Cloud 分片协议；只保证原片本地不丢（EPR-06） | 6.2–6.3 | T-11–T-13 | M4.2 本地文件恢复；M4.3 既有 M3 API；M4.4 续传测试 |
| M3：对象完整性验证 | 本地 SHA-256 不替代 Cloud MediaObject 校验（EPR-06） | 6.1–6.2 | T-11–T-13 | M4.2 本地摘要；M4.3 Cloud 端对象校验；M4.4 端到端媒体校验 |
| M4：对象 Ready 发布 | 本地文件 ready 不等于 Cloud Asset ready/可读（EPR-06） | 6.2–6.3 | T-13 | M4.2 本地引用门槛；M4.3 既有 Cloud 发布/授权；M4.4 双端验证 |
| M5：授权媒体读取 | 不实现 Cloud read grant/URL/权限（EPR-06） | 6.3 | 边界审查，无媒体授权用例 | M4.2 明确不含；M4.3 既有授权；M4.4 验证真实读取链路 |
| M6：媒体传输故障/续传 | 仅注入本地写入、rename、DB 崩溃，不替代 M3 网络故障测试（EPR-06） | 7.1–7.3 | T-11、T-12、T-13 | M4.2 本地补偿；M4.3 M3 API 行为；M4.4 网络/续传故障 |
| M7：媒体与训练任务关联 | 仅保留本地外部关联 ID，不创建/覆盖 Cloud Session/Asset（EPR-06） | 6.1、6.3 | T-13、边界审查 | M4.2 本地索引；M4.3 Cloud 权威关联；M4.4 真实业务链路 |

### P0 / W1–W4 Requirement / Scenario → Task → Test → 责任追溯

下列场景的行为 Owner 均为 M4.2 Edge 本地账本；M4.3 仅负责真实 Cloud 授权/命令来源、服务端游标/回执及 Cloud 侧并发，M4.4 才验证真实双进程网络、重认证/掉线及既有 M3 媒体往返。Mock 测试不代替后续阶段。

| Review 项 | Requirement / Scenario | Task | Test | M4.2 / M4.3 / M4.4 责任 |
| --- | --- | --- | --- | --- |
| P0-01 | EPR-01：同 Node 重启和 Credential 轮换继续复用原 RuntimeIdentity/账本 | 2.4 | T-21 | M4.2 本地身份与隔离 Mock；M4.3 提供 credential 作用域；M4.4 真实同 Node reissue |
| P0-01 | EPR-01：不同 Tenant/Site/Node 复用目录时 fail closed、不读/发旧 Outbox | 2.4 | T-22 | M4.2 身份门；M4.3 认证来源；M4.4 双节点认证边界 |
| P0-01 | EPR-01：两个 Runtime 竞争同目录只有一个拿到 OS 锁 | 2.5 | T-23 | M4.2 独占锁；M4.3 不涉及；M4.4 验证部署不共享运行卷 |
| P0-01/W3 | EPR-01/EPR-07：init/upgrade 与运行服务互斥 | 2.5 | T-24 | M4.2 同锁契约；M4.3 不涉及；M4.4 按实际部署约束补充 |
| P0-01 | EPR-01：异常退出后锁由 OS 释放且残留锁文件不永久阻塞 | 2.5 | T-25 | M4.2 进程锁；M4.3 不涉及；M4.4 仅部署环境检查 |
| P0-02 | EPR-02：单命令 UTF-8 8192 字节边界 | 3.4 | T-26 | M4.2 validator；M4.3 返回符合契约的 command；M4.4 实际 HTTP 边界 |
| P0-02 | EPR-02：每页 50 条通过、51 条整页拒绝且零应用 | 3.4 | T-27 | M4.2 页预检；M4.3 分页实现；M4.4 真实分页网络 |
| P0-02 | EPR-02：重复 JSON Key/未知字段/非法 UUID 拒绝 | 3.4 | T-28 | M4.2 严格解析；M4.3 契约字段；M4.4 对接验证 |
| P0-02 | EPR-02：不支持 Schema/方向、非安全整数、非法 UTC 拒绝 | 3.4 | T-29 | M4.2 严格 validator；M4.3 契约响应；M4.4 跨端错误映射 |
| P0-02 | EPR-02：第 N 条非法时合法前缀可留、N 及后缀不应用、Cursor 不越位 | 3.4 | T-30 | M4.2 逐命令事务；M4.3 命令序号；M4.4 丢包/重放验证 |
| P0-02 | EPR-02：固定 `round_through` 跨进程重启原值恢复 | 3.3–3.4 | T-31 | M4.2 持久轮次；M4.3 提供稳定上界；M4.4 网络轮次恢复 |
| P0-02 | EPR-02：前缀不重做、非法命令不 ACK、后续命令不越缺口 | 3.2–3.4 | T-32 | M4.2 Cursor/ACK gate；M4.3 Cloud ACK 水位；M4.4 端到端序号恢复 |
| W1 | EPR-04：两个 SQLite 连接并发 append 不重复/不跳 Assignment sequence | 5.4 | T-33 | M4.2 本地事务/唯一约束；M4.3 Cloud 上行锁序独立；M4.4 真实双端流水 |
| W1 | EPR-02/EPR-04：并发重复命令/事实仅一次效果并返回获胜持久结果 | 3.4、5.4 | T-34 | M4.2 本地幂等；M4.3 Cloud 幂等独立；M4.4 请求重放 |
| P0-03/W1 | EPR-03/EPR-08：取消先提交拒绝开工；启动资格先提交则同 run identity 安全停止 | 4.4 | T-35 | M4.2 本地 gate；M4.3 Cloud 终态/取消权威；M4.4 双端竞态验收 |
| W2 | EPR-06/EPR-07：文件写入或 SQLite DB/WAL ENOSPC 不产生可引用事实/Outbox，保留恢复锚点并转正确就绪状态 | 7.4 | T-36 | M4.2 文件/SQLite 恢复；M4.3 不涉及；M4.4 媒体上传异常另验 |
| W2 | EPR-06：文件/父目录 fsync 失败不推进 published/available | 7.4 | T-37 | M4.2 fsync 边界；M4.3 不涉及；M4.4 目标硬件检查不由本用例替代 |
| W2 | EPR-06：EXDEV 禁止 copy+delete、保留 staging 并阻断引用 | 7.4 | T-38 | M4.2 同卷文件流程；M4.3 不涉及；M4.4 生产挂载类型独立评估 |
| W2 | EPR-06：路径穿越、符号链接、硬链接/重复路径归属和根目录替换被拒绝 | 6.4、7.4 | T-39 | M4.2 本地路径边界；M4.3 不涉及；M4.4 部署权限补充验证 |
| W2 | EPR-06：final 缺失/损坏/孤立文件不引用、不覆盖、不删除 | 7.3–7.4 | T-40 | M4.2 文件对账；M4.3 不涉及；M4.4 M3 上传前重新验证 |
| W3 | EPR-01/EPR-07：迁移前/中、DDL 后 revision 写入失败或候选验证失败，原库 revision、业务行、Inbox/Outbox/序号可恢复 | 2.2 | T-41 | M4.2 SQLite upgrade；M4.3 PG schema 独立；M4.4 双端数据库不合并 |
| W3 | EPR-07：原子切换前/后（含 manifest 未完成）退出，重启唯一辨识活动/候选库并保持安全 | 2.2 | T-42 | M4.2 manifest/cutover；M4.3 不涉及；M4.4 不属于网络联调 |
| W4 | EPR-07/EPR-09：混合文件目录启动扫描按分级 hash 策略恢复，报告计数/耗时并在关键扫描结束前不 ready | 7.1、7.5 | T-43 | M4.2 启动扫描/可测策略；M4.3 不涉及；M4.4 可复核但不设生产 SLA |
| P0-02 | M4.1 A1/A2、R4/S4.1/S4.3 → EPR-02：`next_after` 与非空页末命令/固定 `round_through` 一致，空页不推进，异常重启从持久 Cursor 续取 | 3.3 | T-44 | M4.2 页校验/本地游标；M4.3 提供契约分页；M4.4 真实响应/重连联调 |
| P0-03 | M4.1 D1、Sync API/Reconcile 对账规则 → EPR-03/EPR-07：`projection_revision` 幂等单调，独立校验 `task_version` 且不改 Edge 执行事实 | 4.1 | T-45 | M4.2 本地投影账本；M4.3 Cloud 投影产生/版本；M4.4 真实 reconcile/restart |
| W2 | M4.1 D3、W1.1–W1.7 → EPR-06/EPR-07：rename/fsync 后独立提交 `published`；阶段间重启只产生一份 CaptureFact/Outbox/sequence | 6.1–6.2、7.2 | T-46 | M4.2 文件/DB 提交恢复；M4.3 不涉及；M4.4 真实媒体流程另验 |

## 隔离测试编号

| Test | 场景与预期 |
| --- | --- |
| T-01 | 空持久目录首次初始化，建成版本化账本且 readiness 转 ready。 |
| T-02 | 重复初始化不清空或重建任务、Inbox、Outbox、序号及 envelope。 |
| T-03 | Schema 从受支持旧版本显式升级；未知高版本/升级失败不改坏原库并保持 not-ready。 |
| T-04 | 命令事务提交前/提交时终止进程，Inbox 效果与 cursor 同回滚；重启不 ACK 未提交命令。 |
| T-05 | 命令已持久接收但发送 Command ACK 前退出，重启从同一 cursor 发相同 ACK，不重复应用。 |
| T-06 | 业务接单和 `training_task.accepted` Outbox 同事务；事务失败均不可见，只有已接单不代表实际开工。 |
| T-07 | 同一事件/事实重复提交，复用原 `event_id`、sequence 和原 envelope。 |
| T-08 | 已用 ID 再以异参提交，保留原件和冲突证据，目标流进入 `recovery_required`。 |
| T-09 | 每 Assignment sequence 从初始值严格连续；两个 Assignment 互不影响。 |
| T-10 | 丢上行 ACK 后重启可重发原 envelope；HTTP 200/错误 scope/ID/Assignment/sequence/disposition 均不能销账，精确回执可销账。 |
| T-11 | 文件临时写入中崩溃，重启不得引用、不伪造 CaptureFact/Outbox，保留原始字节并登记恢复原因。 |
| T-12 | 文件发布 rename 后、最终 DB 提交前崩溃；按已持久 intent 重验后幂等补偿或人工隔离，不重复分配序号。 |
| T-13 | DB 最终提交后立即退出；重启校验 FileRecord、CaptureFact、Outbox 和文件 hash 后恢复引用，不一致则挂起。 |
| T-14 | 执行中的确定性 Worker 进程重启，按持久 checkpoint 恢复同一 Assignment 或明确转人工状态。 |
| T-15 | `safety_hold` 重启、重认证及网络恢复后保持；401/自然过期/单独撤钥不触发 hold；显式解挂有完整审计。 |
| T-16 | Cloud 已取消后补投离线迟到事实，Edge 原事实保留且不重开任务、不改 Cloud 终态。 |
| T-17 | P06 重试预算耗尽后原始事件、序号、内容和后续受控恢复时机仍存在，不标已送达。 |
| T-18 | `recovery_required` 跨重启保持；人工恢复有审计；等待超时仍挂起且原事实不删除。 |
| T-19 | 多 Assignment 中一个流永久拒绝/缺口时单独隔离，另一个健康流仍可投递/执行。 |
| T-20 | 无公网时本地 health/diagnostics/API 与持久化可用；数据库/文件卷不可用时 not-ready，诊断脱敏。 |
| T-21 | 同一 Tenant/Site/Node 重启及 Credential ID 轮换，使用原 RuntimeIdentity、cursor、Task 和 Outbox 账本，不重初始化。 |
| T-22 | 将 Node B（或不同 Tenant/Site）配置到 Node A 数据目录；readiness 为 identity_mismatch，旧 Task/Outbox 不读取/执行/发送，身份和原数据未改。 |
| T-23 | 两个独立 Runtime 进程并发打开同一 `EDGE_DATA_DIR`；OS 锁只授予一个运行权，另一个在启动 Dispatcher/消费者前失败。 |
| T-24 | Runtime 持锁运行时并发执行 init/upgrade；init/upgrade 无法越过锁，反向升级运行期也不得双开服务。 |
| T-25 | 持锁 Runtime 被 SIGKILL/异常退出后，OS 自动释放锁；残留 lock 文件存在不阻断后续显式恢复启动。 |
| T-26 | 对单条命令测量原始 UTF-8 JSON 字节；8192 字节通过、8193 字节在解析/持久化前拒绝。 |
| T-27 | 50 条命令分页可继续处理；51 条整页拒绝且 Inbox、命令效果、Cursor 均无变化。 |
| T-28 | 逐一注入重复 JSON Key、未知字段、非小写连字符 UUID；均拒绝且产生有界脱敏诊断。 |
| T-29 | 注入 `schema_version` 非整数 1（含布尔值）、错误方向/类型、非 JSON 安全整数及非规范 UTC/显式 null；均不持久化或推进 Cursor。 |
| T-30 | 连续命令 N 前缀合法、N 非法且 N+1 后缀合法；只保留前缀，Cursor/ACK 不超过 N−1，后缀不应用；无法证明兼容安全时流持久为 `recovery_required`，保持同一轮次并等待兼容升级或审计人工恢复。 |
| T-31 | 持久 `round_through` 后在分页中途杀停；重启继续旧上界，未追平前不得获取/保存新上界替换它。 |
| T-32 | 合法前缀重启后不重复应用，非法命令不 ACK，后续序号不越过缺口；验证 ACK attempt/response 与 Inbox applied、Task phase 分离。 |
| T-33 | 两个独立 SQLite Connection 并发提交同 Assignment 两个不同事实；`(assignment_id,sequence)` 唯一连续、无重复效果/空洞，事务外无网络等待。 |
| T-34 | 两个独立会话并发提交同一命令或采集事实；只产生一次效果，未获胜请求读回并返回同一持久 ID/sequence。 |
| T-35 | 两独立连接交错 Worker start-claim 与取消命令；取消先提交则不能开工，start claim 先提交则取消沿同 run identity 请求安全停止，只有真实安全停止才报 outcome。 |
| T-36 | 分别注入 staging/最终目录文件写入 ENOSPC 与 SQLite DB/WAL ENOSPC；无可引用 CaptureFact/Outbox。空间仍可写时持久 intent/RecoveryRecord；DB 无法写时保持 not-ready 并以故障前 intent/文件作为恢复锚点，重开确认账本后在可写时幂等补记；不把未确认提交当成功。 |
| T-37 | 文件 fsync、源/目标父目录 fsync 分别失败；不推进 published/available，不开放引用或覆盖对象，readiness/局部阻断符合扫描策略。 |
| T-38 | staging 与 objects 跨设备或 rename 返回 EXDEV；不 copy+delete，不删源文件，不产生 available FileRecord。 |
| T-39 | `../`、绝对路径、staging/final 符号链接替换、数据根目录替换、越界引用、非预期硬链接及多个业务记录指向同一不可变路径均按策略拒绝；不读取根目录外内容、不覆盖对象。 |
| T-40 | 注入 final 缺失/损坏、DB 行无文件和无 DB 行 orphan；保留原 bytes/DB 证据、禁止引用和覆盖、不自动删除原片。 |
| T-41 | 分别在迁移前、迁移中、DDL 已执行但 revision 写入失败、候选完整性/数据不变量验证失败时中断；活动原库 revision、业务行、RuntimeIdentity、Inbox、Outbox 和序号可重开并恢复，绝不指向候选库。 |
| T-42 | 分别在候选验证后原子切换前、原子替换完成后但 manifest 未更新时崩溃；启动由 manifest、唯一活动路径、revision 和摘要区分旧库/已切换候选，确认一致则审计完成，不一致则 not-ready 并待显式恢复；不得出现不确定活动库或空库。 |
| T-43 | 在含正常 available、staging/未完成、异常退出关联和 orphan 的固定合成文件集上执行启动扫描；记录文件数/总大小/快速扫描、完整 hash、unfinished recovery、DB 查询、readiness 时间并核验分级结果。 |
| T-44 | 覆盖正确尾游标、next_after 小于/大于页尾、超过 round_through、空页、重复页和异常后重启；无效页整页零应用，空页不推进，重启从 last_applied_sequence 重取且不越 ACK。 |
| T-45 | 覆盖更高/相同/更低 projection_revision、相同 revision 异内容、重启持久化，以及 task_version 独立变化/回退；旧投影不覆盖，新投影不改 Edge Assignment/事实/Outbox。 |
| T-46 | 分别在 rename 前、rename/fsync 后但 published 提交前、published 提交后 available 提交前崩溃；重启恢复阶段且最终最多一份 CaptureFact、一条 Outbox 和一个 Assignment sequence。 |

## Workflow follow-up

- 项目负责人审阅并单独授权 Apply 后，才按上述任务开始实现与测试。
- Apply 完成并通过项目验收后，再按 OpenSpec 流程验证和归档本 Change。
