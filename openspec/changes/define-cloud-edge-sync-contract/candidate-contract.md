# v1 候选行为契约与样例

**二轮 Propose · 待负责人签认 · 后续实施输入**

R1–R8 与原 19 个 Scenario ID 延续自 [原始评审 Head](https://github.com/TuIanL/zhiyong-swim-platform/commit/b2bb18313d9fc1b66d85ee391b8e11aee23bff1d)。以下 SHALL/MUST 用于表达候选行为的验收强度。负责人签认只确认文档设计，M4.2/M4.3 应各自将承担的行为转写为实施 Change 的 Delta。满足状态须由对应实现及验收证据支持，跨端收敛由 M4.4 单独验收。M4.1 使用 `skip_specs: true`，未来归档时本文随文档留存。

## 用途

定义 Cloud 与 Edge 间版本化训练任务指令、最小采集事实和执行回报的行为，使节点在断网期间继续已接收的工作，并在重新联网后通过持久收据、重放和对账恢复一致的任务视图。

## 候选需求与场景

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

同步 SHALL 使用试图访问当时仍有效、已注册且 active 的节点身份。自然过期、凭据撤销或节点停用均 MUST 拒绝同步与旧收据读取，通信 MUST NOT 延长凭据期限。Edge 的本地执行/安全停止由已验证的本地可知状态按 D5 决定，单一 401 不推断原因。受控重新签发后的原节点 SHALL 可以重放原有事件；不同节点 MUST 无法继承队列或确认游标。

#### Scenario: S7.1 Credential expires while isolated
- **WHEN** active 节点断网 35 天并以原凭据重连，或在服务端 UTC 恰好到达失效时请求重放
- **THEN** Cloud MUST 返回 401，无新收据与业务写入。Edge MUST 暂停云端同步并保留本地任务和 Outbox，等待受控更新凭据。没有独立安全停止指令时，已接单任务仍可本地执行。

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

## 协议样例

下列样例均使用合成数据。完整的输入、预期结果和后续证据见 [验收矩阵](tasks.md#acceptance-matrix)，涉及本地确定性与 PG 竞态的细节见 [Design](design.md)。

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
- Device 同归属但已停用时，按 Q7 的推荐选项返回 200，收据 `disposition=conflict_recorded` 且 `code=device_disabled`。有效冲突占用该上行序号，普通采集投影不增加。

### ACK、接单与实际执行

| 向量 | 轨迹 | 期望 |
| --- | --- | --- |
| A1 | 拉取分配命令 41。先模拟收到 HTTP 响应后、本地事务提交前崩溃，再模拟已提交持久接收后、ACK 发出前重启 | 第一次无游标推进，第二次可补发 `{"through":41}`。两次均未自动接单或开工。Cloud 处理 Command ACK 只更新交付水位 |
| A2 | 页 1 包含分配 41，目标水位 42。页 2 先后测试同分配的取消命令和其他分配的命令 | 有取消时不接单。未取消时追平后才可原子提交接单与 Outbox。提交后断网可执行，Cloud 未收到接单事件前仍为 `assigned` |
| S6.1–S6.3 | Cloud 初始分配 seq=41/v1，已收接单和采集。路径 A 先提交取消 seq=42/v2，再收 Edge 的 seq=3、v1 成功回报。路径 B 先提交该回报，再发起取消。另测分配和取消同轮下发且 Edge 未开工 | A 返回 200 `conflict_recorded` 并保留本地事实，Cloud 保持取消。B 成功回报获 `applied` 后，取消返回 409 且无 seq=42。未开工且取消已应用时，执行计数为零 |

### 凭据、安全停止与待发事实

| 向量 | 轨迹 | 期望 |
| --- | --- | --- |
| C1 | Cloud UTC 到期，或断网 35 天后仅得到通用 401 | 暂停同步并保留原事件。待接单任务继续等待，已接单任务仍可运行 |
| C2 | 管理员向同一节点发出经验证的仅撤钥操作 | 停用旧钥并保留离线执行，持续保存新事实。Cloud 拒绝旧钥的重放和收据读取 |
| C3 | 经验证的节点停用或本地安全停机通知，此时同时有已接单待跑任务及运行中任务 | 持久 `safety_hold`、零新开工、运行中任务安全收口，重启保持挂起与原 Outbox。无任务取消命令时不报告 `stopped_by_cancel` |
| C4 | 先更换同 Node 凭据，再按需验证 Registry 恢复和本地解挂。另用不同 Node 身份验证隔离 | 自然过期或仅撤钥可恢复原账本同步。停用路径在 Node 尚未激活时仍被拒绝，激活且新凭据生效后可对账，但有审计的本地解挂前不得开工。其他节点无法使用原队列 |
