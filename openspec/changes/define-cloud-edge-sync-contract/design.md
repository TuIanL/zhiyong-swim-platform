# Design

**M4.1 · 负责人签认记录 · 纯文档 Apply**

## Context

### 基线与取证

- GitHub PR #6 于 2026-11-18 10:02:22（北京时间）合并。GitHub `main` 与本次 fetch 后的 `origin/main` 均为 `94fed6b03d50ccca52f6ec959bcde1636148c65c`，两父提交为此前 main `3352c6b` 和最终 PR head `6dcedf8`。工作分支从完整 merge SHA 建立。[PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6) · [Merge commit](https://github.com/TuIanL/zhiyong-swim-platform/commit/94fed6b03d50ccca52f6ec959bcde1636148c65c)
- 合并后 main Push CI Run `44220297894` 的三个 Job 全部成功。原始日志的 checkout SHA 和两份 artifacts 元数据均与合并 SHA 一致。SQLite **210 passed / 92 skipped**，PG17 **281 passed / 21 skipped**，PG 专用实例清理为 `removed`。隔离 RustFS 使用 **ffprobe 6.1.1**，验收和精确清理成功。此结果更新了 Notion 新版入口中 RustFS 仍在运行的时间截面。[main CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894) · [PG 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14389754072) · [RustFS 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14390244558)
- 基线含 144 个受跟踪路径。服务树只有 `services/cloud`，包括一个 Python 3.13/FastAPI 包、SQLAlchemy/Alembic、SQLite/PG17/RustFS 测试和合成 MP4。真正的迁移位于包内，`services/cloud/migrations` 是兼容符号链接，版本为 0001–0004。其余目录为 `.github` CI、`configs`、`scripts`、`docs`、`openspec` 和 `var/.gitkeep`。模型 **19 表**，OpenAPI 快照 **43 paths / 57 operations**（含健康/就绪）。Pose 配置仅记录默认选型。[目录树](https://github.com/TuIanL/zhiyong-swim-platform/tree/94fed6b03d50ccca52f6ec959bcde1636148c65c) · [应用入口](../../../services/cloud/src/swimplatform/main.py) · [模型](../../../services/cloud/src/swimplatform/models.py) · [OpenAPI](../../../docs/contracts/openapi.json)
- 规划前活动 Change 为 0。主规格有 `cloud-identity`、`cloud-edge-registry`、`cloud-training-session`、`cloud-media-asset`、`cloud-media-authorization`、`cloud-media-transfer` 共 6 份。M1/M2/M3 分别对应 PR #4/#5/#6 的 Registry、Session/Asset、Media Transfer 实施归档。此前 PR #3 的领域契约已约定 D4/D10，允许 Edge 保存临时本地记录，正式 Session 的接纳、ID 映射和冲突规则由后续 Change 界定。[主规格](../../specs/) · [M1 归档](../archive/2026-11-11-implement-cloud-edge-device-foundation/) · [M2 归档](../archive/2026-11-14-implement-cloud-session-asset-foundation/) · [M3 归档](../archive/2026-11-16-implement-cloud-media-upload-transfer/) · [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md)
- Notion 项目明确本地优先和统一云端权威。同步 P1 要事务队列、ACK、去重、退避及冲突记录，验收看断网不丢失、重复投递无重复记录及恢复后收敛。部署包 P1 要可重复安装、健康检查、重启及无公网可用，目标 GPU 工作站验证另由负责人安排。07 是草案，内含指令版本、有效期、签名或校验线索。v1 签认范围为单一合成任务类型，Q4 决定以有效身份的 HTTPS/TLS 拉取与版本校验下发。[项目](https://app.notion.com/p/410f602574aa816ea4a6f2b06985d412) · [同步 P1](https://app.notion.com/p/410f602574aa8181a19ae87e25b62b4d) · [Edge 部署包 P1](https://app.notion.com/p/410f602574aa81608463d9de3e26368a) · [07 协议](https://app.notion.com/p/410f602574aa81cda7bff8c3ed483f4d) · [04 Runtime 设计](https://app.notion.com/p/410f602574aa8142a2ecde4eb3a6872a) · [新版工程入口](https://app.notion.com/p/410f602574aa81288834cc297ae5b039)

### 已批准边界、待决设计与实施状态

| 状态 | 内容与凭据 |
| --- | --- |
| 已批准的既有边界 | 本地优先，已业务接单的任务可离线继续，原片默认留场馆，获准传输沿用 M3。Session 最终状态及离线临时记录继承 ADR 0003 D4/D10。D12 的服务端 UTC、7 天默认/30 天上限、撤销不可恢复、受控签发及禁止自动续期已批准。[ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) · [Notion 决策记录](https://app.notion.com/p/410f602574aa81618d05efd317151022) · [Registry 主规格](../../specs/cloud-edge-registry/spec.md) |
| 本轮明确的交付边界 | M4.1 为纯文档契约，沿用 `skip_specs: true`。候选需求、样例和矩阵随 Change 留存。后续 M4.2/M4.3 分别起草并审查行为 Delta。[纯文档先例](../archive/2026-11-10-define-cloud-capture-media-contracts/proposal.md) |
| 已批准的 M4 v1 设计方向 | Q1=A、Q2=A、Q3=A、Q4=A、Q5=B、Q6=A、Q7=A。实施参数和外部政策的待决边界见签认表。 |
| 实施满足 | 文档签认和 OpenSpec strict 证明可评审与结构正确。M4.2/M4.3 各自凭实现和对应的测试证据判断所负责条款是否满足，双向同步的系统行为由 M4.4 验收。 |

### 现有能力和缺口

| 基线 | 可复用基础 | M4 缺口 |
| --- | --- | --- |
| Cloud Identity / M1 Registry | User/AuthSession、Tenant/Site 和成员授权。Node、Camera Device 的固定归属与复合外键。Owner/Admin 签发和撤销独立 Edge 凭据，服务端 7 天默认/30 天上限。Heartbeat 只记录观察值，默认 30 秒、在线窗口 90 秒 | Edge 本地服务、数据目录与本地数据库、启动/恢复器、运行时同步客户端、受控凭据装载及本地访问身份。心跳在线状态只供观测 |
| M2 TrainingSession、Asset、授权 | Session 由用户创建，持久记录创建者和 Cloud 状态 `planned → recording → completed` 或合法取消。读权限按现有角色/资源 grant 派生。当前 Edge 可为同场馆已有 Session、所属 Camera 创建上传意图 | TrainingTask / 分配 / 指令版本、Edge 领任务及执行回报、临时 Session 接纳映射、纯采集元数据的云端投影。Session 无 node 归属或同步 revision。当前 Edge 上传路径的同场馆校验不能代替 M4 的分配校验 |
| M3 Media Transfer | UploadSession 与 VideoAsset 受控创建，支持分片签名、确认、续传、异步完成、整对象 SHA-256/大小/媒体探测、`ready` 事务以及授权播放/下载。MediaJob/CleanupCandidate 是媒体专用持久工作 | 通用业务 Outbox/Inbox、节点下发日志、游标、ACK、对账。缺本地分析执行器、AnalysisTask / AnalysisResult / Report 模型和服务身份的结果/发布入口。媒体 worker 的完成只表示媒体处理 |
| 开发及交付 | 已有 SQLite 快速验证、专用 PG17 双后端事务/约束校验，以及真实隔离 RustFS 媒体套件 | 实际 Cloud 与 Edge 进程经网络通信、独立持久卷及断网/重启/失 ACK 故障注入；场馆部署验证单独验收 |

代码入口见 [Edge Registry](../../../services/cloud/src/swimplatform/edge_registry.py) · [Session/Asset API](../../../services/cloud/src/swimplatform/media.py) · [媒体访问](../../../services/cloud/src/swimplatform/media_access.py) · [媒体传输](../../../services/cloud/src/swimplatform/media_transfer.py) · [迁移](../../../services/cloud/src/swimplatform/migrations/versions/) · [CI](../../../.github/workflows/ci.yml)。

## Goals / Non-Goals

签认契约描述一条可复核的闭环。Cloud 为已有 Session 分配一个 TrainingTask 给一个 Node，Edge 持久接收命令并业务接单后可离线记录合成采集事实和执行终态，重连后更新 Cloud 的独立任务视图。M4.1 交付仅为可评审、可逐场景走读的契约。真实摄像头、算法执行、分析结果摄取、报告发布、权限/配置/模型分发、离线自建 Session 的正式接纳、节点转移及生产选型均留给对应领域 Change。

## Decisions

### D1 数据权威与允许方向

| 对象 | 权威与允许的流向 | 投影规则 |
| --- | --- | --- |
| TrainingSession / TrainingTask | Cloud 持有正式 Session、任务分配与取消。Cloud 下发任务命令。Edge 持有接单、执行与产物事实，可上报接单和终态 | 独立的任务视图从事实推进。Session 的 `status`、标题、创建者以及授权继续由 Cloud 现有操作维护。离线临时 Session 可留本地，接纳需要独立的来源核验和显式 ID 映射 |
| 采集事实 | Edge 生成稳定 `capture_id`，上行所属 Camera、采集时间及最小元数据。Cloud 校验 Tenant/Site/Node、分配、Session 和设备来源 | 入库为业务采集事实，保留原始设备时间与 Cloud 接收时间。未知时钟数据保持未知。本地路径、媒体 URL、原片、图像帧和个人标识均在 v1 白名单外 |
| 上传状态 | Edge 权威仅含本地文件存在性、待传及发送进度。M3 Cloud 持有 UploadSession 状态和对象已验证/可访问事实 | 事件 ACK 与媒体完成、读取授权各走独立状态。Cloud `completing`、已传分片和 Edge 报称上传成功均不足以发布。原片默认本地。Q5 B 将显式人工批准的合成视频 M3 上传纳入 M4.4 必验路径。审批绑定 Session、具体资产、目的和现行授权。复用原意图键和 M3 的 asset/upload ID |
| 人工上传批准 | M4.4 测试操作人在事件流之外对具体 Session、合成视频及目的做出显式批准，发起主体须通过 M3 当前授权 | 记录批准与资产绑定，事件 ACK、接单或终态均不生成批准。生产审批人、隐私、保留策略另审 |
| 分析执行 | 未来由 Cloud 分派方固定 `analysis_task_id` 和输入 ID/revision，执行该分配的 Edge 持有运行、失败与成功事实 | M4 v1 的 `training_task.finished` 只表示最小训练工作项结束。未来分析状态须按执行 ID 校验及投影，分析调度、服务身份、输入不可变性与重跑另议 |
| 报告结果 | Edge 保有生成事实及本地版本。未来允许经许可、脱敏且有来源的候选结果上行。Cloud 权威持有接纳、发布版本与云端读权 | 后续绑定输入 revision、pipeline/model/rule/schema 版本与发布授权。v1 无报告内容、结果写入、自动公开权限或派生媒体创建 |
| 节点与权限 | Cloud 下发或管理员配置归属、授权和期望值，Edge 仅能报告观察值 | 现有 `EdgeCredential` 与 User 角色互斥；未来的权限快照、配置或模型分发各有独立契约，保持默认拒绝 |

#### Q5 B 的独立媒体链路

```text
Edge 原片 + 采集事实
  |-- M4 事件 Outbox --> Cloud Inbox/收据 --> 采集/任务投影
  +-- 人工明确批准具体 Session、资产与目的
      --> 现有 M3 授权 --> UploadSession / pending_upload
      --> 分片与续传 --> completing --> M3 整对象验证 --> ready
```

每次合成测试批准先绑定待传本地资产的稳定标识、预期 SHA-256 与大小、Tenant/Site/Session、上传目的和当前授权主体。M3 新建上传意图原子分配云端 Asset ID 后，将返回的 `asset_id`/`upload_session_id` 与这次批准及同一原件绑定。隔离测试可以用具有当前 S-manage 的 User 通过用户侧 M3 API 明确发起，其同一发起身份继续上传，Edge 同步身份不获 User 令牌或额外媒体权限。当前 M3 允许的 Edge 上传路径仍遵守原发起节点及有效设备边界。授权失效阻止新的授权及正常发布，已签 URL 受原 TTL 约束。仅 M3 对精确对象版本验证 SHA-256、大小和媒体有效性后可提交 `ready`。本地原件保留。

M4.4 使用隔离 RustFS、合成 MP4 与测试身份验收 M1–M6。这里的人工批准用测试编排记录和显式动作表达。真实数据审批角色及记录产品规则、采集/传输授权、未成年人监护人同意、生产存储/区域/访问控制以及保留、备份、删除、撤回与审计均需另批。[M3 接口契约](../../../docs/contracts/cloud-capture-media.md) · [验收矩阵](tasks.md)

### D2 v1 信封、流与负载

v1 请求使用严格 JSON 对象和字段白名单，事件版本为整数 `schema_version=1`。已签认的单事件上限为 8 KiB，每个下发页最多 50 条，整数使用 JSON 安全整数范围。Q6 尚未签认具体超时和退避预算。上行每请求一事件，避免批次部分提交语义。

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
| Edge → Cloud `training_task.finished` | `outcome=completed/failed/stopped_by_cancel` | 每个接收过的分配最多一次正常执行终态。成功/失败由 Cloud 按当前控制状态和接收顺序投影；已取消后的回报适用 D4 |

接收端按已验证、规范化的不可变信封计算内容指纹。字段顺序和 JSON 空白不改变含义，重复键与未知字段拒绝，UUID 规范为小写连字符格式，UTC 时刻统一为等义的 Z 表示，可选时间字段缺失时统一省略，显式 null 拒绝。原始设备时间字符串按原值保留。规范化正反例见[契约样例](candidate-contract.md#协议样例)。Inbox 主键为 `event_id`，另用作用域、分配及序号做唯一约束；同序号异 ID 和同 ID 异信封均为完整性冲突。采集另按 `(tenant_id, site_id, edge_node_id, assignment_id, capture_id)` 保证同一业务事实只有一份；两个独立采集可有相同文件哈希。请求级 `Idempotency-Key` 继续服务已有管理和上传接口，独立于事件去重。

### D3 事务、传输与 ACK

| 概念 | 持久边界 | 可证明的事实 |
| --- | --- | --- |
| 持久接收 | Edge 事务提交命令 Inbox、命令本地效果（如待接单或取消标记）及连续游标 | 此命令已可从本地账本恢复。收包、解析或尚未提交的事务均不足以推进游标 |
| Command ACK | Edge 在上一步提交后发送 `through`，Cloud 记录已确认命令水位 | 此水位以内的命令已在 Edge 连续持久应用。Command ACK 丢失可重发，ACK 成功与否不影响已经持久化的本地接单 |
| 业务接单 | 追平一轮固定水位后，在本地确认任务未取消、无安全挂起且接单资格已在本轮有效同步中得到确认。事务写入本地已接单状态与 `training_task.accepted` Outbox | 允许离线调度该任务。Cloud 只有提交上行 `accepted` 事件后才能把任务投影为 `accepted`。若追平前断网或失去有效认证，本轮待接单项留待下次认证同步 |
| 实际执行 | Edge 调度器在分配级串行化下复核已接单、无已应用取消、无安全挂起，持久取得执行资格，用相同执行身份启动。重启按检查点恢复或转人工 | 执行由本地状态与执行器证据证明。v1 无独立上行开始执行事件；接单回报、Command ACK 和 HTTP 200 均不能证明实际开工 |

Cloud 对上行事件的收据独立于 Command ACK。上行收据只确认指定事件已投影或已记录冲突。

Q4 确认 Edge 使用有效节点身份主动发起 HTTPS/TLS 拉取与回报。Cloud 和 Edge 均以各自持久数据库作为队列与收据的事实源；消息队列和常驻推送服务无需成为首片依赖。

| v1 路由候选 | 请求与响应边界 |
| --- | --- |
| `GET /api/v1/edge/sync/commands?after=0&through=…` | 从本地已持久应用游标读取下一页，只返回当前节点的命令。首请求返回页及固定追平目标 `through`，后续页以该值为上界。快照后新提交的指令下轮获取 |
| `POST /api/v1/edge/sync/command-acks` | `{through: N}` 确认本地连续持久消费到 N。Cloud 推进本节点交付水位但不得回退，返回当前 ACK 水位；超过已知节点流尾的值拒绝 |
| `POST /api/v1/edge/sync/events` | 认证、作用域和信封检查后按序消费。200 携带 `event_id`、`assignment_id`、`sequence`、原处置 `disposition=applied/conflict_recorded`、可选有界 `code`。同内容重投返回同一逻辑收据。200 的冲突收据确认已记录和结案，发送端保留冲突线索 |
| `GET /api/v1/edge/sync/reconcile?assignment_id=…` | 返回节点命令头和 ACK 水位。指定本节点分配时附 `next_edge_seq`、`task_version`、`projection_revision`、当前任务状态；无分配查询时只返回节点水位。边缘发送端以当前投影对账，ACK 重放不携带覆盖性任务快照 |

- 先校验当前身份与可见归属，再查旧收据。认证失败 `401 edge_unauthorized`，越范围 `404`。不支持的版本、方向或格式返回 `422`。序号空洞返回 `409 sequence_gap` 及期望序号；事件身份冲突返回 `409 event_conflict`；不可从现存历史恢复的游标返回 `409 recovery_required`。上述错误不推进 Inbox 或交付水位。结构合法、权限匹配但与已提交业务终态冲突的下一条事件，原子记录 `conflict_recorded` 并消费该序号。
- Cloud 任务命令及下发日志同事务提交，序号以事务内节点流计数分配，回滚不留空洞。Edge 连续应用命令时提交 Inbox、命令效果和本地游标，提交后才发送游标 ACK。命令重复接收只返回已持久处理进度。业务接单和调度按本节四个边界推进。
- Edge 每条本地采集或终态与 Outbox 同事务入库。Cloud 将 Inbox 收据、流位置、任务投影或结构化冲突记录同事务提交，再返回收据。发送端只对归属、事件 ID、分配和序号均与待发项匹配的结构化收据标记成功或冲突。同条件重复接收仍计一次业务效果，两个方向都允许至少一次投递。并发重复、重启及超时后仍按已提交结果恢复。
- 发送端每条流只派送头部未确认项，分配间不要求总顺序。超时、断网、429/可重试 5xx 使用带抖动的有上限指数退避，429 尊重服务端提示。耗完一轮预算后保留记录与下一次尝试时机。422、404 或完整性冲突暂停对应流，保留人工诊断入口。永久拒绝不能将原 ID 改载荷重发或跳号。其它分配可继续。
- 重连先用本地游标拉取指令直至固定水位，再补送 Command ACK 并按序重放本地 Outbox。Command ACK 丢失时重发已持久接收的水位。上行收据丢失时重投原事件。最后读取对账结果，比对双向水位、当前任务投影和本地待发记录。投影依据递增的 `projection_revision` 应用；Cloud ACK 水位只作线索。Cloud 期望序号领先时仍需补取具体收据，不能仅凭水位删除未确认项。已有节点缺少已初始化的本地账本时，启动应挂起并报告恢复需求，禁止自动用空库从零重放。只有已验证为新绑定的节点能初始化零游标。存在无法补齐的本地缺口或超出可重放历史时，同样挂起受影响的节点/分配并人工恢复；v1 无跳游标重置。

### D4 云端任务控制与终态

#### 创建并指派

- 候选入口为 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks`。只允许当前有效 User 会话及目标 Tenant 的 Owner/Admin。无效会话或 Edge 凭据返回 `401`。非成员、不可见 Site、越 Tenant/Site 的 Session、Node 或任务以 `404` 隐藏。同场馆可见但无管理角色的 Coach/Athlete 返回 `403`，Session/Asset 读 grant 不增加控制权限。
- 请求含 `session_id`、`edge_node_id`、`work_kind=capture_demo` 与 `Idempotency-Key`。结构、缺键、非法键和未知字段返回 `422`。对于新写入，在锁后按已有任务、父 Session 状态、Node 状态的顺序校验。已存在任务按 `task_exists` 处理。无现存任务时要求父 Session 属于路径 Tenant/Site 且为 `planned` 或 `recording`，Node 同场馆且为 `active`。Session 已完成或取消，或可见 Node 的行政状态非 active，返回 `409 state_conflict`。心跳 `online` 只供观测。
- 一次提交创建 `task_id`、`assignment_id`、初态 `assigned`、`task_version=1`、节点序号、`training_task.assigned` 下发记录和请求收据，成功返回 `201` 与含任务/分配标识、初态、初始版本及命令序号的收据。任何一项失败则全部回滚，禁止创建未分配的任务或单独重派。
- Q1 确认**整个 v1 生命周期唯一**。同 `(tenant_id, site_id, session_id)` 最多一个任务，同任务最多一个分配，均以数据库唯一约束保护。任务成为 `completed`、`failed` 或 `cancelled` 后仍占名额，任何新键再建均返回 `409 task_exists`。新训练如需另起任务应对应真实的新 Session。采用活动任务唯一须先重审 Q1、更改约束和测试，实施不得自行切换。
- 创建和取消键都按 `(tenant_id, site_id, user_id, operation, key_digest)` 隔离。先校验当前会话、角色及请求目标可见归属，再查当前作用域收据。同键同规范化参数重放原成功状态和逻辑收据，即使节点或 Session 此后已终结；收据不是当前任务视图。同键异参（含目标、Node 或期望版本）返回 `409 idempotency_conflict`。仅在未命中成功收据时评估新操作的状态门槛。并发主键/唯一冲突应回滚并按当前授权解释为重放或冲突，收据和副作用均至多一次。创建与取消为不同 operation。

#### 取消与竞争

- 候选入口为 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks/{task_id}/cancel`，使用相同控制权限和 `Idempotency-Key`。请求只接收 `expected_task_version` 正整数。服务端设置 `operator_cancelled`，父 Session 取消联动路径使用 `session_cancelled`。指定任务必须属于受权的场馆。停用节点的任务仍可由有权操作人取消。
- `assigned/accepted` 且期望版本匹配时，同事务写入 `cancelled`、递增到 v2、追加唯一取消命令并保存收据。返回 `200` 和包含 `task_id`、`assignment_id`、`status`、`task_version`、`sequence`、`cancelled_at`、`reason` 的收据。同键同参重放返回原收据。同键异参先按幂等冲突处理。已取消任务用新键、期望版本为取消前版本或当前取消版本时，返回原取消结果，取消版本、时间、原因和命令数量保持一致。可取消或已取消的任务遇到其它期望版本时返回 `409 version_conflict`。`completed/failed` 的新取消返回 `409 state_conflict`，无任务或命令写入。
- 分配、终态投影及父 Session 取消先序列化父 Session，再锁受影响的任务行。先提交的合法终态生效。父 Session 先取消时，同事务取消未终结任务并追加命令，同时按既有 M3 语义收口未完成媒体。任务先完成时，合法的父 Session 取消继续独立处理，保留任务和既有媒体历史。单独任务取消只控制该分配。
- Cloud 已取消时，合规的迟到接单、采集及成功/失败回报写冲突收据与最小审计事实，普通投影保持取消。上行允许引用已知历史命令版本，拒绝未来版本或缺少因果前置的事件。只有收到并持久应用对应任务取消指令才可回报 `stopped_by_cancel`。本地安全挂起按 D5 处理。

#### 锁依赖图与 M4.3 PostgreSQL 验收

箭头表示同一事务持有左侧行锁后尝试获取右侧锁。图来自静态调用链，两条路径可能针对同一 Session 和 Node，尚待 PG 独立连接实证。

```text
基线 A  Edge 上传意图 / 查询 / 中止
        Node --> Credential --> Session [--> UploadSession]
        media.py: get_edge_identity() --> lock_session(_upload)

基线 B  M3 分片转移 / 完整对象最终发布
        Session --> UploadSession --> Asset --> MediaObject --> Node --> Credential
        media_transfer.py: _lock_transfer() --> lock_edge_identity() / _accepted_identity_valid()

依赖环  Node --> Session --> ... --> Node
```

M4.3 候选锁序以受限初验读取发现归属，先锁 `Session`，父取消沿既有 M3 顺序锁 `UploadSession → Asset → MediaObject`，再锁受影响的 `Task`，随后统一取得必要的 `Node → Credential → Device` 锁并以新鲜服务端 UTC 和当前状态重验，最后锁节点命令水位/写对应收据。上传路径按适用层级取锁。已持有 Registry 或流锁的纯节点操作不得再取 Session 锁。父取消和多行写入按稳定主键顺序。网络 I/O 在事务边界之外。若 PG 实证另有锁依赖，M4.3 必须完成对应的锁序设计和兼容回归。

验收使用可销毁 PG17、真实 API/worker、至少两个独立 DB 连接和可控制顺序的测试屏障。要求用例实际相交于同一组资源，并交换先提交方。启用有界等待，任何死锁 `40P01` 或锁/测试超时均使必选用例失败，不能由应用重试掩盖。校验事务结束后的行数、状态、版本、游标、命令和收据，测试报告记录覆盖的顺序。

| ID | 必选竞态及断言 |
| --- | --- |
| L1 | 同一 Session + Node 的 Edge 上传意图、查询、中止分别与需要节点锁的 Cloud 路径交错，覆盖 M3 传输/最终发布与新增父取消路径。精确确认父先锁顺序、无反向等待、无残留，以及既有 M3 状态/授权结果。 |
| L2 | 同 Session 的并发创建/分配（同键、异键）、新任务与父取消。只允许一个任务、一个分配、一条分配命令，失败不占流序号。先取消父 Session 时不得创建任务。 |
| L3 | 任务取消/父 Session 取消与终态投影双顺序。Cloud 只有一个合法终态及至多一条取消命令，后到合规事实只有收据/审计。父取消对 M3 的 `completing` 与已 `ready` 表现符合既有契约。 |
| L4 | 凭据撤销、节点停用或等待行锁期间恰好过期与 Inbox 投影/重放竞争。撤权先提交或重验时已到期则 `401`，不推进水位，不泄露旧收据。接收先合法提交时保留原收据历史。 |

证据入口见 [旧 Edge 身份和上传路径](../../../services/cloud/src/swimplatform/media.py) · [Registry 行锁与无锁初验](../../../services/cloud/src/swimplatform/edge_registry.py) · [M3 传输及最终发布](../../../services/cloud/src/swimplatform/media_transfer.py)。

### D5 离线、撤权与安全停止

D12 的有效期以 Cloud 服务端 UTC 判断，到期、撤销和停用均拒绝同步及旧收据读取。提交和收据查询前复核 Node active、凭据 generation 和作用域。曾成功的心跳和历史 ACK 不授予额外时间或范围。

| 可知原因 | 本地执行和安全停止（Q3 已批准） | 队列与恢复 |
| --- | --- | --- |
| 断网、已知自然过期，或仅收到无法区分原因的 `401` | 暂停同步，保留已业务接单任务的本地运行资格（含尚未开工的已接单任务）。待接单任务等待有效控制流。通用 401 仅视为认证失败并告警，不能推断节点停用 | 保留原片、检查点、已应用命令、Inbox/Outbox 和原事件 ID。Cloud 拒绝该凭据后的请求，等待同 Node 受控签发并按原游标对账 |
| 已验证的人工撤销，仅针对凭据 | 停用该凭据、暂停云端同步。已接单任务继续本地运行。若撤销同时包含已验证的本地停机指令，则按下一行进入安全挂起 | 同一 Node 可用受控新凭据恢复同步。撤销不可复活，保存此期间本地生成的待发事实 |
| 已验证的节点停用，或有权操作者明确要求安全停机 | 持久设置本地安全挂起。禁止所有新开工，含已接单未开工项。通知运行中的任务检查点停机，无法确认安全结束时保持 `safety_hold` 及待人工状态。重启继续阻止开工 | 保存检查点、原片和待发事实，不伪造任务完成/取消。仅当真正应用任务取消命令才可报 `stopped_by_cancel`。停用节点须符合 Registry 显式恢复并使用同 Node 新凭据。重开工须另有审计的本地解挂；已终结或已取消的执行不恢复 |

M4 v1 不假设断网 Edge 实时收到管理变更。可信状态来自受控的本地操作或经授权验证的管理通知，可信通知通道、现场核验、凭据安全交付和解挂审计的实现方式留 M4.2/M4.3 审查；不从 401、心跳中断或未认证信号伪造状态。35 天原凭据必过期，队列绑定 Node 而非 Credential ID，迁场馆或新节点不得继承。旧媒体上传会话及短期 URL 继续受 M3 自己的有效期和授权约束。

### D6 四个最小 Change

| 次序 / 候选 Change | 独立验收 | 依赖和交接 |
| --- | --- | --- |
| M4.1 `define-cloud-edge-sync-contract`（本提案） | 交付候选契约、样例、决策记录和验收矩阵。文档冻结以负责人签认及 strict 验证为准 | 产物供 Edge/Cloud 分别消费，实施和部署另行决策 |
| M4.2 `add-edge-runtime-persistence` | 隔离 CPU 环境可重复启动本地服务并通过健康检查。持久卷存储命令 Inbox、任务/采集事实及 Outbox。用确定性合成执行器和测试契约对端验收无公网执行、重启恢复、崩溃事务、退避和取消。持久化产物用临时目录和故障注入验证 | M4.1 文档签认后，先在实施 Change 声明本地行为 Delta，再验收 Runtime 最小部署包，Notion P1 的目标工作站、GPU/驱动和实机交付待独立现场验收 |
| M4.3 `add-cloud-sync-inbox-and-projection` | 云端最小授权分配/取消入口、按节点下发日志与 ACK、持久 Inbox、采集和任务窄投影。用协议测试客户端和 PG17 验收归属、重复、并发、Session 取消、凭据与对账。现有 Node/Session 和媒体回归覆盖 | M4.1 文档签认后声明 Cloud 行为 Delta，可和 M4.2 并行。分配必须经正式 Cloud 写入入口，验收时不直接造 Inbox 或投影状态 |
| M4.4 `verify-cloud-edge-sync-end-to-end` | 两个真实服务进程、各自持久卷、真实 HTTP、可控网络故障。提交前后崩溃、掉线、丢响应、重放、乱序、取消与完成、35 天到期及同节点 reissue 的全链路收敛。另以隔离 RustFS 必验人工批准的合成 MP4 经现有 M3 完成上传、续传、校验及撤权检查（M1–M6） | M4.2 + M4.3；真实指同步双方和持久化，采集/执行使用合成夹具 |

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
| M4.3 | 候选逻辑记录为训练任务/分配、每节点控制计数与 ACK、事务下发日志、事件 Inbox/冲突收据及采集投影。复合 FK 固定 Tenant/Site/Node/Session/Task 关系，唯一约束固定全生命周期单任务/单分配并防重复序号和多次应用，`projection_revision` 在实际状态/投影变更后推进。增量 schema 另立迁移，兼容已有无任务 Session；新记录不默认导入历史数据 |
| API / 兼容 | 候选同期新增两个 Cloud 控制入口 `POST /api/v1/tenants/{tenant_id}/sites/{site_id}/training-tasks` 与其 `/{task_id}/cancel`，其权限、状态、幂等与取消语义详见 D4。四个节点同步路由只授权对应方向和所属资源。后续 Delta 明确 Registry 放行，并记录 Session 取消的增量。既有 57 个操作、M3 授权/状态/签名语义继续适用 |
| 交付与回退 | 后续先部署兼容 Cloud 再启用同步，未启用的旧客户端可继续走原接口。出现异常先暂停新分配/同步传输，保留日志、收据及 Edge 卷，回退至能读取当前 schema 和事件的人审版本；不以回退代码为由删除已提交历史。DDL、启动顺序和 schema 回退由实施 Change 细化 |

## 验收环境

- **M4.1** 使用固定合并 SHA、OpenSpec strict、信封正反例走读和逐场景矩阵。Git 差异只应位于本 Change。评审环境无需数据库、容器或视频连接，现有 CI 仅作为 M1–M3 基线证据。
- **M4.2 / M4.3** Edge 使用临时独立文件库和可重启普通 CPU 进程，Cloud 使用现有隔离 SQLite 套件和专用 PG17 实例。两端用同一合成契约向量，PG 竞态用独立连接，以可注入 UTC 时钟演练到期。用失败注入检查提交前无半条状态、提交后重投仍同收据。
- **M4.4** 每次运行使用专用网络和命名卷。断开 Cloud–Edge 链路、丢弃提交后响应、停止并重启进程，测试保留同一持久卷。用 Cloud API 和两边只读数据库断言收敛、计数、状态不回退及没有未授权媒体。在未获批准分支观测不存在上传行为，再用显式人工批准的独立分支复用 M3 上传合成 MP4。固定对象版本、撤权与本地原件留存都要单独取证。场馆硬件和学员资料不进入此环境。
- 交付记录包括固定提交、工具/环境版本、用例与场景映射、各端行数/游标与清理结果，CI 应在必选场景零收集或非预期跳过时失败。精确清理本次 run 的容器、网络和卷；日志与 artifacts 不含凭据、带签名 URL、原始视频或真实学员资料。

## Q1–Q7 负责人签认

<a name="decision-signoff"></a>

记录日期 **2026-11-18（Asia/Shanghai）**。批准来源为本次负责人明确授权纯文档 Apply 的请求。签认对应 [二轮评审 Head](https://github.com/TuIanL/zhiyong-swim-platform/commit/a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b) 及 [Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7)。业务选择统一为 **Q1=A、Q2=A、Q3=A、Q4=A、Q5=B、Q6=A、Q7=A**。

| 决策 | 原 A / B 候选 | 已批准 v1 选择 | 对 DB、API、Edge 和验收的影响 | 仍待确认 |
| --- | --- | --- | --- | --- |
| Q1 | A 全生命周期唯一，仅 Owner/Admin；B 仅活动任务唯一，扩展控制权限需另审 | **A**。一个 Session 最多一个 Task、Task 最多一次 Assignment，固定一个 Node，终态占位，首跑 `capture_demo` | M4.3 同事务创建任务、分配、命令和收据。唯一约束、权限、幂等和重复取消按 D4 / T1–T9 / L2 | 多任务、多次分析和重派后续另议 |
| Q2 | A 父取消联动、合法先提交终态；B 显式任务取消、父取消单独协调 | **A**。Cloud 控制，Edge 报事实。迟到合规事实与冲突收据留存，完成历史保留，离线临时 Session 留本地 | M4.2 取消消费，M4.3 Cloud 投影和父事务，M4.4 竞态，保持 M3 终态与 ready 兼容 | 临时 Session 正式接纳及 ID 映射另议 |
| Q3 | A 仅撤钥继续本地运行，可信停用/停机触发安全挂起；B 撤钥亦挂起或另增管理通道 | **A**。断网/自然过期/仅撤钥时已接单任务继续。经验证的停用或本地停机持久挂起，保留事实和检查点。D12 继续适用 | M4.2 安全停止、解挂及重启，M4.3 现行凭据重验和 Registry 恢复，C1–C4/L4 | 可信通知、现场核验、凭据交付与解挂实现；完全离线无法保证及时收到远端停用 |
| Q4 | A HTTPS/TLS 拉取 + 固定水位；B 独立签名和未接单硬截止 | **A**。有效认证、连号、版本及载荷校验，无逐命令签名或独立任务硬截止 | M4.2/M4.3 区分持久接收、Command ACK、业务接单、实际执行。A1/A2，尚未送达取消不视为 Edge 已停止 | 各实现的调度及事务细节按 D3、Q6 验证 |
| Q5 | A 首版只验元数据，上传另行获准；B 在明确人工批准后纳入媒体验证 | **B**。M4.4 必验经过人工批准的合成 MP4 上传。原片默认本地，事件、执行终态及收据均不触发上传 | 现有 M3 权限、UploadSession、分片、续传及整对象验证，M1–M6 验收，无 M4 媒体授权扩展 | 真实审批人/记录产品规则、真实个人信息和监护人授权、生产存储/区域/访问控制、保留、备份、删除、撤回、审计 |
| Q6 | A 限额、持久化与人工恢复；B 改分页预算或带快照裁剪 | **A**。8 KiB/事件、50 条/页、双向连续序号、带抖动有界指数退避、原信封保留、`recovery_required`、独立文件库和 PG17 | M4.2 重试/不丢事实，M4.3 服务端限额与对账，M4.4 故障注入。问题分配不阻断其它上行分配 | 连接/请求超时、退避/抖动参数、重试预算和重置、告警、重连对账周期、人工恢复触发/操作阈值 |
| Q7 | A 按当前设备状态和授权，停用转冲突；B 按可信历史采集授权版本接纳 | **A**。同作用域停用设备仅在当前授权和因果合法时可记录冲突并消费序号，自报时间不能证明采集时授权 | M4.3 接纳及最小审计，越 Tenant/Site/Node 或无效凭据仍拒绝，验收 S1.1 及 D2 样例 | 可证明的历史授权版本另审 |

[行为契约与样例](candidate-contract.md) · [验收矩阵](tasks.md)
