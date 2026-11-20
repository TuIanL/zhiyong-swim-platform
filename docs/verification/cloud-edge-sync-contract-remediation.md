# M4.1 Post-Verify 文档 Remediation

**2026-11-18（Asia/Shanghai） · Remediated - Awaiting Re-Verify**

首轮独立 Verify 的结论是 **CRITICAL 0 / WARNING 2 / SUGGESTION 2**。本轮按负责人授权修订 W1、W2、S1，供第二轮独立 Verify。S2 留待正式 Archive。

## A. 固定基线

| 用途 | 提交 |
| --- | --- |
| main | `94fed6b03d50ccca52f6ec959bcde1636148c65c` |
| 原 Apply Head、原 Verify 核验 Head、Remediation 起点 | `4588e6905ad876fb8bcc1edb5a3280f21703200a` |
| Commit A，原始 Verify 报告原样入库 | `7e37c4e3778e0b33c2ce2ccbcfb42cc4af630aaa` |
| Commit B，最终契约及架构文档 Head | `ce16198de4a56a9af44305b8d7af98f2940019ba` |

本报告以 Commit B 为文档核验对象。报告提交及其 CI 由 PR 正文绑定最终 Head。[Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) · [首轮独立 Verify](https://github.com/TuIanL/zhiyong-swim-platform/blob/7e37c4e3778e0b33c2ce2ccbcfb42cc4af630aaa/openspec/changes/define-cloud-edge-sync-contract/verification.md) · [原 Apply 7/7](cloud-edge-sync-contract-apply.md)

## B. W1 取消后的离线补投

原缺口在于 Cloud 已取消并消费迟到接单后，后续事实可能从任务投影查不到接单前置，而且 `stopped_by_cancel` 的入站处置未确定。

- API 契约第 26 行的 D4 小节把因果依据绑定同一 Assignment 已消费的 Inbox 接单记录，接单处置可以是 `applied` 或 `conflict_recorded`。Cloud 校验当前身份、归属、关联、Event ID、连续序号及因果，在一个事务写 Inbox、审计、流位置和收据。迟到接单、采集、真实终态沿序号 1、2、3 消费，保持 `cancelled`，不写正常采集投影或媒体状态。合同走读消除了仅因投影为取消而把合法后续序号卡住的分支。
- 取消应用前已实际完成或失败的 Edge 保留原 `completed/failed`，后到取消不重写事实。只有持久应用同一分配取消命令且执行器实际因此安全停止时，才以对应命令版本上报 `stopped_by_cancel`。Cloud 核对已提交取消命令、版本和同分配接单，保存停止 outcome 和命令关联。丢失 Command ACK 不阻断合法停止回报。
- 合法新事实沿用 HTTP 200 `conflict_recorded/task_cancelled`，包括 `stopped_by_cancel`。收据含原事件、分配及序号。原信封重放返回原收据且不重复推进，异参、缺序、未来版本、无效身份、越域及跨 Assignment 因果引用按原有错误结构拒绝并保留待发项。第 444 行补正反收据，第 526 行增加 W1.1–W1.7，完整走读 `accepted → capture.recorded → finished` 和独立停止分支。架构第 49 行记录事务/投影边界。[D4](../contracts/cloud-edge-sync-v1.md#late-cancellation-replay) · [W1 矩阵](../contracts/cloud-edge-sync-v1.md#w1-vectors)

## C. W2 人工批准媒体续传

API 契约第 419 行保留 894 字节 MP4 作为轻量上传意图示例。M7 指定可复现的 20 MiB 有效合成 MP4，通过给原样例追加合法 ISO-BMFF `free` box 生成，位于临时目录。未来 M4.4 必须使用 **ffprobe 6.1.1** 记录媒体验证信息。

| 核验项 | 本轮实际证据与后续验收 |
| --- | --- |
| 夹具与布局 | 临时文件实际大小 **20,971,520 字节**，SHA-256 为 `ca553583858bab2781f3e8f09cab40c9069a6a4bd93b8d6df540919c92382fb0`。按当前 M3 16 MiB 布局计算两片，为 **16,777,216 + 4,194,304 字节**。本机 ffprobe **8.1.2** 静态探测成功，识别 MP4、MPEG-4 16×16 视频流和 1 秒时长。实际 M4.4 的固定版 ffprobe 取证仍待执行。 |
| 人工批准及第一片 | M7 要求绑定 Session、资产、用途及现行 M3 授权，持久记录唯一批准、原发起人、Asset、UploadSession、意图键和指纹。上传第一片并确认，再用 ListParts 证明已持久。此刻网络观测须证明第二片尚未传。此处为验收设计，实际分片回执由 M4.4 采集。 |
| 中断及续传 | M7 要求确认首片后终止测试上传进程并重启 Edge，从原批准、原文件、持久卷与 UploadSession 恢复。按 ListParts 对账，仅补签并上传第二片。用网络记录断言首片新增 PUT 为 0、补传数为 1，保留首片回执及同一上传标识。实际重启、回执和网络观测由 M4.4 采集。 |
| 整对象、权限与本地原件 | M7 按原 M3 Complete、授权及 worker 验证精确版本、大小、SHA-256 和媒体有效性，成功后方可提交 completed/ready。负向覆盖未批准、批准记录丢失、获准文件变化、坏摘要、身份撤销/过期和媒体探测失败。记录最终对象版本、校验结果及 Edge 原件存在和哈希。实际对象版本与原件保留证明由 M4.4 采集。 |

M1–M6 原矩阵保留，M7 在第 571 行独立追加，详细输入和阶段取证从第 573 行开始。未批准分支通过隔离批准门槛保证零上传意图，沿用原 M3 API 权限。正式审批、真实视频和生产准入继续按 ADR 0004。[M7 生成、取证及负向用例](../contracts/cloud-edge-sync-v1.md#m7-multipart-resume)

## D. S1 上行收据

API 第 91 行新增收据作用域规则。Cloud 从当前有效节点身份推导 Tenant/Site/Node。Edge 先将具体请求的认证作用域与本地不可变 Outbox 和当前上下文核对，再验回包的分配、事件 ID、序号及处置。只有完全匹配才确认对应待发项，同收据重放幂等。最小响应字段未新增。第 544 行的 S1-R1–S1-R4 分别覆盖正确匹配、错 event ID、错 Assignment/sequence、跨 Node 绑定。[收据契约](../contracts/cloud-edge-sync-v1.md#receipt-scope) · [S1 矩阵](../contracts/cloud-edge-sync-v1.md#s1-vectors)

## E. 追溯与静态检查

- 原验证报告整文件 SHA-256 为 `84d038c4448c652deb145d9480b8d7cd885107311ab819ac45aa8f3a3a25c902`，Commit A 只新增该文件，后续逐字节保持。原 Apply 报告及 Tasks 的 7/7 与 `4588e69` 一致。
- Commit B 保留原 R1–R8、19 个 Scenario、19 个 T/A/C/L 向量、M1–M6 全部编号和矩阵行。新增 W1.1–W1.7、S1-R1–S1-R4 及 M7，候选契约第 10 行、Design 第 71 行接入本轮追溯。ADR Q1–Q7 未改，P01–P10 数值及隔离环境适用范围未改。
- Change strict 通过，`skip_specs: true` 有效且无行为 Delta。主规格 strict **6/6**，既有 Archive strict **6/6**。对照 main 的既有规格与业务代码无 diff。
- Commit B 的 9 份 Markdown 静态检查覆盖 **100 个相对链接、51 个锚点、11 个 JSON 样例**，Git diff 空白检查通过。S2 归档后路径调整保留为待办。
- W1、W2、S1 的文档方案已交付。两项 WARNING 仍等待第二轮独立 Verify 确认关闭；当前自检未识别新增契约歧义。M4.4 正反向运行及取证保持后续实施归属。
