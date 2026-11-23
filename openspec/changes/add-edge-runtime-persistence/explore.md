# M4.2 Explore｜Edge Runtime 本地持久化

## 结论摘要

M4.2 要补的是一套独立、可重启的 Edge 本地账本与恢复基础，不是 Cloud 同步服务或完整 Edge Station。当前 Edge Runtime、Venue Console 和场馆部署均只有职责说明 README，没有可运行服务、独立依赖、数据库、迁移、测试或 API。Cloud 已有 Edge Registry、凭据/心跳、TrainingSession、媒体授权和 M3 上传，但没有 M4.1 的 TrainingTask、Assignment、Command Log、Sync Inbox/Outbox、游标或同步路由。

建议 M4.2 隔离实现以普通 CPU 进程、本地 SQLite 文件、独立 SQLAlchemy/Alembic 环境为基线；文件单独落在显式 Edge 数据目录。SQLite 是隔离开发与测试选择，不是生产数据库批准。Redis 不作为首片依赖或事实源。生产数据库、Redis、现场存储容量/备份和生产数据保留仍待评审。

M4.1 的 Edge 端责任可在不更改契约的情况下落实：Inbox、命令效果和连续游标同事务；业务接单和 Outbox 信封同事务；采集事实/真实终态与 Outbox 同事务；事件按 Assignment 连续编号且重试保持原信封；通用断网、自然过期或单纯撤钥不自动停止已接单任务；只有已验证停用或可信本地停机持久触发 `safety_hold`。任何恢复错误均保留事实并转为可诊断/人工恢复状态。

## 1. Git 与 OpenSpec 基线

- Repository：`TuIanL/zhiyong-swim-platform`；执行前在源 clone 成功 fetch，`origin/main=fa985a33926cf166b121e8b748c2b54ab7bd7e65`，与 PR #8 合并提交相同。
- PR #7 已于 2026-11-20 合并，merge SHA `8fea879270c6ced9e4bc899b367f43e6e0de77b6`；PR #8 已于同日合并，merge SHA 为当前 main。GitHub 查询时无开放 PR。
- 原源 clone 工作区有 158 个既存暂存删除项且检出内容为空；未在其中编辑或清理。当前工作在 `/private/tmp/zhiyong-swim-platform-m4-2-edge-runtime-persistence` 的全新 clone 和独立分支 `docs/m4-2-edge-runtime-persistence`，干净起于上述 main SHA。
- OpenSpec 根存在，`schema: spec-driven`，项目文档语言为简体中文，主规格现有六项均属 Cloud。没有已存在的同名 Change。新 Change 使用行为规格，不设置 `skip_specs: true`。

## 2. 当前代码真实状态

| 路径 | 实际内容 | 当前缺口 |
| --- | --- | --- |
| `services/edge-runtime/` | 仅 `README.md`，描述未来 Edge API、Device Manager、Video Ingest、Media Catalog、Task Runtime、Worker、离线恢复和运维模块 | 无 Python 包、运行入口、模块依赖/锁、配置、数据库、迁移、API、worker 或测试 |
| `apps/venue-console/` | 仅 `README.md`，描述未来场馆 LAN 管理前端和 Edge API 消费者 | 无前端代码、构建、API Client 或 E2E |
| `deploy/venue/` | 仅 `README.md`，说明未来 Profile 仅包含 Edge Runtime 与 Venue Console | 无 Compose、镜像、数据卷或启动/恢复配置 |
| `services/cloud/` | 实际运行的 Python 3.13/FastAPI Cloud 包；依赖与迁移在 Cloud 根级独立定义 | 不含本地 Edge 持久化；不应让 Edge 导入 Cloud ORM、Session 或直接访问 Cloud DB |

Monorepo 规范要求 Edge 使用独立依赖、锁、测试和迁移；Cloud 保留现有根级包与 CI。场馆部署与 Personal Workbench 分离。新增 OpenSpec 行为能力宜命名 `edge-runtime-persistence`，与现有 `cloud-*` 主规格并列，不修改 Cloud 规格。

## 3. Cloud 现有能力审计及复用边界

| 已实现 Cloud 能力 | 代码/模型证据 | Edge 必须消费/遵守 | Edge 不得重复建设 |
| --- | --- | --- | --- |
| Identity、Tenant/Site、成员和授权 | `services/cloud/src/swimplatform/api.py`、Cloud Identity 与 Media Authorization 主规格 | 通过未来版本化接口消费归属与授权结果 | 不建立 Cloud 用户、Tenant、Site、RBAC 或另一套身份系统 |
| Edge Registry | `edge_registry.py`；`EdgeNode`、`Device`、`EdgeCredential`；Cloud migration `20261110_0002` | 保存受控的本机 Node 标识；Camera Device ID 用作采集来源；依有效 Cloud 凭据同步 | 不克隆 Registry、设备登记或 Cloud 权限模型 |
| Node/Device | EdgeNode 状态为 pending/active/disabled；Device 当前只支持 camera 且有固定 Tenant/Site/Node 归属 | 按 M4.1 事实信封引用原标识；不从本地观察值改写 Cloud 归属 | 不创建第二个 Cloud Device Registry |
| Edge 凭据 | 凭据表仅保存 token hash；明文只在签发成功响应一次；7 天默认、30 天上限、服务端 UTC、撤销不可复活；`/api/v1/edge/heartbeat` 记录观测 | 凭据由受控 Secret 配置适配器提供；不写入业务 SQLite、普通诊断或日志；401 只暂停同步 | 不复制 Cloud 凭据签发、到期、撤销或身份授权逻辑 |
| TrainingSession 与 Asset | `media.py`、`TrainingSession`/`VideoAsset`；迁移 `20261112_0003`。Session 状态 planned/recording/completed/cancelled 且终态不可回退 | 本地任务保留 Cloud 发来的 `session_id` 作为外部关联标识；Cloud Session/Asset 继续由 Cloud 决定 | 不在 Edge 创建/覆盖正式 Cloud Session、状态、grant 或 Asset |
| M3 Media Transfer | `media_transfer.py`、`UploadSession`、`MediaObject`、`UploadPart`、`MediaJob`；迁移 `20261114_0004`；有分片续传、整对象校验、`ready` 发布和访问授权 | M4.2 只提供本地文件索引/校验/恢复接口，不把事件 ACK 当媒体 ACK；原片默认留本地 | 不复制上传 URL、分片/续传、Cloud 对象验证、媒体授权/目录或 M3 状态机 |
| M4.1 任务同步服务端 | 搜索 Cloud 源码、测试和 `docs/contracts/openapi.json` 未发现 training-tasks 或 edge/sync 路由/模型/迁移 | M4.2 用 `CloudAdapter` 接口和 `MockCloudAdapter` 做隔离验证 | 不在本 Change 修改 `services/cloud/`、Cloud API、OpenAPI、Cloud DB 或 M4.3 功能 |

现有 Cloud CI 使用 SQLite、PostgreSQL 17 与隔离媒体存储，是 M1–M3 兼容回归证据。它不等于 M4.2 Edge 运行验收。

## 4. M4.1 契约映射

权威依据为 [云边架构](../../../docs/architecture/cloud-edge-sync-v1.md)、[API 契约](../../../docs/contracts/cloud-edge-sync-v1.md)、[ADR 0004](../../../docs/decisions/0004-cloud-edge-sync-v1.md)、[第三轮 Verify](../../../docs/verification/cloud-edge-sync-contract-verify-round-3.md) 与完整 [M4.1 Change Archive](../archive/2026-11-20-define-cloud-edge-sync-contract/)。

| 契约 | M4.2 Edge 本地责任 | 留给后续 |
| --- | --- | --- |
| D1/R2，Cloud 持正式 Session/Task/Assignment/取消；Edge 持接单、执行和采集事实 | 本地 `LocalTrainingTask`/`LocalAssignment` 是影子与运行事实，不覆盖 Cloud 状态；事件白名单不含视频、报告或分析结果 | M4.3 Cloud 授权、控制 API、投影和冲突收据；M4.4 双端收敛 |
| D2/R1，信封 ID、scope、sequence、版本与载荷白名单稳定 | 首次入库生成/保存完整规范信封及 SHA-256；重复投递逐字节/规范内容复用，不允许相同 event_id 改内容 | M4.3 服务器校验；M4.4 网络实际往返 |
| D3/R3/A1/A2，持久接收、Command ACK、业务接单、实际执行为四阶段 | Inbox+命令效果+游标同一事务；事务提交后 ACK；业务接单仅在追平固定水位且未取消/未挂起时与 `accepted` Outbox 同事务；执行有单独门槛 | M4.3 命令源/ACK 水位；M4.4 两个真实进程 |
| D3/R4，命令节点序号、事件 Assignment 序号、补拉后补投和对账 | 持久连续 cursor；Outbox 每 Assignment 独立序列；缺口、丢失账本或无法重建进入 `recovery_required`，不跳号 | M4.3 Cloud Inbox/收据/对账；M4.4 真实网络乱序与重放 |
| R5/C1/C2，断网、自然过期、仅撤钥 | 同步暂停，但已业务接单工作/事实继续并持久化；未接单保持等待；重连恢复同 Node 账本 | M4.3 当前身份/再签发；M4.4 35 天逻辑时钟和网络演练 |
| D5/R6/C3/C4/S6.3，取消与 safety hold | 已持久取消后阻止新开工；只有实际安全停止才记录 `stopped_by_cancel`。已验证停用/可信本地停机写入不自动清除的 `safety_hold`；保存检查点/事实 | M4.3 Cloud 取消命令、节点状态/授权；M4.4 安全通知与双端竞态。无生产远程通知通道承诺 |
| R7/S7.1/S7.2，过期、撤销、新凭据及同 Node 恢复 | 通用 401 不猜原因、不触发 hold、不丢本地状态；凭据自然过期暂停同步；账本绑定 node_id，不随 credential ID 变化 | M4.3 Registry/credential 行为；M4.4 实际 reissue 流程 |
| R8/S8.1、M1–M7，事件与媒体分离 | `LocalFileRecord` 校验/本地保留；事件收据不删除文件，不生成 Cloud 上传 | M4.4 单独人工批准后走 M3 的完整上传、续传和验证 |

契约没有要求 Edge 获得 Cloud 最终状态权，也没有要求把 Event Outbox 当作媒体上传队列。将 local shadow 与 Cloud projection 分列可避免冲突。

## 5. 存储和依赖候选

| 候选 | 适用性 | 建议 |
| --- | --- | --- |
| SQLite 文件 | 单节点、单个 Edge 应用进程、隔离 CPU 测试；事务性地托管 inbox、cursor、task、outbox、hold、recovery | M4.2 隔离可运行切片的推荐选项；使用持久目录、显式初始化/升级、外部备份，不视为生产批准 |
| PostgreSQL | 多进程写入、较强并发、集中备份/监控时更合适，但要运行和恢复额外数据库服务 | 生产环境候选；需结合场馆算力、I/O、备份恢复、升级和运维成本另评；不用于 M4.2 隔离 CPU 基线的必需服务 |
| SQLAlchemy + Alembic | 与当前 Cloud 工程已有 Python 工具链相同；独立模型/迁移可支持 SQLite，并为之后评估 PG 留接口 | 推荐 Edge 自有 package 内使用 SQLAlchemy Core/ORM 与 Alembic；Edge schema/versions/env 独立，不导入 Cloud Base/迁移；显式 migration 命令，启动只校验版本 |
| Python `sqlite3` + 手写 migration | 最少依赖，满足单 SQLite 后端，但版本升级、事务和未来跨后端抽象需自建 | 可作为更小的备选；Edge 既要版本化 schema 又需保留未来 PG 评估时，预计重复造轮子，优先 SQLAlchemy/Alembic |
| Redis | 缓存/短期调度可能有用，但不能成为业务状态或未确认事件的唯一存储；与 SQLite 引入两套故障和备份路径 | M4.2 不引入。若后续多进程/缓存实测证明必要再议；按具体版本评许可证，Redis 8 起为 RSALv2/SSPLv1/AGPLv3 三选一，Redis 7.4 系列是 RSALv2/SSPLv1，不能沿用“Redis 一律 BSD”假设 |
| 本地文件系统 | 大媒体不进业务表；文件写入与 SQLite 事务无共同原子提交 | 同一 Edge 数据卷下 `staging/` 与 `objects/`，数据库保存相对路径、大小、SHA-256、状态。fsync、原子 rename、启动对账，不自动删除原始视频 |

许可证核对依据：[SQLite 公共领域说明](https://www.sqlite.org/copyright.html)、[PostgreSQL License](https://www.postgresql.org/about/licence/)、[SQLAlchemy MIT](https://www.sqlalchemy.org/download.html)、[Alembic BSD-3-Clause](https://github.com/alembic/alembic/blob/master/LICENSE.txt)、[Redis 各版本许可](https://redis.io/legal/licenses/)。这些是方案调研，不替代依赖锁定时对完整传递依赖的 SBOM/许可证审查。

## 6. 本地数据模型草案

以下是行为规格/Design 候选，不是已批准 SQL Schema。全部行只服务当前 Edge Node 的本地账本，不建立 Cloud 外键，不复刻 Cloud 行或权限。

| 候选记录 | 建议主键、字段和约束 | 必须持久/重建边界 |
| --- | --- | --- |
| `LocalCommandInbox` | `event_id` 主键；`node_id`、`command_sequence`、schema version、task/assignment ID、task version、type、规范 JSON、fingerprint、received/applied time；唯一 `(node_id, command_sequence)` | 原命令与去重内容不得丢；相同 ID 异内容是冲突 |
| `CommandCursor` | `node_id` 主键；`last_applied_sequence`，可选 `round_through`；仅已验证的新绑定可从 0 建立 | 持久连续位置；不从 Cloud ACK 倒推本地已收命令 |
| `LocalTrainingTask` | Cloud `task_id` 主键；外部 Session/Tenant/Site ID；local phase、last command version、checkpoint version/JSON、created/updated；任务生命周期和不变量由 Edge schema 校验 | 区分 Cloud 下发 status 与本地 phase；不做正式 Cloud Session/Task 投影 |
| `LocalAssignment` | Cloud `assignment_id` 主键；task/node ID；独立 `next_event_sequence`、最后已应用 task version、run/execution ID、attempt/checkpoint、恢复状态；唯一 task_id（v1 单分配） | 每分配序号独立连续；状态可恢复、其他 Assignment 互不阻塞 |
| `LocalCaptureFact` | `capture_id` 主键；scope IDs、assignment/task/device ID、captured UTC/raw device time、metadata allowlist、可空 `file_id`、事实摘要；唯一 scope+capture_id | 本地业务事实和事件内容不可静默替换；不知道的时间仍未知 |
| `LocalEventOutbox` | `event_id` 主键；assignment ID、连续 `sequence`、schema/type、不可变规范信封字节/JSON、fingerprint、状态、发送预算/next_attempt、ACK 收据；唯一 `(assignment_id, sequence)` | 原始信封留到精确收据匹配；发送状态可变而信封不变 |
| `LocalSafetyHold` | hold_id、node/scope、原因及可信来源、触发时间、active/released、清除操作者/时间/说明；以追加历史保留每次 hold/release | 挂起与审计持久，重启不得自动清除 |
| `LocalFileRecord` | file_id；scope/task/assignment/capture 关联；相对 staging/final path、size、sha256、media metadata、状态和各阶段时间；唯一文件路径 | 保留源文件及校验信息，未核验文件不能引用；没有生产保留期限 |
| `LocalRecoveryRecord` | recovery_id；scope 类型/ID、failure code、相关行/文件 ID、脱敏证据、首次/最近时间、open/resolved、人工处理审计 | 不可恢复事实和处理理由持久保存；重复扫描应幂等 |

派生的进程/网络可用状态、DB connection、临时缓存、当前健康计算可以重建。命令/事件 envelope、Inbox 去重结果、cursor、已提交业务事实、Outbox、hold、文件关联和未结 recovery record 不可丢。Outbox 至少保留到匹配收据；M4.2 不提出压缩/删除规则。原视频不随事件确认自动删除。

## 7. 事务与文件一致性设计要点

SQLite 事务与文件系统不构成分布式原子事务。建议所有写入以 `LocalFileRecord` staging 意图作为可恢复凭证，两个文件目录位于同一持久文件系统：

1. 事务记录 staging intent、文件 ID、关联任务/采集事实的稳定标识和相对路径。
2. 写唯一临时文件；写完 flush/fsync，计算大小及 SHA-256，校验已知期望值；将校验结果状态提交。
3. 只在同一文件系统内原子 rename 到不可变最终路径，再 fsync 文件和父目录。
4. 再开 DB 事务，同时把 FileRecord 标为可用、写 LocalCaptureFact 和分配序号确定后的不可变 Outbox envelope。只有这笔提交后 worker/本地读 API 才可引用该文件。
5. 每次启动扫描数据库与 staging/objects：逐项验证大小、hash、相对路径和业务关联；生成幂等 RecoveryRecord。检查期间不向 Worker/Console 提供未验证引用。

| 崩溃点 | 磁盘/数据库可能状态 | 重启规则 |
| --- | --- | --- |
| intent 前 | 未有 FileRecord；可能无文件 | 无关联则不暴露；发现遗留文件按 orphan 登记、隔离，保留供人工检查 |
| 写临时文件中 | DB intent 存在、临时文件不完整 | 标记 `recovery_required`，不生成事实/Outbox、不供引用；不自动删除媒体字节 |
| 已写临时文件并 fsync，校验记录已提交，rename 前 | 已验证 temp + staging DB 状态 | 重算 size/hash；匹配后可继续 rename；不匹配则挂起并保留证据 |
| rename 后、最终 DB 事务前 | 最终文件存在，DB 仍是 staging/verified | hash 匹配且可关联 intent 时补做最终事务；否则隔离并人工处理 |
| 最终 DB 事务中失败/进程退出 | SQL 原子回滚，文件已发布，记录仍是前态 | 同上，以持久 intent 确认，不重复创建 capture/outbox |
| 最终 DB 事务已提交 | FileRecord、事实、Outbox 同时可见 | 再核验文件；hash 正确方可恢复引用 |
| DB 显示 ready 但文件缺失/损坏 | 孤立数据库引用 | 标记 `recovery_required`，阻止执行和引用，不从 Cloud 推测文件正确性，不自动删/覆盖原件 |
| 文件无 DB 记录 | 孤立文件 | 隔离登记为 orphan，禁止引用；M4.2 不自动清理。恢复失败绝不自动删除原始视频 |

如果恢复依赖缺少证据、hash 不符、游标不连续或数据库本身无法打开，显式挂起并保留原始库/文件；不通过重建空库、跳游标、重命名覆盖或猜测归属“修复”。

## 8. 离线任务、重启与安全挂起

- 收到 Cloud 命令：严格校验版本/方向/字段/身份绑定；一个 SQLite 事务插入 Inbox、更新本地命令效果与游标。提交成功才发 `{through}` ACK。重复同命令只重发已提交 ACK，不重复业务效果。提交前退出不推进游标；提交后 ACK 丢失可用持久 cursor 重发。
- 业务接单：仅当同步轮固定 `through` 已全部应用，命令证明任务未取消，且没有 safety hold 时，单事务更新本地 accepted + 插入 `training_task.accepted` Outbox。持久接收或 ACK 本身不接单。
- 执行启动：只允许 accepted、未取消、无 safety hold 的 Assignment。持久 run ID/checkpoint 后调用确定性测试 Worker；重启只按已持久 checkpoint 恢复或转人工 `recovery_required`，不重复不能证明幂等的外部副作用。
- 采集及真实任务终态：LocalCaptureFact/LocalTask 状态、Assignment sequence 分配、原始 Outbox envelope 同一 DB 事务提交。事件 ID 首次产生并在同事务保存；后续重投不重建信封。`stopped_by_cancel` 要求已持久应用同一 Assignment 取消命令且 worker/停机控制已确认真实安全停止。
- 离线或凭据自然过期/仅撤钥：停止 Cloud 请求、持续本地已接单执行并保存事实；未接单任务不启动。通用 401 不被解释为 Node disabled，不触发 safety hold。
- Node disabled 必须来自受信且经验证的状态；可信本地停机可直接触发。安全挂起持久化并阻止所有新开工；重启、重认证、网络恢复或 worker 启动不能自动解挂。只有显式、带操作者/原因/时间审计的受控操作可释放。
- 对账先补拉已到固定上限的命令和 ACK，再按 Assignment 顺序重放原 Outbox，最后核对与当前投影。收据匹配认证 scope、`event_id`、`assignment_id`、`sequence` 和处置；HTTP 200/Cloud 水位单独都不足以销账。永久错误暂停该流、保留事实；其他 Assignment 仍运行。
- Event ACK 与 M3 UploadSession/VideoAsset.ready/读取授权互相独立；Edge 不自动上传、删除或改写原片状态。

生产可信停用通知、身份凭据投递、Venue Console 授权和本地解挂角色/核验流程均未在本 Change 定义，不假设其已存在。

## 9. 隔离测试环境、P01–P10 和故障注入

环境固定为普通 CPU、独立 Edge 工作进程、持久 SQLite 测试文件、临时持久文件目录、FakeClock、FakeNetwork、合成 Cloud 命令、合成 media bytes、MockCloudAdapter 和确定性 MockAnalysisWorker。通过子进程重启保留同一 data dir。无需公网、真实 Cloud、真实摄像头、GPU、Docker、Redis 或 Cloud DB。

| 参数 | 隔离开发/测试用法（禁止写成生产默认） |
| --- | --- |
| P01/P02 | 连接超时 2 秒；单请求总计 5 秒，覆盖提交后响应延迟和丢失 |
| P03/P04/P05 | 初始退避 1 秒、上限 30 秒、±20% jitter；测试固定随机种子；有效 `Retry-After` 更长时尊重服务端提示，即使本轮重试预算提前耗尽 |
| P06 | 首次后最多 3 次重试或累计 30 秒，先到为准；耗尽不销账，持久记录下次受控探测时机 |
| P07 | 只有有效认证重连对账、明确人工恢复，或至少 60 秒冷却后的受控探测成功可重置；重启/连续失败不重置 |
| P08 | 每 Assignment 100 条待发或最老 300 秒报警；只告警不丢事件 |
| P09 | 正常同步/对账 15 秒，恢复网络时合并为一次立即对账；401 等身份处置，不盲重试 |
| P10 | 确认缺口不可恢复立即挂起；人工操作单次等待 300 秒，超时仍挂起、不跳 cursor、不丢事件 |

计划覆盖用户给定的 20 项：干净目录/重复初始化、Schema 升级、接令重启/ACK 前重启、接单与 Outbox 原子性、同事件重复与异参冲突、Assignment 连号、丢失 ACK、文件写入/发布/DB 提交各崩溃窗口、执行重启、safety_hold 重启保持、取消后的迟到事实、重试预算耗尽、recovery_required 人工恢复、多 Assignment 隔离，以及无公网健康检查和持久化。详细 `Requirement / Scenario → Task → Test` 表由 Proposal 后 Tasks 文件列出。

这是测试设计，不代表本轮执行上述测试；本轮只做 OpenSpec 和静态文档验证。

## 10. 风险与待负责人决策

1. **生产数据库**：SQLite 只批准作隔离 CPU 验证基线。场馆单进程/多进程写入、数据库服务运维、备份恢复和资源余量仍需选择 SQLite 或 PostgreSQL；Redis 是否有经测量的需求也待议。
2. **生产数据目录与运维**：生产路径、磁盘分区/容量水位、备份、恢复点/恢复时间、介质损坏和保留/删除规则未批准。M4.2 不能据恢复流程自动清理原始视频。
3. **凭据和本地 API**：边缘凭据仅抽象为外部 secret source；具体 OS secret store/交付、健康/诊断接口生产绑定地址与认证方式需安全评审。M4.2 建议仅在 loopback 提供无敏感诊断，不发布场馆 LAN 控制面。
4. **安全挂起来源与解挂**：M4.1 明确通用 401、自然过期、仅撤钥不触发 hold，只有已验证节点停用/可信本地停机触发。生产通知、现场核验、操作者身份与恢复审计 UI 留后续决定；Mock 仅验证语义。
5. **任务恢复点**：确定性 worker 可证明检查点恢复；真实采集/AI worker 的副作用幂等、并发进程数和安全停机反馈属于 ES-05/ES-06 的后续运行设计。
6. **文件语义**：原子 rename 只在同一文件系统成立；断电时 `fsync` 与硬件写缓存的真实性需在目标场馆盘验证。M4.2 合成故障测试不证明 GPU 工作站硬件耐久性。
7. **许可与传递依赖**：Redis 版本许可证差异使其不适合作为无必要的隐含依赖。实施前独立锁文件和完整依赖许可证扫描是可验收项。
8. **M4.1 API 未实现**：当前 Cloud 不提供任务/同步路由。Mock 不能冒充真实双进程网络集成；M4.3 和 M4.4 责任保持隔离。

## 11. Edge Station ES 任务映射

| 任务 | M4.2 输出对其支持 | 仍由独立任务交付 |
| --- | --- | --- |
| P1｜Edge Runtime 基础部署包 | 独立启动骨架、数据目录/schema、持久化、健康与最小诊断、无公网可启动的 CPU profile | Ubuntu/GPU 工作站安装、驱动、可重复 Compose 部署和现场验收，不因此视为 P1 完成 |
| ES-05｜本地任务运行时与 Worker 生命周期 | Local task/assignment、接单/执行门槛、持久 checkpoint、确定性 Worker 接口和重启恢复基座 | 完整 Worker 生命周期、实际 AI/Video worker 和完整运行策略 |
| ES-06｜Edge 离线与故障恢复 | SQLite 持久账本、MockCloud、离线重试、recovery_required、safety_hold 和进程重启演练 | 主机级部署故障、真实 Cloud 通知/集成、备份恢复和生产运维验收 |
| ES-01～04、ES-07～09 | 提供可复用边界/数据状态 | Runtime 完整包、摄像头、Console、媒体回放、监控备份、V1 集成、Personal Workbench 均不因 M4.2 完成 |
