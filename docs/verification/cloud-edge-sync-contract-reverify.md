# M4.1 第二轮独立 OpenSpec Verify

**2026-11-20（Asia/Shanghai） · `define-cloud-edge-sync-contract`**

**原 W1、W2 在 M4.1 文档范围内正式关闭，S1 已满足。第二轮结论为 CRITICAL 0、WARNING 1、SUGGESTION 1。** 新增 W3 记录任务取消与采集设备停用同时成立的收据歧义。S2 仍归正式 Archive。建议负责人审阅 W3 后再决定归档。

## 核验对象与历史

| 项目 | 固定证据 |
| --- | --- |
| 第二轮 Verify Head | `93548e58662f3a94de82b186738d6231928a2c4c`，本地 HEAD 与 GitHub PR Head 一致 |
| PR #7 | `docs/m4-cloud-edge-sync-contract → main`，Open / Draft / 未合并。[PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) |
| PR base | `94fed6b03d50ccca52f6ec959bcde1636148c65c` |
| 原 Apply 与首轮 Verify 核验 Head | `4588e6905ad876fb8bcc1edb5a3280f21703200a`。[Apply 证据](cloud-edge-sync-contract-apply.md) · [首轮 Verify 固定版](https://github.com/TuIanL/zhiyong-swim-platform/blob/7e37c4e3778e0b33c2ce2ccbcfb42cc4af630aaa/openspec/changes/define-cloud-edge-sync-contract/verification.md) |
| Remediation 证据 | 契约修订 `ce16198de4a56a9af44305b8d7af98f2940019ba`，报告随固定 Head 提交。[Remediation 记录](cloud-edge-sync-contract-remediation.md) |

首轮报告于 `7e37c4e` 单文件入库，与第二轮固定 Head 中的文件逐字节一致。SHA-256 为 `84d038c4448c652deb145d9480b8d7cd885107311ab819ac45aa8f3a3a25c902`。原结论保留为 0 CRITICAL、2 WARNING、2 SUGGESTION。

## OpenSpec 完整性、正确性与一致性

| 维度 | 本轮结果 |
| --- | --- |
| 完整性 | repo-local，`spec-driven`。Proposal、Design、Tasks 均已交付，7/7、剩余 0。specs 明确跳过且无 Delta，Spec Coverage 不适用 |
| 正确性 | 完成 W1/W2/S1 的文档走读、样例与现有 M3 接口交叉检查。Requirement Implementation Mapping 和 Scenario Coverage 的实现映射不适用，R/S 候选的运行证据由 M4.2–M4.4 各自交付 |
| 一致性 | 复核 Proposal、Design、Tasks、ADR、正式契约、架构和历史证据。Q1–Q7 签认为 A/A/A/A/B/A/A，ADR 与 P01–P10 表原样，参数限隔离开发和测试。新增 W3 为契约交叉条件歧义。代码模式检查不适用，固定差异无业务源码 |

## 首轮 Findings 复核

| 编号 | 裁决 | 独立核验依据 |
| --- | --- | --- |
| W1 | **关闭** | Cloud 先取消且接单未上报时，已消费的同 Assignment Inbox 接单事实可满足后续因果。W1.1–W1.4 走读得序号 1/2/3 均消费并获 HTTP 200 `conflict_recorded/task_cancelled`，Cloud 保持 `cancelled`，正常采集投影及媒体无新写入。W1.5–W1.6 区分持久应用取消后真实安全停止、取消到达前已完成或失败、仅收到指令或 ACK。不靠 Command ACK 证明停止，`stopped_by_cancel` 关联已提交取消命令及 v2，适用相同冲突收据。W1.7 验证同内容重放的原收据，以及异参、缺序、越域、跨分配前置的拒绝与不消费。停止正负样例明确 200 和 422。[D4](../contracts/cloud-edge-sync-v1.md#late-cancellation-replay) · [W1.1–W1.7](../contracts/cloud-edge-sync-v1.md#w1-vectors) |
| W2 | **关闭** | M7 明确要求两片、首片已确认且第二片缺失、重启后同批准/主体/UploadSession 恢复，以及 ListParts 对账后只补第二片。网络断言要求首片新增 PUT 为 0、补传数为 1。M3 仍使用已确认编号、大小和 ETag，Complete 以完整 manifest 提交，Worker 验证精确对象版本、整对象摘要、大小、媒体和现行授权后才发布 ready；原片保留。还覆盖未批准、批准丢失、撤权、摘要不符和探测失败。已独立运行文档的夹具生成与固定版探测步骤，真实传输和重启留给 M4.4。[M7](../contracts/cloud-edge-sync-v1.md#m7-multipart-resume) · [M3 契约](../contracts/cloud-capture-media.md) · [M3 ListParts 源码](https://github.com/TuIanL/zhiyong-swim-platform/blob/93548e58662f3a94de82b186738d6231928a2c4c/services/cloud/src/swimplatform/media_transfer.py#L866-L938) |
| S1 | **满足** | Cloud 按当前有效凭据推导 Tenant/Site/Node。Edge 核对具体请求的认证绑定、当前绑定与本地不可变 Outbox，再验 Assignment/Event ID/序号及处置。正向与重放幂等、错事件、错分配或序号、跨节点四组向量均明确本地确认结果，收据 JSON 字段保持原样。[作用域规则](../contracts/cloud-edge-sync-v1.md#receipt-scope) · [S1-R1–R4](../contracts/cloud-edge-sync-v1.md#s1-vectors) |
| S2 | **留待 Archive** | 活动目录链接全部可达。待经授权归档后，按首轮报告复核移位引起的相对路径和锚点。 |

M7 独立复现使用固定 Head 的 Bash 代码块和 ffprobe **6.1.1**，在临时目录生成后清理。文件 **20,971,520 字节**，按 M3 16 MiB 布局为 **16,777,216 + 4,194,304 字节**两片。探测确认有效 MP4、MPEG-4 视频流、16×16、1 秒。SHA-256 为 `ca553583858bab2781f3e8f09cab40c9069a6a4bd93b8d6df540919c92382fb0`。

## 第二轮仍待处理

- **CRITICAL 0。**
- **WARNING 1 · W3 取消与同归属设备停用重叠时的收据 code。** 复现输入为已取消的任务、同一 Assignment 已消费 `accepted@1`、有效 Node 凭据，接着收到合法连续的 `capture.recorded@2`，来源 Device 同归属但已停用。D4 和 W1.3 指定 `task_cancelled`，Q7 样例指定 `device_disabled`，两处未规定同时成立时如何选择。两处均要求 200、`conflict_recorded`、消费序号、保持取消终态及无正常采集投影，歧义限于首次收据的诊断值和应留存的原因。最小处理是在另行授权的修订中指定单一 code 的优先级，明确同时成立的原因如何审计，并加一条复合向量断言入库、无投影和同内容重放原收据。[D4 第 30 行](https://github.com/TuIanL/zhiyong-swim-platform/blob/93548e58662f3a94de82b186738d6231928a2c4c/docs/contracts/cloud-edge-sync-v1.md#L30) · [Q7 第 359 行](https://github.com/TuIanL/zhiyong-swim-platform/blob/93548e58662f3a94de82b186738d6231928a2c4c/docs/contracts/cloud-edge-sync-v1.md#L359) · [W1.3 第 536 行](https://github.com/TuIanL/zhiyong-swim-platform/blob/93548e58662f3a94de82b186738d6231928a2c4c/docs/contracts/cloud-edge-sync-v1.md#L536)
- **SUGGESTION 1 · S2。** 在正式 Archive 中核对 Change 文档移位后的链接。

## 静态检查和证据绑定

- `openspec validate define-cloud-edge-sync-contract --strict` 通过，CLI 确认 `skip_specs: true` 和零 Delta。主规格 strict 6/6、既有归档 strict 6/6。原 8 个 Requirement、19 个 Scenario 和矩阵行、19 个 T/A/C/L 向量及 M1–M6 保留。新增 W1 七项、S1 四项和 M7。
- 对固定 Head 的十份 Markdown 复核 106 个相对链接和 56 个锚点，解析 10 个围栏 JSON 样例和 3 个内联 JSON 对象。对 base、初轮 Apply Head 及工作树执行 `git diff --check` 均通过。GitHub 与本地差异均为 11 个路径，限 Markdown 和 Change 元数据。主规格、归档、业务源码、OpenAPI、迁移与 CI 工作流和 base 一致。
- [CI Run 44316824305](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305) 已完成，3/3 成功。逐个读取原始日志，实际检出 `refs/pull/7/merge` 的 `ef2a851eb9b69eae0f850e005871bef37af41a11`。GitHub Compare 相对固定 Head 领先 1、落后 0、文件差异为零。两份 artifact 元数据均绑定此 Run ID 与固定 PR Head。[GitHub Compare](https://github.com/TuIanL/zhiyong-swim-platform/compare/93548e58662f3a94de82b186738d6231928a2c4c...ef2a851eb9b69eae0f850e005871bef37af41a11)

| Job | 原始结果 | 证据 |
| --- | --- | --- |
| SQLite | 210 passed、92 skipped | [日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305/job/134845027977) |
| PostgreSQL 17 | 281 passed、21 skipped。清理 `removed`，同 Run 专用容器 `swim-pg-test-2f652ac78b86ad1a` 复查 `absent`、退出码 0 | [日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305/job/134845027136) · [postgresql-evidence](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305/artifacts/14433785492) |
| 隔离 RustFS | 成功，ffprobe 6.1.1-3ubuntu5。专用容器 `swim-rustfs-c6f6f694ec16`，ID `78e678e4d1e9841caf1cb8642b35c76abcc036a170047a3a10fafdc892419086`，清理为 `removed` | [日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305/job/134845026162) · [rustfs-media-evidence](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44316824305/artifacts/14433491367) |

CI 证据范围为 M1–M3 兼容性回归。第二轮报告单独保存，保留两轮各自的固定 Head 和结论。PR 仍为 Open / Draft / 未合并。
