# M4.1 独立 OpenSpec Verify

**核验日期 2026-11-18（Asia/Shanghai） · CRITICAL 0 / WARNING 2 / SUGGESTION 2**

OpenSpec 的纯文档结构和 7 项任务记录均可复核。独立审计发现两处会使后续实现或验收出现不同结果的缺口，**建议完成文档 Remediation 后再归档**。本轮报告固定在 `4588e6905ad876fb8bcc1edb5a3280f21703200a`，PR #7 仍为 Open / Draft / 未合并。

| 维度 | 核验结论 |
| --- | --- |
| 完整性 | Apply 任务记录 7/7，七项各有交付证据；原 8 项 R、19 个 S、19 个 T/A/C/L 和 6 个 Q5 B 媒体向量可追溯。正式行为 Delta 覆盖不适用，`specs` 由 CLI 跳过。 |
| 正确性 | 文档的事务、承诺范围、授权边界及参数数值已核对。取消后的因果与收据、M4.4 续传夹具存在两项 Warning。M4 实现映射、运行场景及新业务代码模式检查不适用于本纯文档 Change。 |
| 一致性 | Pinned Git 树、六份主规格、Q1–Q7 选择、PR 工程回链与 Apply 证据一致。两项 Suggestion 涉及收据作用域表达和归档移动后的链接。 |

## 1. 固定基线与发布边界

仓库为 `TuIanL/zhiyong-swim-platform`，分支为 `docs/m4-cloud-edge-sync-contract`。GitHub 的 PR Head、本地 HEAD 和远端跟踪分支一致。GitHub 当前 `main` 与 PR Base 均为 `94fed6b03d50ccca52f6ec959bcde1636148c65c`。[PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) · [main 基线](https://github.com/TuIanL/zhiyong-swim-platform/commit/94fed6b03d50ccca52f6ec959bcde1636148c65c)

| 阶段 | 提交 | 父提交 | 提交时间（UTC+08:00） |
| --- | --- | --- | --- |
| 初版 Propose | `b2bb18313d9fc1b66d85ee391b8e11aee23bff1d` | `94fed6b` | 2026-11-18 10:26:42 |
| 二轮 Propose | `a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b` | `b2bb183` | 2026-11-18 10:39:27 |
| Q1–Q7 签认入库 | `ef17d966a46d99da03e5c2ab68e3b2d401268c37` | `a26d006` | 2026-11-18 10:57:08 |
| 正式文档交付及 Task 2.2 补签参考 | `ff5d82c1b4c85e7b438cb125b581a52784cc3f6a` | `ef17d96` | 2026-11-18 11:09:04 |
| Task 2.2 补签入库及最终 Apply | `4588e6905ad876fb8bcc1edb5a3280f21703200a` | `ff5d82c` | 2026-11-18 20:40:03 |

表中时间为 Git 提交时间。签认来源以负责人提供的 Q1–Q7 决策及 P01–P10 补签记录为准。PR 正文按相同基线区分二轮 Propose、签认、6/7 文档交付、7/7 最终 Head 与对应 CI，和 Apply 证据的 Git 追溯一致。

GitHub PR 文件列表与 `git diff --name-status main-baseline...apply-head` 均为以下 9 项新增：

- `docs/architecture/cloud-edge-sync-v1.md`
- `docs/contracts/cloud-edge-sync-v1.md`
- `docs/decisions/0004-cloud-edge-sync-v1.md`
- `docs/verification/cloud-edge-sync-contract-apply.md`
- `openspec/changes/define-cloud-edge-sync-contract/{.openspec.yaml,candidate-contract.md,design.md,proposal.md,tasks.md}`

业务源码、迁移、依赖、CI 工作流、OpenAPI 快照、六份主规格与既有归档在两棵提交树中一致。OpenSpec 1.16.0 返回 `skip_specs: true`、`specs: skipped`，Change 内无 `specs/` 或行为 Delta。Proposal 明确 M4.2/M4.3 各自提交所实现的行为 Delta。M4.1 归档的职责是保留文档与证据。

## 2. 决策到实施与验收的追溯

ADR 0004 第 11–17 行和 Design 第 59–65 行逐项等值，顺序为 **Q1=A、Q2=A、Q3=A、Q4=A、Q5=B、Q6=A、Q7=A**。Proposal 第 11–25、37 行保留签认与范围，Tasks 第 3、7–19、25–29 行覆盖验收入口，Apply 记录第 13–19 行回指各项证据。以下表中的 API 行号指 `docs/contracts/cloud-edge-sync-v1.md`，架构行号指 `docs/architecture/cloud-edge-sync-v1.md`，均以固定 Head 计。

| 决策 | 架构和 API 实际约束 | 验收与后续责任 |
| --- | --- | --- |
| Q1 A | 架构 15、40 行，API 15–24、40 行。全生命周期每 Session 一个 Task，每 Task 一次 Assignment 和一个固定 Node；终态占名额；当前 Tenant Owner/Admin 控制，首版 `capture_demo`。创建与指派同事务。 | T1–T9/L2，M4.3 权限、唯一性、原子写和幂等，M4.2 消费分配命令。 |
| Q2 A | 架构 15、47–48 行，API 23–26、199–213 行。Cloud 持正式终态，Edge 上报事实，合法事务先提交者胜出；父 Session 取消联动未终结项，保留已完成历史。迟到事实的细分收据及因果条件见 W1。 | R6/S6.1–S6.3/L3，M4.2 本地调度门槛、M4.3 事务与投影、M4.4 双端竞态。 |
| Q3 A | 架构 82–94 行，API 215–225、419–426 行。断网、自然过期、仅撤钥保留已接单任务的执行资格；可信停用或停机触发持久 `safety_hold`。通用 401 不推断停用。同 Node 恢复有审计解挂门槛。 | R5/R7/C1–C4/L4，按 M4.2 本地恢复、M4.3 现行授权、M4.4 故障恢复取证。 |
| Q4 A | 架构 D6，API 34、38–42、54–74、103 行和 ADR 14 行。有效节点身份通过 HTTPS/TLS 主动拉取，节点序号、版本与固定追平水位。逐命令数字签名及独立任务硬截止不纳入 v1。 | R1/R3/R4/A1/A2。M4.2 与 M4.3 分别验收拉取应用、ACK、接单和执行门槛，M4.4 验证未送达取消的边界。 |
| Q5 B | 架构 17–35 行、API 111–125、227–237 行及 ADR 15、23–34 行。独立人工批准，与事件、报告和媒体状态分离；沿用 M3。 | M1–M6 由 M4.4 独立验收；M4.2 负责原件保留，M4.3 负责事件与媒体的授权隔离。M3 向量的夹具见 W2。 |
| Q6 A | 架构 132–153 行、API 76–80、94–103 行。8 KiB、50 条/页、双向连续序号、带抖动有界退避、保留原信封及 `recovery_required`。P01–P10 限隔离环境。 | R3/R4/R5/A1/A2。M4.2 调度与持久化，M4.3 限流及对账，M4.4 提交后丢响应和重启演练。 |
| Q7 A | 架构 16 行、API 39、76、389–400 行与 ADR 17 行。同归属停用设备的合法迟到事实只记 `conflict_recorded`，不增正常采集投影。权限和归属先检，设备自报时间不能证明过去授权。 | R1/S1.1、R2/S2.1 与停用设备受控样例，M4.3 来源和投影，M4.4 节点隔离。 |

### Q5 B 人工批准与 M3 边界

API 第 115、119–125 行绑定 Tenant、Site、Session、具体本地资产 ID、SHA-256/长度、目的、当前 M3 发起身份及批准引用。M3 生成的 `asset_id` 和 `upload_session_id` 回链同一批准。未批准分支的事件可 ACK，仍应为零上传意图、零对象写入、零原片传输。隔离路径可使用现行 S-manage User 或现行 Edge 发起者，原发起主体继续走 M3 权限核验。Edge 同步客户端不会获得 User 令牌或通过同步取得媒体权限。

M3 负责分片、续传、精确对象版本及 SHA-256、长度和媒体有效性验证。Worker 在提交前复核当前授权，完成后方可成对写 `completed/ready`。事件 ACK、分片确认和 `completing` 均不能使媒体进入 `ready`，上传完成后保留本地原件。已签 URL 仍受 M3 TTL 和对象约束。对照既有 M3 契约的 User/Edge 操作、发起人限制和 `ready` 边界，以及 (R2/R8) 的媒体/报告授权分离，未发现权限扩张。

M1、M2、M3、M4、M5、M6 分别对应未批准、指定人工批准、上传中断恢复、整对象验证、撤权/过期、本地原件保留。其运行归属为 M4.4，使用合成 MP4、测试编排、隔离 RustFS 和测试身份。真实审批角色及记录规则、个人信息处理、监护人同意、生产存储/区域/访问控制、保留、备份、删除、撤回及审计按 ADR 0004 第 27–32 行另行批准。[M3 正式契约](https://github.com/TuIanL/zhiyong-swim-platform/blob/4588e6905ad876fb8bcc1edb5a3280f21703200a/docs/contracts/cloud-capture-media.md)

### Q6 数值与适用范围

独立逐行比较 `ff5d82c` 与 `4588e69`，P01–P10 表体十行完全一致。ADR 0004 第 16、21 行、架构第 138–140 行、API 第 34 行和 PR 正文均明确限隔离开发与测试，生产默认值另审。API 第 103 行明确 8 KiB 是单个 JSON 信封 UTF-8 实际字节数（8192，含空白及载荷，不含 HTTP 头），下发也逐事件遵守上限，每页最多 50 条。

| 参数 | 核对值与含义 |
| --- | --- |
| P01 / P02 | 连接 2 秒，单请求总计 5 秒，后者含连接及读取。 |
| P03 / P04 / P05 | 初始 1 秒，最大 30 秒，基数 ±20% 抖动；有效 `Retry-After` 可能先耗尽本轮预算。 |
| P06 | 首次之后最多重试 3 次或总计 30 秒，先到为准，耗尽不丢 Outbox。 |
| P07 | 经有效认证的重连对账、显式人工恢复，或至少 60 秒冷却后的受控探测成功。重启及连续失败不重置。 |
| P08 / P09 | 每分配 100 条积压或最老 300 秒告警；正常重连/对账间隔 15 秒，网络恢复合并重复触发，401 等待身份处置。 |
| P10 | 确认不可恢复缺口即挂起。人工单次操作等待 300 秒，超时保持挂起，游标与事实保留。 |

Apply 走读第 29–33 行与上述一致。即时 503 和零偏移抖动时，1/2/4 秒的退避间隔给出 `t=0/1/3/7` 四次尝试，正好是首次及 3 次重试。等待或有效限流提示可先耗尽 30 秒预算。重启挂起、重连对账与 300 秒人工恢复超时都保留原 ID、序号与信封。未重跑新增行为场景。

## 3. 验收矩阵与 Apply 证据

| Requirement | 原始场景 | 文档验收证据与归属 |
| --- | --- | --- |
| R1 | S1.1、S1.2 | 身份、严格信封、方向和作用域。M4.2 下行、M4.3 上行、M4.4 隔离。 |
| R2 | S2.1、S2.2 | Cloud 控制与 Edge 事实分权，采集/执行事件不创上传或发布报告。M4.3 投影及负向测试，M4.4 传输观测。 |
| R3 | S3.1、S3.2、S3.3 | Outbox/Inbox 提交、至少一次投递及唯一效果、丢 ACK/异参。M4.2 持久化、M4.3 去重与独立 PG 事务、M4.4 真实中断。 |
| R4 | S4.1、S4.2、S4.3 | 连号、缺口、重连补投、不可恢复处理。M4.2/M4.3 对账与卷恢复，M4.4 上下行故障。 |
| R5 | S5.1、S5.2 | 离线执行和重启，有界重试与卡住分配隔离，待发文件/检查点保留。M4.2 队列与执行器、M4.4 真实断网。 |
| R6 | S6.1、S6.2、S6.3 | 父 Session、任务取消和完成竞态，原终态保留。M4.2 接单/运行门槛、M4.3 PG 竞态、M4.4 双端顺序。见 W1。 |
| R7 | S7.1、S7.2 | UTC 失效、撤销和停用、同 Node 再签发；其他节点与旧凭据不能取旧收据。M4.3 实时授权、M4.4 恢复，C1–C4 补 Edge 状态。 |
| R8 | S8.1、S8.2 | 原 M3 媒体验证和授权独立，既有资源和客户端兼容。M4.2 本地原件、M4.3 兼容回归、M4.4 隔离媒体。见 W2。 |

从二轮 Propose 到固定 Head 比对标题与矩阵：R1–R8、19 个 S 的原编号与标题完整保留并一一匹配，T1–T9、A1–A2、C1–C4、L1–L4 共 19 项原向量与 M1–M6 的 6 项新增向量分别保留。API 第 60–63 行明确持久接收命令、Command ACK、业务接单 Outbox、实际开工四阶段。架构第 45–80 行将账本、投影及锁序写入实施要求，基线代码可复核潜在 Node→Session 与 Session→Node 逆序，PG17 双连接验证计划属于 M4.3。

| 任务 | 独立复核 |
| --- | --- |
| 1.1 | Q1/Q2/Q5/Q7、D1、控制权限及 Q5 B 的隔离正确性有文档证据。 |
| 1.2 | Q3/Q4、D12、S1.1/S7.1/S7.2 与 C1–C4 的凭据和下发边界可追溯。 |
| 2.1 | API、信封、错误和样例可复核；发现 W1 及 S1 的收据语义问题，保留原任务记录。 |
| 2.2 | P01–P10 补签、Task 2.2 走读、A1/A2、R3/R4/S5.1 及重置/恢复证据可复核。 |
| 2.3 | 终态双顺序及四项 PG 验收计划可核对；W1 需要补一条迟到因果链。 |
| 3.1 | 原始 ID、兼容基线、M4.2/M4.3 各自 Delta、M4.4 双端及媒体交接齐备；W2 需明确续传取证。 |
| 3.2 | strict、Git、链接、JSON 及无 Delta 静态证据已独立重验。 |

`openspec instructions apply` 报告 `all_done` 和 7/7。原任务文字与二轮 Propose 完全一致，补签前后仅将 2.2 置完成并加追溯。Verify 未改动 Tasks。

## 4. 静态检查结果

- `openspec validate define-cloud-edge-sync-contract --strict` 通过，CLI 显式接受 `skip_specs: true` 和零 Delta。
- `openspec validate --specs --strict` 6/6，主规格逐文件与 main 基线相同；`openspec validate --archived --strict` 6/6。
- 从固定 Git 树独立复现原 8 份 Markdown 的 **84 个相对链接**，其中 **38 个带锚点**，路径可达且锚点有定义。此计数排除新 Verify 报告。
- 解析 8 个 JSON 代码块和 1 个 HTTP 样例中的 JSON 请求，均合法。检查字段、UUID/UTC、`task_id`/`assignment_id`、命令水位、同一采集的收据关联、HTTP 409 结构/状态及冲突样例。M3 样例字段与当前 `UploadIntentCreate`/`CaptureMetadata` 一致，合成夹具实际 **894 字节**，重新计算 SHA-256 等于样例。上行收据作用域建议见 S1，小素材的分片局限见 W2。
- `git diff --check 94fed6b...4588e69` 通过。GitHub PR 与本地提交树的范围清单一致。

## 5. 固定 CI Run 的证据

核对 [Run 44306207193](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193) 和三个 Job 的原始 checkout、测试、清理及上传日志。**PR Head 是 `4588e6905ad876fb8bcc1edb5a3280f21703200a`；实际 checkout 是 `refs/pull/7/merge` 的 `01ec194c9f5de09393acdf6f69acf59395b3c373`。** 三份日志都记录该测试提交合入固定 main 和 PR Head。GitHub Compare 确认测试合并提交比 PR Head 多 1 个提交、少 0 个提交、文件差异为零。两份 artifact 的元数据 `head_sha` 均严格指向 PR Head，`workflow_run.id` 均为 44306207193。[测试提交与 PR Head 比对](https://github.com/TuIanL/zhiyong-swim-platform/compare/4588e6905ad876fb8bcc1edb5a3280f21703200a...01ec194c9f5de09393acdf6f69acf59395b3c373)

| Job | 实际结果与证据 |
| --- | --- |
| SQLite | 成功，**210 passed / 92 skipped**。[Job 134808311992](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193/job/134808311992) |
| PostgreSQL 17 | 成功，**281 passed / 21 skipped**。主清理日志为 `removed`，同一 run-id 的兜底记录为 `absent`，`exit_code=0`。[Job 134808312363](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193/job/134808312363) · [artifact 14428192696](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193/artifacts/14428192696) |
| 隔离 RustFS | 成功，媒体探针 **ffprobe 6.1.1**（包后缀 `-3ubuntu5`）。日志记录指定 run 的精确容器清理 `removed`。[Job 134808312408](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193/job/134808312408) · [artifact 14429070299](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44306207193/artifacts/14429070299) |

此 Run 证实 M1–M3 兼容性回归和测试环境。M4 的 Outbox/Inbox、Edge Runtime、双端同步与 Q5 B 集成运行证据由后续 Change 交付。

## 6. Findings 与最小 Remediation

### CRITICAL（0）

未发现负责人签认方向被替换、Q5 B 绕过 M3/真实数据准入，或纯文档 Change 修改正式行为主规格的证据。

### WARNING（2）

**W1 · 取消先提交后，缺少整条离线回报因果链的收据规则。** 位置 `docs/contracts/cloud-edge-sync-v1.md:26`、`:48–50`、`:76–78`、`:100`、`:351`、`:448`。对应 Q2、R3/R6、S3.2/S6.1。实际契约允许已取消 Task 将迟到 `training_task.accepted` 记为 `conflict_recorded`，同时拒绝缺少因果前置的事件。文档没有规定这条已消费的冲突接单是否满足同分配后续采集及终态的接单前置。它只限制 `stopped_by_cancel` 的产生条件，没有明确其入站处置和收据。现有竞态样例从 Cloud 已收到接单和采集开始，无法判别两种实现。预期是在终态仍为 `cancelled` 的前提下，能按序保留授权合规的迟到事实及稳定收据。否则 M4.3 可能只从业务投影寻找接单，从而拒绝 `seq=2` 及后续，分配队列无法收敛。最小修订是说明已消费的合法冲突接单如何作为因果证据，补齐 `stopped_by_cancel` 的收据与审计规则，再补一条 Cloud 取消时 Edge 尚未上报、重连依次回报 `accepted → capture → finished` 并重放的验收轨迹。维持已有 Q2 终态和权限规则。

**W2 · Q5 B 的续传验收没有明确要求多分片输入。** 位置 `docs/contracts/cloud-edge-sync-v1.md:405–410`、`:495`，对照 `docs/contracts/cloud-capture-media.md:99`、`services/cloud/src/swimplatform/media_transfer.py:294–309`。对应 Q5 B、R8/S8.1、媒体验收 M3。M4.4 小样例将仓库中的 894 字节 MP4 描述为隔离输入，该文件按当前 16 MiB 布局仅有一个分片。现有矩阵要求进程重启后保留已确认分片并续传，未明确验收时必须同时存在已确认和待传分片。预期是验证同一获准资产和 UploadSession 的部分文件续传。若全程使用小样例，最多能验证重取单分片回执或补重传完整单片，无法证明续传只发送缺失分片。最小修订是在 M3 向量指定至少两片的合成 MP4，保留 894 字节样例作为意图示例。可引用已有合成素材生成方式，在第一片确认后中断，重启使用相同批准、发起者及 upload ID，列出已确认部分并补传其余分片。[既有隔离 MP4 生成与布局用例](https://github.com/TuIanL/zhiyong-swim-platform/blob/4588e6905ad876fb8bcc1edb5a3280f21703200a/services/cloud/tests/test_media_transfer_storage.py#L973-L1036)

### SUGGESTION（2）

**S1 · 点明上行收据的作用域匹配来源。** 位置 `docs/contracts/cloud-edge-sync-v1.md:73`、`:78`、`:331–336`。对应 R1/R3、S3.2/S3.3。收据示例只包含事件 ID、分配 ID、序号及处置，文字同时要求归属匹配。预期是通过当前受认证的请求上下文和本地待发信封核对 Tenant/Site/Node，再核对回包 ID 与序号。建议明确这一点，避免实现端自行扩展响应字段或只匹配序号。

**S2 · 在归档动作中复核 Change 文档路径。** 位置 `openspec/changes/define-cloud-edge-sync-contract/proposal.md:11,21,39`、`design.md:43–49`、`tasks.md:25–29`、`candidate-contract.md:5–9`。对应文档追溯与 Task 3.2。现有链接在活动目录下均可达。静态模拟单纯移到 `openspec/changes/archive/<date>-define-cloud-edge-sync-contract/` 后，四份 Change 文档含 **44** 个指向仓库其他目录的相对链接需要调整。预期归档后仍能定位正式契约与证据。建议在经批准的归档流程里修正受影响的相对深度，或改用固定提交链接并重跑链接检查。本轮没有执行 Archive。

## 7. 归档建议及停止位置

OpenSpec 形式前置已满足，Change 是 `skip_specs: true` 且 7/7 的纯文档交付。**工程核验暂不建议将当前 Head 归档**。W1 和 W2 应在授权后的最小文档 Remediation 中补清并复核。建议处理 S1，并在未来归档时纳入 S2 的链接验证。本轮到报告为止，PR 保持 Open / Draft / 未合并。
