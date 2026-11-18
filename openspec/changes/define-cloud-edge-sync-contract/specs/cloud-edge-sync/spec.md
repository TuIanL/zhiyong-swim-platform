# Spec Delta

## Purpose

定义 Cloud 与 Edge 间版本化训练任务指令、最小采集事实和执行回报的行为，使节点在断网期间继续已接收的工作，并在重新联网后通过持久收据、重放和对账恢复一致的任务视图。

## ADDED Requirements

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

生产端 SHALL 在同一事务保存业务变化与待发送事件。接收端 MUST 在同一事务持久记录去重结果及其业务作用，并在提交后才确认。Cloud 下发游标的 ACK MUST 表示 Edge 已经持久保存对应命令，接收任务是独立的 Edge 业务事实。

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

已持久接收的任务 SHALL 在断网或云端凭据失效期间继续本地执行，并持久记录事实。网络失败 SHALL 以有界退避重试，重试预算用完后保留队列。尚未持久接收的云端任务 MUST 经控制流同步才可启动。

#### Scenario: S5.1 Offline restart and retry exhaustion
- **WHEN** 已接收任务开始执行后 Edge 断网、进程重启且达到一轮重试预算
- **THEN** Edge MUST 从本地状态恢复同一任务或标记需人工恢复，保留待同步事实及原 ID，禁止静默丢弃。待接收任务不得因重启或时钟变化而启动。

#### Scenario: S5.2 Permanent rejection needs review
- **WHEN** 上报遇到不可重试的格式、归属或完整性错误
- **THEN** Edge MUST 保留未确认记录和脱敏原因，停止该流盲重试并允许其他无关流继续。未获结构化终态收据不得视为已送达。

### Requirement: R6 Cancellation and completion serialize at Cloud

同一任务的 Cloud 取消及终态回报 SHALL 受同一条件化状态转换约束。Cloud MUST 保留先提交的合法终态以及后到、经过授权的冲突事实。Edge 在持久应用取消后 MUST 禁止新开该分配的执行并协作停止仍在运行的执行；已形成的本地事实仍可按契约回报。

#### Scenario: S6.1 Cancellation wins before completion
- **WHEN** Cloud 任务取消先提交，或父 Session 取消先提交并在同事务封住该未终结任务，随后收到合规的成功回报
- **THEN** Cloud MUST 保持任务 cancelled，持久记录冲突并返回冲突收据。Edge MUST 保留本地产物，Cloud 不得据此发布产物或将任务改回 completed。

#### Scenario: S6.2 Completion wins before cancellation
- **WHEN** 合法终态回报在 Cloud 已提交为 completed，随后提交任务取消请求
- **THEN** 任务取消请求 MUST 报告状态冲突且不产生取消指令。独立的 Session 取消按既有规则处理，既有任务成功事实仍可审计。

#### Scenario: S6.3 Cancel arrives before dispatch starts
- **WHEN** Edge 在同一次补拉中发现一个尚未接收的分配及其后续取消，或在已接收但尚未开始时持久应用取消
- **THEN** Edge MUST 记录取消并阻止新执行。对已经执行过的本地事实 MUST 保留可追溯记录。

### Requirement: R7 Credential recovery preserves node boundaries

同步 SHALL 使用试图访问当时仍有效、已注册且 active 的节点身份。过期、撤销或停用 MUST 拒绝同步与旧收据读取，且通信 MUST NOT 延长凭据期限。受控重新签发后的原节点 SHALL 可以重放原有事件；不同节点 MUST 无法继承队列或确认游标。

#### Scenario: S7.1 Credential expires while isolated
- **WHEN** active 节点断网 35 天并以原凭据重连，或在服务端 UTC 恰好到达失效时请求重放
- **THEN** Cloud MUST 返回 401，无新收据与业务写入。Edge MUST 暂停云端同步并保留本地任务和 Outbox，等待受控更新凭据。

#### Scenario: S7.2 Reissue for the same node
- **WHEN** 有权人员受控签发相同节点的新凭据并更新本机，节点处于 active 且当前资源权限仍有效
- **THEN** 节点 MUST 能按原标识和游标对账并恢复投递。旧凭据及其他节点的新凭据 MUST 仍无法访问这些收据、任务或历史。

### Requirement: R8 Existing media and identity contracts continue to apply

同步事件 SHALL 只包含允许的有界元数据。另行获准的二进制传输 SHALL 复用 M3 UploadSession 与既有身份、资源、有效期及整对象验证约束。同步 ACK MUST 只确认事件处理结果。

#### Scenario: S8.1 Distinct media and event acknowledgements
- **WHEN** 采集事件已 ACK，但视频尚未获准上传，或已获准上传并处于 `completing`
- **THEN** Edge MUST 保留本地副本。Cloud MUST 不把事件 ACK 或分片完成当作 `ready`，且短期授权、撤权和整对象校验继续生效。

#### Scenario: S8.2 Legacy clients and resources remain compatible
- **WHEN** M1–M3 客户端继续使用原身份、Session、幂等上传或媒体读取操作，或历史 Session 从未分配任务
- **THEN** 原有请求和状态语义 MUST 保持兼容。服务 MUST 不为旧行自动生成任务、事件、媒体上传或读取权限。
