# Spec Delta

## Purpose

为场馆 Edge Runtime 定义独立于 Cloud 的本地持久状态、离线连续性和崩溃恢复行为，使接收的命令、已发生的业务事实和未确认事件在进程重启后仍可核验与恢复。

## ADDED Requirements

### Requirement: Edge 持久数据具有独立边界和版本

Edge Runtime SHALL 使用独立数据目录和版本化 Schema 保存本地运行状态。服务启动 MUST NOT 静默创建空白替代库或应用升级；数据版本不兼容时 MUST 阻止业务运行并报告可诊断状态。

#### Scenario: 新数据目录显式初始化
- **WHEN** 运维在隔离环境对空数据目录执行初始化
- **THEN** Edge SHALL 建立本地账本与初始 Schema 版本，后续启动可从同一目录恢复

#### Scenario: 重复初始化不重置数据
- **WHEN** 初始化命令再次指向已含任务、Inbox 或 Outbox 的数据目录
- **THEN** Edge MUST 保留已有行、序号与信封，不得清库或重复生成初始业务事实

#### Scenario: 未知 Schema 版本
- **WHEN** 服务发现数据库 Schema 高于自身支持版本或升级失败
- **THEN** Edge MUST 保持原数据不变、拒绝业务运行并给出版本诊断

### Requirement: 命令 Inbox 与连续游标原子持久化

Edge SHALL 在同一持久事务中保存已验证命令、命令产生的本地效果和连续游标。只有事务提交后的连续水位可用于 Command ACK；重复命令不得重复产生业务效果。

#### Scenario: 命令事务提交后才发送 ACK
- **WHEN** Edge 收到下行命令并成功提交 Inbox、命令效果及游标
- **THEN** Edge MAY 对该连续游标发送 Command ACK，且重启后可从持久账本重发相同水位

#### Scenario: 提交前进程崩溃
- **WHEN** 命令 Inbox 事务在提交前中断
- **THEN** 命令效果和游标 MUST 均不可见，Edge MUST NOT 确认该命令

#### Scenario: 重复和冲突命令
- **WHEN** Edge 收到已持久命令的相同信封，或同一命令 ID/序号对应不同信封
- **THEN** 相同信封 MUST 幂等返回已提交进度；异参 MUST 保留原记录并进入可诊断冲突状态

### Requirement: 持久接收、业务接单和实际执行相互区分

本地任务 SHALL 区分 Cloud 分配状态、Edge 业务接单和实际执行状态。持久接收或 Command ACK MUST NOT 自动接单或开工；Edge 只有在固定命令水位追平、Assignment 未取消且无 safety hold 时才可持久接单。

#### Scenario: 未追平或已取消时不接单
- **WHEN** 命令轮仍未达到固定水位，或同一 Assignment 已应用取消命令
- **THEN** Edge MUST 不产生业务接单事实且 MUST 不启动该任务

#### Scenario: 追平后接单与接单事件同事务
- **WHEN** 固定水位已追平、Assignment 仍有效且没有安全挂起
- **THEN** Edge MUST 在同一事务提交本地接单状态和唯一的 `training_task.accepted` 事件

#### Scenario: 已接单不等于已开工
- **WHEN** Assignment 已持久接单但执行门槛尚未通过
- **THEN** Edge MUST 保留可离线恢复的接单状态，但不得报告实际开始执行或自动越过取消/安全挂起门槛

### Requirement: 本地事实与不可变 Outbox 原子保存

Edge SHALL 在单个本地事务中保存采集/任务终态事实、Assignment 连续序号和对应不可变事件信封。重试 MUST 复用原 `event_id`、序号、版本和内容；Outbox 在匹配收据前不得确认或删除。

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

### Requirement: Assignment 投递失败互相隔离

Edge SHALL 对每个 Assignment 维护独立的投递进度和有界重试状态。瞬态失败耗尽一轮预算后 MUST 保留原 Outbox；永久拒绝 MUST 暂停并诊断对应流，且不得阻断其他可运行 Assignment。

#### Scenario: 重试预算耗尽
- **WHEN** 网络/服务错误达到隔离配置的一轮预算上限
- **THEN** Edge MUST 保留原事件 ID、序号、内容及后续恢复时机，不得删除或标记已送达

#### Scenario: 单个 Assignment 永久错误
- **WHEN** 一个 Assignment 收到不可重试的完整性或格式拒绝
- **THEN** Edge MUST 将该流置于可诊断/人工恢复状态，同时允许其他无冲突 Assignment 继续投递或执行

### Requirement: 文件在验证和数据库登记完成前不可引用

Edge SHALL 将文件暂存、完整性校验、原子发布和数据库登记作为可恢复的分阶段流程。只有已验证文件及其本地 FileRecord、CaptureFact 和相关 Outbox 均持久提交后，任务/本地读取接口才可引用该文件；文件故障 MUST NOT 自动删除原始视频。

#### Scenario: 暂存文件通过验证后发布
- **WHEN** 文件临时写入完成且大小与 SHA-256 校验通过
- **THEN** Edge SHALL 在同一数据卷原子发布文件，并在最终数据库事务提交 FileRecord、事实与 Outbox 后开放本地引用

#### Scenario: 校验前进程崩溃
- **WHEN** 进程在临时文件写入、验证或发布期间退出
- **THEN** 重启检查 MUST 将未验证文件保持为不可引用状态并记录恢复原因，不得伪造完整 CaptureFact 或 Outbox

#### Scenario: 文件与数据库状态不一致
- **WHEN** 数据库记录指向缺失/摘要不符文件，或发现没有数据库记录的文件
- **THEN** Edge MUST 标记对应恢复/孤立状态并保留文件证据，不自动覆盖、引用或删除原始视频

### Requirement: 重启恢复失败必须可见且不丢事实

Edge SHALL 在重启时核对 Schema、命令/事件连续性、本地任务检查点和登记文件。无法由持久证据安全恢复的局部状态 MUST 标记 `recovery_required` 并阻止其继续执行或投递；其他独立 Assignment MAY 继续运行。

#### Scenario: 已接单任务进程重启
- **WHEN** Edge 在任务执行期间退出并以相同数据目录启动
- **THEN** Edge MUST 按已提交检查点恢复同一 Assignment，或保留事实并标记人工恢复，MUST NOT 从新任务或空账本开始

#### Scenario: 无法补齐的本地游标
- **WHEN** 命令/事件游标丢失、账本损坏或存在不可解释序号缺口
- **THEN** Edge MUST 保留任务、Inbox 和原 Outbox，挂起受影响范围并显示恢复原因，不得推断 Cloud 水位等于本地完成状态

### Requirement: safety_hold 跨重启保持并受审计控制

Edge SHALL 对已验证节点停用或可信本地安全停机持久保存 `safety_hold`，阻止所有新开工并要求运行中任务安全收口。网络断开、凭据自然过期、单独撤钥或普通 401 MUST NOT 单独设置该挂起；重启 MUST NOT 自动清除挂起。

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

### Requirement: 本地健康与诊断不依赖公网

Edge SHALL 在 Cloud 不可达时提供本地存活/就绪状态和只读的基本持久化诊断。诊断 MUST 显示受影响范围、挂起与待发计数，不暴露凭据、完整事件载荷或原始文件路径。

#### Scenario: 无公网健康检查
- **WHEN** Cloud 不可达且本地数据库/文件目录可用
- **THEN** 本地 health/diagnostic 操作 MUST 可响应并显示同步受限与本地服务可用状态

#### Scenario: 本地账本或文件存储不可用
- **WHEN** 数据库 Schema、写入能力或文件卷检查失败
- **THEN** Edge MUST 报告 not-ready/恢复状态，不得声称可安全接单或执行
