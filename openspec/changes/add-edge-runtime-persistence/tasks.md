# Tasks

本任务清单是后续独立授权 Apply 的实施与验收计划，不代表本轮已经实现或执行测试。所有隔离配置仅用于普通 CPU、本地 SQLite 文件和 Mock 适配器；生产数据库、凭据入口、数据保留与 LAN 运维策略仍须另行批准。

## 1. Edge 应用骨架与隔离运行入口

- [ ] 1.1 在 `services/edge-runtime/` 建立独立可安装/启动的应用包、独立依赖锁、配置读取和 CLI；启动只校验 Schema，不在启动期间自动建库或迁移；以空 checkout 和显式测试 `EDGE_DATA_DIR` 启动/退出演练及依赖清单检查验收。
- [ ] 1.2 定义 Edge 自有 Domain/Repository、Unit of Work、`CloudAdapter`、Clock、Network 与 Worker 接口，并提供确定性 `MockCloudAdapter`/Worker；运行接口契约单测，确认 Edge 不导入 `services/cloud`、Cloud ORM/Base 或 Cloud Alembic 环境。
- [ ] 1.3 提供仅 loopback 的最小 health/readiness/只读脱敏 diagnostics；通过无公网子进程检查，证明 Cloud 不可达时本地 API 有响应、数据卷或 Schema 不可用时 readiness 为 false，输出不含凭据、完整事件或原始路径。

## 2. 数据目录、SQLite 与版本化 Schema

- [ ] 2.1 实现显式 `EDGE_DATA_DIR` 布局、目录权限/路径校验、独立 SQLite 文件与 Edge 自有 SQLAlchemy/Alembic 配置；检查初始化生成文件和独立 migration history，不修改 Cloud 依赖或迁移。
- [ ] 2.2 实现显式初始化及版本升级命令；以干净目录初始化、重复初始化保留账本、旧版本升级、新版本拒绝和升级失败保留原库（T-01、T-02、T-03）验收，并补齐本模块初始化/恢复文档。
- [ ] 2.3 为本地账本实现外部 Cloud ID、唯一约束、索引、Schema 版本及必要的写入事务；静态检查 Alembic revision 可逆/可诊断约定，SQLite 文件重新打开后逐项核对约束与持久值。

## 3. Command Inbox 与下发连续游标

- [ ] 3.1 持久化经校验的原始命令信封、fingerprint、命令结果和连续 cursor；将 Inbox、命令效果与 cursor 合入同一事务，事务提交后才允许生成 ACK；以提交前崩溃及重开相同目录验证无半提交（T-04）。
- [ ] 3.2 实现命令重复接收幂等、同 ID/序号异内容冲突留证，以及提交后 ACK 响应丢失时从持久 cursor 重发相同水位；以子进程在持久接收后、ACK 前退出并恢复验证（T-05），并注入丢失 ACK 验证不重复应用命令效果（T-10）。
- [ ] 3.3 实现固定下发轮次水位和乱序/重放处理，不以 ACK 或远端游标猜测未提交的本地命令；对乱序分页、重复页、缺口及重放运行可控序列测试，并记录该模块场景与本 Change Requirement 的对应关系。

## 4. 本地 Task、Assignment 与执行门槛

- [ ] 4.1 持久化本地任务/分配影子、状态来源、执行 ID 与确定性 checkpoint；区分命令持久接收、Command ACK、本地业务接单和实际开工；以“接单与 accepted Outbox 同事务”、ACK 后未接单不得启动的测试验收（T-06）。
- [ ] 4.2 实现固定水位追平、未取消且无 active safety hold 的业务接单门槛，以及独立的执行门槛；验证未追平/已取消/已挂起均不接单或开工，接单后断网仍能保留本地状态。
- [ ] 4.3 为确定性测试 Worker 实现持久检查点及进程重启恢复/转 `recovery_required`；使用相同数据目录杀停并重启子进程，验证既有 Assignment 恢复且不从空任务或未证明幂等的副作用重新开始（T-14）；同步更新运行状态文档。

## 5. Outbox、Assignment 序号与回执幂等

- [ ] 5.1 实现每 Assignment 独立的连续序号和不可变规范事件信封；事实、序号、`event_id` 与 Outbox 必须同事务提交，发送元数据与信封分离；验证连续编号及两个 Assignment 互不争用序号（T-09）。
- [ ] 5.2 实现同事实重复提交返回原事件身份/序号、同 ID 异内容保留原件并转 `recovery_required`；以重复提交与冲突注入覆盖（T-07、T-08），并逐字段检查原 envelope 重试前后字节/fingerprint 不变。
- [ ] 5.3 实现收据按认证 scope、`event_id`、`assignment_id`、sequence、disposition 精确匹配；模拟响应丢失、HTTP 200 但收据错配、重复收据及正确收据，验证只有正确收据销账且重启后可重投原 envelope（T-10）。

## 6. CaptureFact 与本地 FileRecord

- [ ] 6.1 实现 `LocalCaptureFact` 与 `LocalFileRecord` 最小数据访问层、文件状态机和相对路径校验；文件写入、size/SHA-256 校验、ready 引用门槛符合 Spec；校验失败或记录不完整时文件不得被任务/API 引用。
- [ ] 6.2 实现同一持久文件系统内唯一 staging 文件、flush/fsync、摘要确认、原子发布和目录同步；验证成功文件只有在 `FileRecord`、CaptureFact、对应 Outbox 同一最终 DB 事务提交后才可读。
- [ ] 6.3 保持事件 Outbox 与 M3 媒体上传/授权状态分离；测试事件收据不删除或上传原片、不产生 Cloud `MediaObject`/ready/grant，并记录 M4.4 媒体接口边界。

## 7. 文件与数据库崩溃补偿

- [ ] 7.1 实现启动期文件账本对账：逐项检查 staging/final 路径、大小、SHA-256、状态和业务关联；readiness 在验证完成前保持 false，未验证文件不能供 Worker 或 API 引用。
- [ ] 7.2 为临时写入中、验证后 rename 前、rename 后 DB 提交前、DB 提交后进程退出分别注入崩溃；复用原持久目录验证恢复能幂等补偿或转人工状态，覆盖 T-11、T-12、T-13。
- [ ] 7.3 实现孤立文件和孤立数据库记录登记、隔离与人工恢复证据；缺失/损坏文件或孤立文件测试验证原始字节和数据库证据均保留，不自动覆盖、引用或删除。

## 8. 离线恢复、取消与 safety_hold

- [ ] 8.1 实现可持久、可审计的 `LocalSafetyHold` 与显式解挂操作；断网、自然过期、单独撤钥或原因不明 401 不触发 hold；只有模拟的已验证停用/可信本地停机触发 hold，并验证重启/重认证不清除（T-15）。
- [ ] 8.2 实现取消命令的持久 cancellation gate；未开工任务取消后禁止开工，运行任务需保存 checkpoint 并证明安全停止后才提交 `stopped_by_cancel`；测试未经停止证明不得生成该事实。
- [ ] 8.3 保留已取消 Assignment 的离线迟到事实及原 Outbox，确保可补投但不会重开任务、改写 Cloud 终态或生成新接单；以取消后事实补投测试验收（T-16），并与 M4.1 的 W1 语义逐项对照。
- [ ] 8.4 实现游标缺口、账本冲突、坏摘要、不可解释执行状态的持久 `recovery_required` 与受控人工处置；测试恢复原因跨重启保留、人工动作超时仍挂起、恢复后保留原信封/事实（T-18）。

## 9. P01–P10 隔离参数与故障隔离

- [ ] 9.1 以显式隔离 profile 实现 P01–P10 的连接/请求超时、有界退避、jitter、重试预算、Retry-After、冷却探测、积压告警、对账节奏和人工等待上限；FakeClock/固定随机种子验证精确边界，并断言这些值不作为生产默认。
- [ ] 9.2 对每 Assignment 独立推进待发、重试和 `recovery_required`；一个流达到重试预算或永久冲突时保留原事件并允许另一健康 Assignment 继续；以多流注入测试覆盖（T-17、T-19）。
- [ ] 9.3 MockCloudAdapter 支持可控断网、丢 ACK、乱序、重复、拒绝、长 Retry-After、错配收据和同节点凭据恢复情形；按 S1-R1–R4 编写匹配/不匹配收据用例，补充 adapter 场景说明。

## 10. 集成验收、追溯与交付文档

- [ ] 10.1 组合独立子进程、持久 SQLite/文件目录、FakeClock/FakeNetwork、MockCloudAdapter 和确定性 Worker，运行全套本 Change 隔离集成矩阵 T-01–T-20；验证无公网 health/本地持久化可用（T-20），记录每次实际运行的提交 SHA 和结果。
- [ ] 10.2 更新 Edge Runtime README、隔离运行与人工恢复指南，明确安装/显式初始化/升级/启动/诊断命令、故障注入方法、Mock 限制和生产待决项；从干净环境逐条照文档执行，不要求 Cloud 或真实场馆硬件。
- [ ] 10.3 完成全模块兼容检查：`git diff --check`、OpenSpec strict、Cloud 源码/六份 Cloud 主规格/OpenAPI/迁移/Cloud CI 未变更检查；报告把 Cloud 既有 M1–M3 回归与 M4.2 Edge 运行验收分开。

## Requirement / Scenario → Task → Test 验收矩阵

### M4.2 Spec Delta Requirement 对照

本 Spec 使用 `EPR-01` 至 `EPR-09` 作为本地追溯简称，顺序对应 `specs/edge-runtime-persistence/spec.md` 中九项 Requirement。测试均为后续 Apply 的计划，当前 Propose 阶段未执行。

| M4.2 Requirement | 场景 | Task | Test/验收证据 |
| --- | --- | --- | --- |
| EPR-01 独立数据边界/版本化 Schema | 新目录、重复初始化、旧版升级、未知版本及失败保库 | 2.1–2.3 | T-01、T-02、T-03；SQLite 重开与 revision/数据核对 |
| EPR-02 Inbox/cursor 原子持久化 | 提交前崩溃、提交后 ACK、ACK 丢失、重复/冲突命令 | 3.1–3.3 | T-04、T-05、T-10；事务原子性、cursor 和 ACK 重发证据 |
| EPR-03 持久接收/接单/执行分离 | 固定水位未追平、取消、接单同事务、接单后未开工、离线恢复 | 4.1–4.3 | T-06、T-14；状态轨迹与子进程恢复记录 |
| EPR-04 事实/不可变 Outbox/收据 | 重复事实、同 ID 冲突、连续序号、迟到事实、精确收据 | 5.1–5.3、8.3 | T-07–T-10、T-16；原 envelope/fingerprint 与匹配收据记录 |
| EPR-05 Assignment 投递隔离 | 重试预算耗尽、永久拒绝、另一分配继续 | 9.2–9.3 | T-17、T-19；各 Assignment 独立序号/状态与保留事件 |
| EPR-06 文件校验/登记后方可引用 | staging 校验、原子发布、崩溃、孤立与坏引用 | 6.1–6.3、7.1–7.3 | T-11、T-12、T-13；文件 hash、DB 记录及恢复状态 |
| EPR-07 重启恢复与事实保留 | 执行重启、账本缺口、坏摘要/人工恢复 | 4.3、7.1–7.3、8.4 | T-14、T-18；同目录恢复或明确 `recovery_required` |
| EPR-08 safety_hold 与取消停止证据 | 断网/401、可信停用、重启、取消与实际安全停止 | 8.1–8.4 | T-15、T-16；审计记录、hold 持续及 outcome 条件 |
| EPR-09 本地健康/诊断 | 无公网、库或文件卷不可用、诊断脱敏 | 1.3、10.1 | T-20；本地 HTTP 响应、readiness、脱敏输出 |

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

## Workflow follow-up

- 项目负责人审阅并单独授权 Apply 后，才按上述任务开始实现与测试。
- Apply 完成并通过项目验收后，再按 OpenSpec 流程验证和归档本 Change。
