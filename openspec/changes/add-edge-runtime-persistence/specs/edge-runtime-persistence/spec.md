# Spec Delta

## Purpose

为场馆 Edge Runtime 定义独立于 Cloud 的本地持久状态、离线连续性和崩溃恢复行为，使接收的命令、已发生的业务事实和未确认事件在进程重启后仍可核验与恢复。

## ADDED Requirements

### Requirement: Edge 持久数据具有独立边界和版本

Edge Runtime SHALL 使用独立数据目录、版本化 Schema 和唯一 `LocalRuntimeIdentity` 保存本地运行状态，并将每个目录不可变绑定到一个 Runtime/Tenant/Site/Node。服务、初始化和升级 MUST 互斥持有该目录的单实例运行权；身份不匹配或 Schema 不兼容时 MUST 阻止账本业务访问且 MUST NOT 改写身份或 Outbox。

#### Scenario: 新数据目录显式初始化
- **WHEN** 运维在隔离环境对空数据目录执行初始化
- **THEN** Edge SHALL 建立本地账本与初始 Schema 版本，后续启动可从同一目录恢复

#### Scenario: 重复初始化不重置数据
- **WHEN** 初始化命令再次指向已含任务、Inbox 或 Outbox 的数据目录
- **THEN** Edge MUST 保留已有行、序号与信封，不得清库或重复生成初始业务事实

#### Scenario: 未知 Schema 版本
- **WHEN** 服务发现数据库 Schema 高于自身支持版本或升级失败
- **THEN** Edge MUST 保持原数据不变、拒绝业务运行并给出版本诊断

#### Scenario: 首次绑定身份及凭据轮换
- **WHEN** 运维显式初始化空目录并绑定 Tenant/Site/Node，之后同一 Node 使用新 Credential 启动
- **THEN** Edge MUST 只创建一个包含稳定 `runtime_instance_id`、绑定作用域、初始化时刻和 Schema 版本的身份记录；只要 Tenant/Site/Node 一致就 MUST 复用原账本，MUST NOT 将 Credential ID 或 Secret 作为身份或清空旧数据

#### Scenario: 不同 Node 试图复用目录
- **WHEN** 配置 Tenant/Site/Node 与目录中持久身份不一致
- **THEN** Edge MUST 进入 `identity_mismatch` 且 not-ready；MUST NOT 查询/读取/发送旧 Outbox、执行旧 Assignment、重绑身份、删除身份记录或清空数据，并 MUST 保留目录原有证据

#### Scenario: 同目录第二 Runtime 或初始化/升级竞争
- **WHEN** Runtime、初始化器或 Schema upgrader 中已有一个持有数据目录独占运行权
- **THEN** 其他进程 MUST 在启动业务消费者/Dispatcher 前失败并返回诊断；进程异常退出后 OS 锁 MUST 自动释放，残留锁文件 MUST NOT 永久阻塞后续恢复

### Requirement: 命令 Inbox 与连续游标原子持久化

Edge SHALL 按 M4.1 严格校验下行分页和命令（单页最多 50 条）。每条已验证命令、对应本地效果和连续游标须原子提交，活动 `round_through` 跨重启固定。分页尾游标、空页、重复页及 ACK 规则见下列场景。

#### Scenario: 命令事务提交后才发送 ACK
- **WHEN** Edge 收到下行命令并成功提交 Inbox、命令效果及游标
- **THEN** Edge MAY 对该连续游标发送 Command ACK，且重启后可从持久账本重发相同水位

#### Scenario: 提交前进程崩溃
- **WHEN** 命令 Inbox 事务在提交前中断
- **THEN** 命令效果和游标 MUST 均不可见，Edge MUST NOT 确认该命令

#### Scenario: 重复和冲突命令
- **WHEN** Edge 收到已持久命令的相同信封，或同一命令 ID/序号对应不同信封
- **THEN** 相同信封 MUST 幂等返回已提交进度；异参 MUST 保留原记录并进入可诊断冲突状态

#### Scenario: 命令页和单命令处于契约边界
- **WHEN** CloudAdapter 返回结构合法、最多 50 条的分页，且每条命令 UTF-8 JSON 字节不超过 8192 并满足 M4.1 字段白名单
- **THEN** Edge MUST 按正式契约验证该页和每条命令；51 条的页 MUST 在任何命令应用前整页拒绝，50 条与 8192 字节上限 MUST 分别计算而不得混为一个限制

#### Scenario: 严格 JSON 与字段校验失败
- **WHEN** 下行命令包含重复 JSON Key、未知字段、非整数 1 的 `schema_version`、未知方向/类型、非规范 UUID/UTC、超安全范围整数、显式 null 或不符合载荷枚举
- **THEN** Edge MUST 在写 Inbox/命令效果/Cursor 前拒绝该命令，保留有界脱敏诊断，并 MUST NOT ACK 越过它的序号

#### Scenario: 连续流中第 N 条命令非法
- **WHEN** 分页本身合法、序号 N 前有合法命令，但 N 非法或存在序号冲突/缺口
- **THEN** Edge MAY 保留已原子提交的连续前缀；MUST NOT 应用 N 或任何后续命令，Cursor/ACK MUST NOT 越过 N−1；无法证明兼容安全时 MUST 将该流持久标为 `recovery_required`，保留同一轮次并等待兼容软件升级或经审计的人工恢复，不得自动跳过或解除阻断

#### Scenario: 固定命令水位跨重启
- **WHEN** 已持久化当前同步轮次的 `round_through`，但尚未连续应用至该水位时进程重启
- **THEN** Edge MUST 从持久 `last_applied_sequence` 续取并保留原 `round_through`，MUST NOT 用 `next_after` 或新响应上界覆盖本地进度/未完成轮次；只有 Cursor 连续到达该值后才可结束本轮并开启下一轮

#### Scenario: 分页尾游标与命令连续尾部一致
- **WHEN** CloudAdapter 返回一页命令及 `through`、`next_after`，或返回空页
- **THEN** 请求 `after`、响应 `through`、`next_after` MUST 是非布尔 JSON 整数，范围为 0 到 2^53−1；`through` MUST 不小于请求 `after`，`next_after` MUST 满足 `after <= next_after <= round_through`。非空页命令序号 MUST 从 `after+1` 连续到本页最后一条，且 `next_after` MUST 等于该尾序号；空页 MUST 令 `next_after == after`，不推进 Cursor。`next_after` 小于/大于非空页尾、超过 `round_through`、空页虚报推进或其他页尾不一致 MUST 在应用任何命令前拒绝整页；重复页只可按已持久同 ID/同内容幂等重放。异常后重启 MUST 以 `last_applied_sequence` 重取，MUST NOT ACK 越位或跳过命令。

#### Scenario: ACK 状态与 Inbox/Task 阶段分离
- **WHEN** Command ACK 尚未发送、发送响应丢失或已收到响应
- **THEN** Edge MUST 将 ACK 投递元数据与 Inbox `applied`、业务接单和 Worker 执行状态分开；ACK 重试 MUST 使用已提交 Cursor，MUST NOT 因 ACK 成功而自动接单或开工

### Requirement: 持久接收、业务接单和实际执行相互区分

LocalTrainingTask SHALL 独立持久化 Cloud 任务快照和版本；LocalAssignment SHALL 独立持久化 Edge 执行阶段及恢复状态。命令持久接收或 ACK 不代表业务接单或实际执行；门槛规则见下列场景。

#### Scenario: 未追平或已取消时不接单
- **WHEN** 命令轮仍未达到固定水位，或同一 Assignment 已应用取消命令
- **THEN** Edge MUST 不产生业务接单事实且 MUST 不启动该任务

#### Scenario: 追平后接单与接单事件同事务
- **WHEN** 固定水位已追平、Assignment 仍有效且没有安全挂起
- **THEN** Edge MUST 在同一事务提交本地接单状态和唯一的 `training_task.accepted` 事件

#### Scenario: 已接单不等于已开工
- **WHEN** Assignment 已持久接单但执行门槛尚未通过
- **THEN** Edge MUST 保留可离线恢复的接单状态，但不得报告实际开始执行或自动越过取消/安全挂起门槛

#### Scenario: Cloud 控制快照与 Edge 阶段分别转移
- **WHEN** Edge 应用 `training_task.assigned`、`training_task.cancelled`、Reconcile Task 投影或本地执行事实
- **THEN** Edge MUST 分别持久保存 `cloud_task_status`（M4.1 枚举 `assigned`、`accepted`、`completed`、`failed`、`cancelled`）、`cloud_task_version`、`cloud_projection_revision` 与本地 Assignment phase；Reconcile 只应用比本地更高的 `projection_revision`，同 revision 同投影幂等、旧 revision 不得覆盖；MUST NOT 将 Edge phase 当成 Cloud 正式 Task 状态，或因快照更新改写 Assignment phase、执行事实、CaptureFact 或 Outbox。

#### Scenario: Cloud Task 投影 revision 重放与乱序
- **WHEN** Reconcile 返回较新 revision、相同 revision 重放或较旧 revision，且 `task_version` 独立变化
- **THEN** Edge MUST 只按 `projection_revision` 判断投影新旧，并独立验证 `task_version` 的 M4.1 非布尔安全整数/正整数规则；更高 revision 可在 task_version 不变时更新快照，但不得令 task_version 回退。相同 revision 且 status/task_version 相同是 no-op，较旧 revision 连同其状态和 task_version 一起忽略；相同 revision 异字段或较新 revision 携带回退的 task_version MUST 保留原快照并留下 Task 作用域诊断/`recovery_required`，不得改变 Edge Assignment 或 Outbox。

#### Scenario: 取消与开工竞争
- **WHEN** 同一 Assignment 的取消应用事务与执行资格事务并发
- **THEN** 若取消先提交，执行资格 MUST 被拒绝；若执行资格先提交，任务沿同一 run identity 进入 running 并接受合作停止；两种顺序 MUST 有唯一事务先后且 MUST NOT 在已应用取消之后取得新开工资格

### Requirement: 本地事实与不可变 Outbox 原子保存

Edge SHALL 在单个本地事务中保存采集/任务终态事实、Assignment 连续序号和对应不可变事件信封；并发连接 MUST 仍保持每 Assignment 唯一连续序号和事实幂等。重试 MUST 复用原 `event_id`、序号、版本和内容；Outbox 在匹配收据前不得确认或删除。

#### Scenario: 同一事实重复提交
- **WHEN** 已提交的本地事实以相同身份和内容再次提交
- **THEN** Edge MUST 返回原事件身份与序号，不新增第二份业务效果

#### Scenario: 提交时生成并保存事件
- **WHEN** Edge 提交新的采集事实或真实任务终态
- **THEN** 事实、分配序号和完整 Outbox envelope MUST 同时可见或同时不可见

#### Scenario: 同 ID 异内容或序号有缺口
- **WHEN** 已登记 event_id 被用于不同内容，或 Assignment 流无法连续恢复
- **THEN** Edge MUST 保留原 envelope 和证据，将受影响流标为 `recovery_required`，不得改写或跳号

#### Scenario: ACK 收据精确匹配
- **WHEN** CloudAdapter 返回上行收据
- **THEN** Edge 只有在请求认证 scope、event_id、assignment_id、sequence 及 disposition 均与该 Outbox 项匹配时才可确认；普通 HTTP 200 或游标水位 MUST NOT 单独销账

#### Scenario: Cloud 取消后的迟到事实仍保留
- **WHEN** Cloud 已合法提交 Assignment 取消，而 Edge 之后才补投该 Assignment 在离线期间产生的本地事实
- **THEN** Edge MUST 保留原事实与不可变事件供对账；不得据此重开任务、覆盖 Cloud 终态或伪造新的业务接单

#### Scenario: 两个数据库连接并发申请 Assignment 序号
- **WHEN** 两个独立 SQLite Connection 并发向同一 Assignment 提交不同合法事实
- **THEN** Edge MUST 只提交唯一且连续的两个序号及各自唯一 Outbox；不得重复分配序号、留空洞或丢失已提交事实

#### Scenario: 两个连接并发提交同一事实
- **WHEN** 两个独立数据库会话同时提交同一业务幂等身份和内容
- **THEN** Edge MUST 只产生一份事实、一个 `event_id` 和一个 sequence；未获胜请求 MUST 返回获胜事务的原持久结果

### Requirement: Assignment 投递失败互相隔离

Edge SHALL 对每个 Assignment 维护独立的投递进度和有界重试状态。瞬态失败耗尽一轮预算后 MUST 保留原 Outbox；永久拒绝 MUST 暂停并诊断对应流，且不得阻断其他可运行 Assignment。

#### Scenario: 重试预算耗尽
- **WHEN** 网络/服务错误达到隔离配置的一轮预算上限
- **THEN** Edge MUST 保留原事件 ID、序号、内容及后续恢复时机，不得删除或标记已送达

#### Scenario: 单个 Assignment 永久错误
- **WHEN** 一个 Assignment 收到不可重试的完整性或格式拒绝
- **THEN** Edge MUST 将该流置于可诊断/人工恢复状态，同时允许其他无冲突 Assignment 继续投递或执行

### Requirement: 文件在验证和数据库登记完成前不可引用

Edge SHALL 将 FileRecord 按 `staging_intent`、`staged_verified`、`published`、`available` 和阻断异常态分阶段持久化；文件 rename 与父目录 fsync 完成后 MUST 通过独立数据库事务持久提交 `published`，之后才可在另一最终业务事务提交 CaptureFact/Outbox/序号并变为 `available`。只有完整校验、同卷不覆盖发布及最终业务事务提交后才能本地引用；本地 `available` MUST NOT 表示 Cloud `VideoAsset.ready`，文件故障 MUST NOT 自动删除原始视频。

#### Scenario: 暂存文件通过验证后发布
- **WHEN** 文件临时写入完成且大小与 SHA-256 校验通过
- **THEN** Edge SHALL 先提交 `staging_intent`、再提交 `staged_verified`；同卷 no-replace rename 与文件/父目录 fsync 完成后，MUST 在独立 DB 提交点持久写入 `published`。随后仅在最终事务原子提交 `FileRecord=available`、CaptureFact、Outbox 和 Assignment sequence 后开放本地引用

#### Scenario: published 提交前后崩溃恢复
- **WHEN** 进程分别在 rename 前、rename+fsync 成功但 `published` DB 提交前、`published` 已提交但最终 `available` 事务前退出
- **THEN** 重启 MUST 依 intent/path/hash 收敛对应状态：rename 前保持 staging；rename 后重验并幂等提交 `published`，不得先建 CaptureFact/Outbox；`published` 后重验并原子补交最终业务事务。恢复全过程 MUST 最多产生一份 CaptureFact、一条不可变 Outbox 和一个 Assignment sequence，不得覆盖或删除原文件

#### Scenario: 校验前进程崩溃
- **WHEN** 进程在临时文件写入、验证或发布期间退出
- **THEN** 重启检查 MUST 将未验证文件保持为不可引用状态并记录恢复原因，不得伪造完整 CaptureFact 或 Outbox

#### Scenario: 文件与数据库状态不一致
- **WHEN** 数据库记录指向缺失/摘要不符文件，或发现没有数据库记录的文件
- **THEN** Edge MUST 标记对应恢复/孤立状态并保留文件证据，不自动覆盖、引用或删除原始视频

#### Scenario: 磁盘空间或持久化屏障失败
- **WHEN** 文件写入/最终目录或 SQLite 写入遇到 ENOSPC，或文件/父目录 fsync 失败
- **THEN** Edge MUST NOT 提交可引用的 CaptureFact/Outbox；已有 staging intent 和原始字节 MUST 保留；无法写 RecoveryRecord 时 MUST 报 not-ready 并在恢复可写后从 intent 派生诊断

#### Scenario: 跨文件系统发布或路径替换
- **WHEN** staging 与 objects 跨文件系统导致 EXDEV，或路径包含 `..`、符号链接、数据根替换/越界或非预期重复引用
- **THEN** Edge MUST 拒绝引用/发布，MUST NOT 以 copy+delete 代替原子操作，也不得读取根目录外文件或覆盖现存对象

#### Scenario: 文件状态与 Cloud 媒体状态分离
- **WHEN** 本地文件达到 `available` 或事件 Outbox 获得匹配收据
- **THEN** Edge MUST 只更新本地 FileRecord/事件状态，不得推断 Cloud Asset 已上传、校验、授权或 `ready`，不得据此删除本地原片

### Requirement: 重启恢复失败必须可见且不丢事实

Edge SHALL 在启动时检查身份、Schema、命令/事件连续性、活动任务检查点、Hold/Recovery 和文件账本；Schema 升级 SHALL 先快照并验证候选库，失败不得破坏活动原库。无法安全恢复的局部状态 MUST 标记 `recovery_required` 并阻止其继续执行或投递；健康 Assignment MAY 继续运行。

#### Scenario: 已接单任务进程重启
- **WHEN** Edge 在任务执行期间退出并以相同数据目录启动
- **THEN** Edge MUST 按已提交检查点恢复同一 Assignment，或保留事实并标记人工恢复，MUST NOT 从新任务或空账本开始

#### Scenario: 无法补齐的本地游标
- **WHEN** 命令/事件游标丢失、账本损坏或存在不可解释序号缺口
- **THEN** Edge MUST 保留任务、Inbox 和原 Outbox，挂起受影响范围并显示恢复原因，不得推断 Cloud 水位等于本地完成状态

#### Scenario: Schema 候选升级失败
- **WHEN** SQLite 快照、候选迁移、revision/完整性验证或数据不变量验证任一阶段失败
- **THEN** Edge MUST 保留原活动库和升级前一致快照，MUST NOT 自动启动空库、半升级库或未验证候选库；Runtime 保持 not-ready 并报告候选/源版本诊断

#### Scenario: Schema 切换前后进程中断
- **WHEN** 进程在候选验证后、活动库原子切换前退出，或在切换后但 manifest 完成标记前退出
- **THEN** 重启 MUST 在独占锁下核对 upgrade manifest、唯一活动库路径、revision 与摘要；只有活动库匹配已验证候选才可认定切换完成，否则保持 not-ready、保留原库/快照/候选和日志并等待显式恢复

#### Scenario: 启动扫描及分级文件校验
- **WHEN** Runtime 启动并完成身份/Schema 检查
- **THEN** Edge MUST 在 ready 前扫描活动/未完成 FileRecord、异常退出涉及文件、未结恢复记录、活动 Assignment/checkpoint、Inbox/Cursor/round 和 Outbox 序列；异常/未完成/元数据变化文件必须重算 SHA-256，正常不可变历史文件可以快速 metadata 核验但 MUST NOT 宣称本次已完整哈希

### Requirement: safety_hold 跨重启保持并受审计控制

Edge SHALL 对每个已验证节点停用或可信本地安全停机原因持久保存独立 Node `safety_hold`；同时将序号/文件/任务异常以 Assignment 级恢复阻断分开保存。Node Hold 阻止所有新开工，Assignment 阻断只影响该分配。网络断开、凭据自然过期、单独撤钥或普通 401 MUST NOT 单独设置 Node Hold；重启 MUST NOT 自动清除任一阻断。

#### Scenario: 通用认证失败不触发挂起
- **WHEN** Edge 断网、遇到自然过期或无法区分原因的 401
- **THEN** Edge MUST 暂停云端同步并保留已接单任务和事实，不推断节点停用，也不自动停止本地执行

#### Scenario: 已验证停用触发持久挂起
- **WHEN** Edge 接受已验证节点停用或可信本地停机事实
- **THEN** Edge MUST 持久设置 hold、禁止新开工、请求运行任务安全停止并保存检查点

#### Scenario: 重启或重认证后仍挂起
- **WHEN** 进程重启、网络恢复或同 Node 更新有效凭据但没有受控解挂操作
- **THEN** Edge MUST 保持 safety_hold；只有写明操作者、时间、原因的显式审计解挂才可允许后续开工

#### Scenario: stopped_by_cancel 需要实际停止证据
- **WHEN** Edge 处理运行中任务的取消
- **THEN** Edge 仅在同一 Assignment 取消命令已持久应用且执行器实际安全停止后，才可产生 `stopped_by_cancel` 事实

#### Scenario: Node Hold 的多个原因独立聚合
- **WHEN** 一个 Node 同时存在两个或更多有效停用/可信本地停机原因，且其中一个原因被显式解除
- **THEN** Edge MUST 只解除被指明且审计的 hold；只要仍有任一 active Node Hold，就 MUST 继续阻止该 Node 所有新开工

#### Scenario: Assignment 恢复阻断不连坐
- **WHEN** 一个 Assignment 因序号缺口、文件摘要或执行检查点异常进入 `recovery_required`，同 Node 的其他 Assignment 正常
- **THEN** Edge MUST 阻止该受影响 Assignment 的开工/投递并保留其恢复证据；MUST NOT 将其自动升级为 Node SafetyHold，其他健康 Assignment MAY 继续

#### Scenario: 解除单项原因不清除其他恢复阻断
- **WHEN** 操作者解决一个 hold 或 Assignment RecoveryRecord，但仍有其他未解原因
- **THEN** Edge MUST 保留其余 active/open 记录；只有作用域相关的全部阻断原因均被单独审计解决且恢复条件通过时，才可重新取得执行资格

### Requirement: 本地健康与诊断不依赖公网

Edge SHALL 提供独立的本地存活/就绪状态 `uninitialized`、`initializing`、`recovering`、`ready`、`not_ready`、`identity_mismatch` 和全局 `recovery_required`。Cloud 同步状态、Node SafetyHold 与 Assignment RecoveryRecord SHALL 作为独立维度报告。诊断 MUST 显示受影响范围、挂起与待发计数，不暴露凭据、完整事件载荷或原始文件路径。

#### Scenario: 无公网健康检查
- **WHEN** Cloud 不可达且本地数据库/文件目录可用
- **THEN** 本地 health/diagnostic 操作 MUST 可响应并显示同步受限与本地服务可用状态

#### Scenario: 本地账本或文件存储不可用
- **WHEN** 数据库 Schema、写入能力或文件卷检查失败
- **THEN** Edge MUST 报告 not-ready/恢复状态，不得声称可安全接单或执行

#### Scenario: 身份匹配但离线启动
- **WHEN** 本地配置绑定与 RuntimeIdentity 一致、必需恢复扫描通过，但 CloudAdapter 当前不可达/未认证
- **THEN** 本地 Runtime readiness MAY 为 `ready` 且本地 health/已接单任务恢复可用；Cloud sync MUST 单独报告 paused，MUST NOT 拉取命令或发送待发 Outbox，已接单任务仍按 M4.1 离线规则运行

#### Scenario: 恢复扫描期间和安全挂起期间的就绪
- **WHEN** 恢复扫描尚未完成，或 Runtime 已 ready 但存在 Node SafetyHold/局部 Assignment 阻断
- **THEN** 扫描期间全局 readiness MUST 保持 `recovering`/not-ready；扫描完成后 Node SafetyHold 不必关闭只读 health API，但 MUST 阻止所有新开工，局部阻断 MUST 只限制对应 Assignment
