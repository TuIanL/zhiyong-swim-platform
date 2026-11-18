# Design

**M4.1 · v1 契约候选 · 待负责人评审**

## Context

### 基线与取证

- GitHub PR #6 于 2026-11-18 10:02:22（北京时间）合并。GitHub `main` 与本次 fetch 后的 `origin/main` 均为 `94fed6b03d50ccca52f6ec959bcde1636148c65c`，两父提交为此前 main `3352c6b` 和最终 PR head `6dcedf8`。工作分支从完整 merge SHA 建立。[PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6) · [Merge commit](https://github.com/TuIanL/zhiyong-swim-platform/commit/94fed6b03d50ccca52f6ec959bcde1636148c65c)
- 合并后 main Push CI Run `44220297894` 的三个 Job 全部成功。原始日志的 checkout SHA 和两份 artifacts 元数据均与合并 SHA 一致。SQLite **210 passed / 92 skipped**，PG17 **281 passed / 21 skipped**，PG 专用实例清理为 `removed`。隔离 RustFS 使用 **ffprobe 6.1.1**，验收和精确清理成功。此结果更新了 Notion 新版入口中 RustFS 仍在运行的时间截面。[main CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894) · [PG 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14389754072) · [RustFS 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14390244558)
- 基线含 144 个受跟踪路径。服务树只有 `services/cloud`，包括一个 Python 3.13/FastAPI 包、SQLAlchemy/Alembic、SQLite/PG17/RustFS 测试和合成 MP4。真正的迁移位于包内，`services/cloud/migrations` 是兼容符号链接，版本为 0001–0004。其余目录为 `.github` CI、`configs`、`scripts`、`docs`、`openspec` 和 `var/.gitkeep`。模型 **19 表**，OpenAPI 快照 **43 paths / 57 operations**（含健康/就绪）。Pose 配置仅记录默认选型。[目录树](https://github.com/TuIanL/zhiyong-swim-platform/tree/94fed6b03d50ccca52f6ec959bcde1636148c65c) · [应用入口](../../../services/cloud/src/swimplatform/main.py) · [模型](../../../services/cloud/src/swimplatform/models.py) · [OpenAPI](../../../docs/contracts/openapi.json)
- 规划前活动 Change 为 0。主规格有 `cloud-identity`、`cloud-edge-registry`、`cloud-training-session`、`cloud-media-asset`、`cloud-media-authorization`、`cloud-media-transfer` 共 6 份。M1/M2/M3 分别对应 PR #4/#5/#6 的 Registry、Session/Asset、Media Transfer 实施归档。此前 PR #3 的领域契约已约定 D4/D10，允许 Edge 保存临时本地记录，正式 Session 的接纳、ID 映射和冲突规则由后续 Change 界定。[主规格](../../specs/) · [M1 归档](../archive/2026-11-11-implement-cloud-edge-device-foundation/) · [M2 归档](../archive/2026-11-14-implement-cloud-session-asset-foundation/) · [M3 归档](../archive/2026-11-16-implement-cloud-media-upload-transfer/) · [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md)
- Notion 项目明确本地优先和统一云端权威。同步 P1 要事务队列、ACK、去重、退避及冲突记录，验收看断网不丢失、重复投递无重复记录及恢复后收敛。部署包 P1 要可重复安装、健康检查、重启及无公网可用，目标 GPU 工作站验证另由负责人安排。07 是草案，内含指令版本、有效期、签名或校验线索。以下契约提议只覆盖一类任务，拟以在线认证/TLS、归属和版本校验约束下发，任务有效期及是否需要独立签名见 Q4。[项目](https://app.notion.com/p/410f602574aa816ea4a6f2b06985d412) · [同步 P1](https://app.notion.com/p/410f602574aa8181a19ae87e25b62b4d) · [Edge 部署包 P1](https://app.notion.com/p/410f602574aa81608463d9de3e26368a) · [07 协议](https://app.notion.com/p/410f602574aa81cda7bff8c3ed483f4d) · [04 Runtime 设计](https://app.notion.com/p/410f602574aa8142a2ecde4eb3a6872a) · [新版工程入口](https://app.notion.com/p/410f602574aa81288834cc297ae5b039)

### 现有能力和缺口

| 基线 | 可复用基础 | M4 缺口 |
| --- | --- | --- |
| Cloud Identity / M1 Registry | User/AuthSession、Tenant/Site 和成员授权。Node、Camera Device 的固定归属与复合外键。Owner/Admin 签发和撤销独立 Edge 凭据，服务端 7 天默认/30 天上限。Heartbeat 只记录观察值，默认 30 秒、在线窗口 90 秒 | Edge 本地服务、数据目录与本地数据库、启动/恢复器、运行时同步客户端、受控凭据装载及本地访问身份。心跳在线状态只供观测 |
| M2 TrainingSession、Asset、授权 | Session 由用户创建，持久记录创建者和 Cloud 状态 `planned → recording → completed` 或合法取消。读权限按现有角色/资源 grant 派生。当前 Edge 可为同场馆已有 Session、所属 Camera 创建上传意图 | TrainingTask / 分配 / 指令版本、Edge 领任务及执行回报、临时 Session 接纳映射、纯采集元数据的云端投影。Session 无 node 归属或同步 revision。当前 Edge 上传路径的同场馆校验不能代替 M4 的分配校验 |
| M3 Media Transfer | UploadSession 与 VideoAsset 受控创建，支持分片签名、确认、续传、异步完成、整对象 SHA-256/大小/媒体探测、`ready` 事务以及授权播放/下载。MediaJob/CleanupCandidate 是媒体专用持久工作 | 通用业务 Outbox/Inbox、节点下发日志、游标、ACK、对账。缺本地分析执行器、AnalysisTask / AnalysisResult / Report 模型和服务身份的结果/发布入口。媒体 worker 的完成只表示媒体处理 |
| 开发及交付 | 已有 SQLite 快速验证、专用 PG17 双后端事务/约束校验，以及真实隔离 RustFS 媒体套件 | 实际 Cloud 与 Edge 进程经网络通信、独立持久卷及断网/重启/失 ACK 故障注入；场馆部署验证单独验收 |

代码入口见 [Edge Registry](../../../services/cloud/src/swimplatform/edge_registry.py) · [Session/Asset API](../../../services/cloud/src/swimplatform/media.py) · [媒体访问](../../../services/cloud/src/swimplatform/media_access.py) · [媒体传输](../../../services/cloud/src/swimplatform/media_transfer.py) · [迁移](../../../services/cloud/src/swimplatform/migrations/versions/) · [CI](../../../.github/workflows/ci.yml)。

## Goals / Non-Goals

首片规格描述一条可复核的闭环。Cloud 为已有 Session 分配一个 TrainingTask 给一个 Node，Edge 持久接收后离线记录合成采集事实和执行终态，重连后更新 Cloud 的独立任务视图。M4.1 交付仅为可评审、可逐场景走读的契约。真实摄像头、算法执行、分析结果摄取、报告发布、权限/配置/模型分发、离线自建 Session 的正式接纳、节点转移及生产选型均留给对应领域 Change。

## Decisions

### D1 数据权威与允许方向

| 对象 | 权威与允许的流向 | 投影规则 |
| --- | --- | --- |
| TrainingSession / TrainingTask | Cloud 持有正式 Session、任务分配与取消。Cloud 下发任务命令。Edge 持有接单、执行与产物事实，可上报接单和终态 | 独立的任务视图从事实推进。Session 的 `status`、标题、创建者以及授权继续由 Cloud 现有操作维护。离线临时 Session 可留本地，接纳需要独立的来源核验和显式 ID 映射 |
| 采集事实 | Edge 生成稳定 `capture_id`，上行所属 Camera、采集时间及最小元数据。Cloud 校验 Tenant/Site/Node、分配、Session 和设备来源 | 入库为业务采集事实，保留原始设备时间与 Cloud 接收时间。未知时钟数据保持未知。本地路径、媒体 URL、原片、图像帧和个人标识均在 v1 白名单外 |
| 上传状态 | Edge 权威仅含本地文件存在性、待传及发送进度。M3 Cloud 持有 UploadSession 状态和对象已验证/可访问事实 | 事件 ACK 与媒体完成、读取授权各走独立状态。Cloud `completing`、已传分片和 Edge 报称上传成功均不足以发布。只有明确授权的媒体走 M3；仍未决定授权策略时，合成闭环只验证元数据。后续若获准传输，同一采集与同一上传尝试持久关联 M3 返回的 asset/upload ID，超时复用原意图键和传输流程 |
| 分析执行 | 未来由 Cloud 分派方固定 `analysis_task_id` 和输入 ID/revision，执行该分配的 Edge 持有运行、失败与成功事实 | M4 v1 的 `training_task.finished` 只表示最小训练工作项结束。未来分析状态须按执行 ID 校验及投影，分析调度、服务身份、输入不可变性与重跑另议 |
| 报告结果 | Edge 保有生成事实及本地版本。未来允许经许可、脱敏且有来源的候选结果上行。Cloud 权威持有接纳、发布版本与云端读权 | 后续绑定输入 revision、pipeline/model/rule/schema 版本与发布授权。v1 无报告内容、结果写入、自动公开权限或派生媒体创建 |
| 节点与权限 | Cloud 下发或管理员配置归属、授权和期望值，Edge 仅能报告观察值 | 现有 `EdgeCredential` 与 User 角色互斥；未来的权限快照、配置或模型分发各有独立契约，保持默认拒绝 |

### D2 v1 信封、流与负载

以下字段名和状态为评审默认值。所有请求使用严格 JSON 对象和字段白名单，受支持的版本为整数 `schema_version=1`。建议每事件上限 8 KiB、下发页最多 50 条，数值宽度采用 JSON 安全整数范围；限额和重试预算见 Q6。上行每请求一事件，避免批次部分提交语义。

| 字段 | 规则 |
| --- | --- |
| `event_id`, `type`, `schema_version` | 生产端首次原子持久化时生成 UUID。重试复用完整信封。事件 ID 在各接收账本内唯一，版本或字段变化需按兼容规则显式处理 |
| `tenant_id`, `site_id`, `edge_node_id` | Cloud 从当前节点凭据绑定取得并逐项校验；Edge 以本机受控绑定核对下行。请求提供的值只是声明 |
| `session_id`, `task_id`, `assignment_id` | Cloud 生成稳定 UUID。任务与 Session 分离。v1 一个 Session 最多一项同步任务、每任务绑定一个节点和一次分配，无自动重派。分配身份关联作用域及父任务 |
| `task_version`, `sequence` | `task_version` 记录 Cloud 命令版本，分配为 1，首次取消为 2；上行回显生成事实时本地已应用的版本。下行 `sequence` 为节点流序号，上行 `sequence` 为分配流序号，两个方向分别从 1 开始严格递增。成功回报或 ACK 不会制造新的命令版本 |
| `occurred_at`, `payload` | `occurred_at` 是生产方声明的 UTC 时刻，用于诊断；Cloud 单独记录 `received_at`。任务竞争、凭据截止和重放排序不取客户端墙钟。载荷只接受下表字段 |

| 方向与类型 | 载荷 | 处理 |
| --- | --- | --- |
| Cloud → Edge `training_task.assigned` | `work_kind=capture_demo`（合成验收工作类型） | 持久保存为待接收。控制追平后提交本地接单记录及上行事件 |
| Cloud → Edge `training_task.cancelled` | `reason` 枚举 `operator_cancelled` / `session_cancelled` | 持久取消。待执行任务停止启动，运行中的任务协作停止 |
| Edge → Cloud `training_task.accepted` | 空对象 | 上行首条。保存本地已接单的事实 |
| Edge → Cloud `capture.recorded` | `capture_id`、`device_id`、可选 `captured_at_utc` 与 `device_observed_at_raw`（≤64 字符） | 每次采集一次 ID，至少记录来源。允许两个时间字段都缺省以表达未知；原始设备时间不被服务端时间填补 |
| Edge → Cloud `training_task.finished` | `outcome=completed/failed/stopped_by_cancel` | 每个接收过的分配最多一次正常执行终态。成功/失败由 Cloud 按当前控制状态和接收顺序投影；已取消后的回报适用 D4 |

接收端按已验证、规范化的不可变信封计算内容指纹。字段顺序和 JSON 空白不改变含义，重复键与未知字段拒绝，UUID 和 UTC 时刻按统一格式规范化，省略的可选字段使用契约规定的单一表示。原始设备时间字符串按原值保留。M4.1 冻结时补充跨语言正反样例。Inbox 主键为 `event_id`，另用作用域、分配及序号做唯一约束；同序号异 ID 和同 ID 异信封均为完整性冲突。采集另按 `(tenant_id, site_id, edge_node_id, assignment_id, capture_id)` 保证同一业务事实只有一份；两个独立采集可有相同文件哈希。请求级 `Idempotency-Key` 继续服务已有管理和上传接口，独立于事件去重。

### D3 事务、传输与 ACK

建议采用 Edge 主动发起的 HTTPS 拉取与回报。Cloud 和 Edge 均以各自持久数据库作为队列与收据的事实源；消息队列和常驻推送服务无需成为首片依赖。

| v1 路由候选 | 请求与响应边界 |
| --- | --- |
| `GET /api/v1/edge/sync/commands?after=0&through=…` | 从本地已持久应用游标读取下一页，只返回当前节点的命令。首请求返回页及固定追平目标 `through`，后续页以该值为上界。快照后新提交的指令下轮获取 |
| `POST /api/v1/edge/sync/command-acks` | `{through: N}` 确认本地连续持久消费到 N。Cloud 推进本节点交付水位但不得回退，返回当前 ACK 水位；超过已知节点流尾的值拒绝 |
| `POST /api/v1/edge/sync/events` | 认证、作用域和信封检查后按序消费。200 携带 `event_id`、`assignment_id`、`sequence`、原处置 `applied / conflict_recorded`、可选有界 `code`。同内容重投返回同一逻辑收据。200 的冲突收据确认已记录和结案，发送端保留冲突线索 |
| `GET /api/v1/edge/sync/reconcile?assignment_id=…` | 返回节点命令头和 ACK 水位。指定本节点分配时附 `next_edge_seq`、`task_version`、`projection_revision`、当前任务状态；无分配查询时只返回节点水位。边缘发送端以当前投影对账，ACK 重放不携带覆盖性任务快照 |

- 先校验当前身份与可见归属，再查旧收据。认证失败 `401 edge_unauthorized`，越范围 `404`。不支持的版本、方向或格式返回 `422`。序号空洞返回 `409 sequence_gap` 及期望序号；事件身份冲突返回 `409 event_conflict`；不可从现存历史恢复的游标返回 `409 recovery_required`。上述错误不推进 Inbox 或交付水位。结构合法、权限匹配但与已提交业务终态冲突的下一条事件，原子记录 `conflict_recorded` 并消费该序号。
- Cloud 任务命令及下发日志同事务提交，序号以事务内节点流计数分配，回滚不留空洞。Edge 连续应用命令时提交 Inbox、命令效果和本地游标，提交后才发送游标 ACK。命令重复接收只返回已持久处理进度。Edge 在追平一轮固定水位且任务未被取消时持久接单，同事务入队 `accepted`，如此即可脱网执行，Cloud 收到 `accepted` 的时间可更晚。
- Edge 每条本地采集或终态与 Outbox 同事务入库。Cloud 将 Inbox 收据、流位置、任务投影或结构化冲突记录同事务提交，再返回收据。发送端只对归属、事件 ID、分配和序号均与待发项匹配的结构化收据标记成功或冲突。同条件重复接收仍计一次业务效果，两个方向都允许至少一次投递。并发重复、重启及超时后仍按已提交结果恢复。
- 发送端每条流只派送头部未确认项，分配间不要求总顺序。超时、断网、429/可重试 5xx 使用带抖动的有上限指数退避，429 尊重服务端提示。耗完一轮预算后保留记录与下一次尝试时机。422、404 或完整性冲突暂停对应流，保留人工诊断入口。永久拒绝不能将原 ID 改载荷重发或跳号。其它分配可继续。
- 重连先用本地游标拉取指令直至固定水位，再补 ACK 和按序重放本地 Outbox。丢 ACK 时用原事件重投取收据。最后读取对账结果，比对双向水位、当前任务投影和本地待发记录。投影依据递增的 `projection_revision` 应用；Cloud ACK 水位只作线索。Cloud 期望序号领先时仍需补取具体收据，不能仅凭水位删除未确认项。已有节点缺少已初始化的本地账本时，启动应挂起并报告恢复需求，禁止自动用空库从零重放。只有已验证为新绑定的节点能初始化零游标。存在无法补齐的本地缺口或超出可重放历史时，同样挂起受影响的节点/分配并人工恢复；v1 无跳游标重置。

### D4 取消、完成及父 Session

- Cloud 任务初态 `assigned`，合法接单投影 `accepted`。其后成功或失败可转为 `completed` 或 `failed`；取消可从 `assigned/accepted` 转为 `cancelled` 并追加控制指令。Edge 回报要求已知的命令版本。回报里的旧版本仍可提交已发生的事实，能否改变任务视图由 Cloud 当前状态决定。回报引用未来版本、缺少接单前置或顺序不合法时拒绝并保留待诊断项。有权且因果合法的迟到事实可写冲突收据。未发布过取消时，`stopped_by_cancel` 无法按正常事实接纳。
- 分配、任务取消、终态投影与父 Session 取消通过父 Session 后任务行的事务序列化，锁后重验作用域和状态。父 Session 先取消时，同事务取消未终结任务并追加取消命令，既有未完成媒体收口按 M3 保持原有顺序。任务先完成时，后到的任务取消返回冲突。合法的父 Session 取消仍按原语义处理，保留既有任务历史。v1 候选只允许在 `planned/recording` Session 新分配任务。独立任务取消只控制该执行分配，M3 已有媒体操作继续依据 Session 及其自身授权。
- Cloud 先取消时，随后合法的成功/失败、迟到接单或采集只写冲突收据与最小审计事实，任务保持 `cancelled`，正常产物视图不会增加。已接单后协作停止可回报 `stopped_by_cancel`，作为已取消分配的观察事实。停止途中已落盘的本地结果保留；取消不会触发本地删除或自动上传。未开始的分配若在同轮补拉发现取消，不应启动也无需生成接单事件。
- 对应的 race 在 PG 必须经独立连接实证。M3 传输与最终发布采用 `Session → UploadSession → Asset → MediaObject → 身份重验`。现有 `media.py` 的 Edge 意图/查询/中止入口却先调用带 Registry 行锁的 `get_edge_identity`，随后锁 Session。与新增父取消路径复用时存在逆序风险，当前结论来自静态调用链。M4.3 必须先验证锁图和实测竞态。建议将跨 Session 的旧 Edge 路径统一为无锁初验、父资源锁定、按需锁节点凭据并取新的服务端 UTC 重验，保持现有响应和幂等语义。同步写入候选顺序为 `Session → 原媒体行（父取消时）→ Task → Node/Credential/Device → 节点流`。单独的节点流读写不反向取得 Session 锁。跨系统操作通过提交后的命令投递，事务内不调用网络服务。

#### 竞态走读样例

```text
Cloud 命令   初始 seq=41 assigned(version=1)；路径 A 追加 seq=42 cancelled(version=2)
Edge 事实    seq=1 accepted(v1), seq=2 capture.recorded(v1), seq=3 finished(completed,v1)

路径 A       Edge 本地完成后重连；Cloud 取消已经提交
             先补拉 seq=42，再上报原 seq=3（确保 1、2 已结案）
             200 conflict_recorded；Cloud 保持 cancelled；本地记录保留

路径 B       Cloud 先提交 seq=3 的 applied，再收到操作者取消
             409 state_conflict；Cloud 保持 completed；无 seq=42

路径 C       Cloud 已消费 seq=3 但响应丢失
             同 UUID/seq/载荷重发，返回原收据；不同载荷返回 event_conflict
             客户端用 reconcile 读取当前投影，任务行与采集事实均无重复
```

### D5 离线与凭据恢复

凭据生命周期沿用 D12，默认 7 天、最大 30 天、服务端 UTC 截止，撤销不可复活。Node 必须 active，检查当前 credential generation，过期恰好截止即拒绝。新增同步入口要在允许读取旧收据之前认证，在提交前串行重验当前节点及资源。曾成功的心跳、历史 ACK 和节点仍在线均不授予额外时间或范围。

已持久接收的任务继续使用本地状态，后续事实照常持久化。断网或节点凭据失效都不自动清空任务、原片及待同步记录。凭据失效后 401 暂停云端同步。35 天离线后，由有权管理员为同一 Node 受控重新签发，经确认的安全渠道更新本机凭据；被停用节点先满足 Registry 的显式恢复规则。新凭据通过现行校验后按原 Node/分配/游标恢复，账本键使用 Node 而非 Credential ID。不同节点、迁场馆和设备身份更换不得继承待发队列。旧媒体上传意图及短期 URL 仍受 M3 自身生命周期和既有接纳/最终授权规则约束，同步 reissue 不复活过期 UploadSession，也不覆盖已终结媒体状态。凭据投递、现场核验和操作审计由负责人确定。

### D6 四个最小 Change

| 次序 / 候选 Change | 独立验收 | 依赖和交接 |
| --- | --- | --- |
| M4.1 `define-cloud-edge-sync-contract`（本提案） | 审阅并冻结方向/信封/schema、ACK/错误、权限/竞态、可复核契约样例和需求矩阵。完成标志为负责人签认及 strict 验证 | 产物供 Edge/Cloud 分别消费，实施和部署另行决策 |
| M4.2 `add-edge-runtime-persistence` | 隔离 CPU 环境可重复启动本地服务并通过健康检查。持久卷存储命令 Inbox、任务/采集事实及 Outbox。用确定性合成执行器和测试契约对端验收无公网执行、重启恢复、崩溃事务、退避和取消。持久化产物用临时目录和故障注入验证 | M4.1；先验收本地 Runtime 最小部署包，Notion P1 的目标工作站、GPU/驱动和实机交付待独立现场验收 |
| M4.3 `add-cloud-sync-inbox-and-projection` | 云端最小授权分配/取消入口、按节点下发日志与 ACK、持久 Inbox、采集和任务窄投影。用协议测试客户端和 PG17 验收归属、重复、并发、Session 取消、凭据与对账。现有 Node/Session 和媒体回归覆盖 | M4.1；可和 M4.2 并行。分配必须经正式 Cloud 写入入口，验收时不直接造 Inbox 或投影状态 |
| M4.4 `verify-cloud-edge-sync-end-to-end` | 两个真实服务进程、各自持久卷、真实 HTTP、可控网络故障。提交前后崩溃、掉线、丢响应、重放、乱序、取消与完成、35 天到期及同节点 reissue 的全链路收敛。合成素材及 M3 隔离媒体回归提供证据 | M4.2 + M4.3；真实指同步双方和持久化，采集/执行使用合成夹具 |

## Risks / Trade-offs

- **队列积压和磁盘损坏** → 可观察地报告待发量、最老待发时长和本地写入失败；磁盘写失败不能宣称已接单或确认。持久卷损坏需要人工恢复。v1 验收持续保留未确认记录，生产容量、保留期限、归档和清理策略另审。
- **两个时钟或两个状态发生分歧** → 客户端采集时间保留原值，顺序只依赖各流版本和 Cloud 事务。取消在 Edge 收到前可能仍在执行，迟到事实留痕。
- **协议长期混用** → 不支持的版本显式失败并保留队列。兼容演进必须通过新版本与灰度策略评审，禁止隐式字段解释或批量补写旧任务。
- **采集事实被当成可见资产** → 元数据、媒体验证、发布与读权分别校验；投影仅给有权的调用者。日志与证据只记录脱敏 ID、错误码和计数。

## Migration Plan

| 层 | 本次文档变更及后续建议 |
| --- | --- |
| M4.1 | API 与数据库影响均为设计约束，当前 0004、19 表、OpenAPI 快照和六份主规格继续作为基线。无数据库迁移、依赖更新、服务注册或数据回填 |
| M4.2 | 独立 Edge 数据目录及版本化 schema，存本地任务、下发游标/Inbox、采集和 Outbox。CPU 隔离验证建议用本地 SQLite 文件。可重复初始化、健康检查、重启和归档恢复使用测试卷。文件写入与数据库提交的边界要有临时落盘和重启补偿，便于识别孤立文件；持久化实现不决定生产数据库 |
| M4.3 | 候选逻辑记录为训练任务/分配、每节点控制计数与 ACK、事务下发日志、事件 Inbox/冲突收据及采集投影。复合 FK 固定 Tenant/Site/Node/Session/Task 关系，唯一约束防重复序号和多次应用，`projection_revision` 在实际状态/投影变更后推进。增量 schema 另立迁移，兼容已有无任务 Session；新记录不默认导入历史数据 |
| API / 兼容 | 候选同期新增两个 Cloud 控制入口 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks` 与其 `/{task_id}/cancel`，仅当期 Owner/Admin、已有有效 Session 与同场馆 active Node 可分配，创建幂等，取消带期望版本、重复取消返回原终态，完成后取消冲突。四个节点同步路由只授权对应方向和所属资源。后续 Delta 明确 Registry 放行，并记录 Session 取消的增量。既有 57 个操作、M3 授权/状态/签名语义继续适用 |
| 交付与回退 | 后续先部署兼容 Cloud 再启用同步，未启用的旧客户端可继续走原接口。出现异常先暂停新分配/同步传输，保留日志、收据及 Edge 卷，回退至能读取当前 schema 和事件的人审版本；不以回退代码为由删除已提交历史。DDL、启动顺序和 schema 回退由实施 Change 细化 |

## 验收环境

- **M4.1** 使用固定合并 SHA、OpenSpec strict、信封正反例走读和逐场景矩阵。Git 差异只应位于本 Change。评审环境无需数据库、容器或视频连接，现有 CI 仅作为 M1–M3 基线证据。
- **M4.2 / M4.3** Edge 使用临时独立文件库和可重启普通 CPU 进程，Cloud 使用现有隔离 SQLite 套件和专用 PG17 实例。两端用同一合成契约向量，PG 竞态用独立连接，以可注入 UTC 时钟演练到期。用失败注入检查提交前无半条状态、提交后重投仍同收据。
- **M4.4** 每次运行使用专用网络和命名卷。断开 Cloud–Edge 链路、丢弃提交后响应、停止并重启进程，测试保留同一持久卷。用 Cloud API 和两边只读数据库断言收敛、计数、状态不回退及没有未授权媒体。观察真实同步过程中没有上传行为；另行获准的合成媒体路径复用现有 RustFS 隔离测试。场馆硬件和学员资料不进入此环境。
- 交付记录包括固定提交、工具/环境版本、用例与场景映射、各端行数/游标与清理结果，CI 应在必选场景零收集或非预期跳过时失败。精确清理本次 run 的容器、网络和卷；日志与 artifacts 不含凭据、带签名 URL、原始视频或真实学员资料。

## Open Questions · 负责人待确认

| 编号 | 待确认决策 | 当前建议和生效点 |
| --- | --- | --- |
| Q1 | v1 任务闭环与控制权限 | 一个已有 Session、单节点、一次分配、一次执行，Owner/Admin 管理。只同步合成任务、采集事实和执行终态。另行决定 Coach、重派、真实采集、AnalysisTask/Report 的范围。冻结前确认 |
| Q2 | 权威、取消规则及离线接纳 | 采用 Cloud 合法终态先提交优先，父 Session 取消联动未终结任务，保留迟到事实；离线临时 Session 留本地，映射另立契约。冻结前确认 |
| Q3 | 凭据恢复流程 | 确认同 Node 受控 reissue，当前授权重验和禁止跨 Node 继承。现场核验人、secret 更新渠道、保管及审计操作另审批；无需修改 D12 |
| Q4 | 传输、下发有效期与签名 | 建议 Edge 主动拉取、认证 TLS 会话内传输、有序版本与持久接收；v1 任务以 Cloud 取消终止接单资格，暂不提供独立任务失效时刻或离线分发签名。07 中的有效期/签名条款需确认本片解释；若需硬截止，先确认可信时钟及已接收离线继续的边界 |
| Q5 | 媒体授权与现场条件 | 保持原片默认本地。明确什么角色可为哪类视频发起 M3 上传，何时可以允许结果或报告上云。场馆硬件、OS/驱动、生产厂商/区域、数据保留/备份/删除与隐私政策另审批 |
| Q6 | 恢复窗口、限额及验收环境 | v1 隔离环境建议 8 KiB/事件、50 条/页，文件库 + PG17。确认重试预算、告警和人工恢复责任。生产数据保留期限仍待决；任何后续裁剪都需先支持明确的游标过期与可试验的修复流程 |
| Q7 | 采集设备停用时的迟到事实 | 建议新采集要求当前 Device active。同归属但已停用设备的迟到事实进入有权冲突记录，既有收据仅在当前节点及资源仍有权时可取。审核是否允许按可证明的采集版本接纳；不同 Node/租户/场馆一律拒绝 |

[Spec Delta](specs/cloud-edge-sync/spec.md) · [验收矩阵](tasks.md)
