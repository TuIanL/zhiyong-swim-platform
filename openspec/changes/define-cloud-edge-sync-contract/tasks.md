# Tasks

本 Change 的 7 项任务只跟踪纯文档契约签认及交付，负责人已明确授权本次纯文档 Apply。Q1–Q7 已批准结论见 [决策表](design.md#decision-signoff)。矩阵中的运行证据归属后续 Change。

## 1. 确认范围与权威

- [x] 1.1 记录负责人对 Q1、Q2、Q5、Q7 涉及 v1 范围的决定。逐行核对 TrainingSession、训练任务、采集、媒体、分析执行及报告的权威和白名单，走读 T1–T9 的权限、全生命周期单任务/单分配与幂等，验收 R2、R6、R8 的正负案例及未经授权的原视频传输为零这一约束。
- [x] 1.2 记录 Q3、Q4 的凭据与下发决定。核对 D12 的默认/最长有效期、服务端截止、同节点受控再签发和越权拒绝边界，走读 S1.1、S7.1、S7.2 及 C1–C4 对自然过期、仅撤钥、已验证停用、有效新凭据和本地解挂的区分。

## 2. 确认协议与对账规则

- [x] 2.1 按决定确认请求/响应字段、允许事件、状态码、规范化指纹和错误结构。核对双方可独立走读的同义 JSON、异参、越权、未知版本和成功/冲突收据样例，以 S1.1、S1.2、S3.3、S5.2 对照验收。
- [ ] 2.2 按 Q6 确认 ACK、事务边界、退避预算、重连水位和人工恢复规则。用 A1/A2 核对持久接收、Command ACK、业务接单和实际执行，用 S3.1、S3.2、R4、S5.1 核对提交前失败、提交后丢响应、乱序、重启和游标丢失。
- [x] 2.3 走读取消与完成的双顺序、父 Session 取消和 Edge 尚未执行三条轨迹，并确认 scope/序号、冲突收据和本地事实均可追溯。对照 R6 与 L1–L4，确认 M4.3 的 PostgreSQL 竞态计划具有固定锁序、并发顺序与可观察断言。

## 3. 核对追溯与交接

- [x] 3.1 从 M1–M3 主规格和归档复核继承的权限、状态、媒体规则，逐条核对下列矩阵、四个切片的独立完成标准和兼容性影响。确认 R1–R8 保留原 19 个 Scenario ID，各实施 Change 从候选契约只提取自己交付的行为 Delta，满足状态应由实现证据支持。
- [x] 3.2 以 `openspec validate define-cloud-edge-sync-contract --strict` 及 `openspec validate --specs --strict` 校验，确认 CLI 标记 specs skipped、Change 内无可归档 Delta，核对本地链接、样例和 Git 差异，输出负责人签认版本与后续各 Change 的验收入口。

## Requirement / Scenario 验收矩阵

<a name="acceptance-matrix"></a>

- [R1–R8 与 19 个原始 Scenario 及运行证据归属](../../../docs/contracts/cloud-edge-sync-v1.md#acceptance-matrix)
- [19 项 T/A/C/L 定向验收](../../../docs/contracts/cloud-edge-sync-v1.md#targeted-matrix)
- [6 项 Q5 B 人工批准媒体联调](../../../docs/contracts/cloud-edge-sync-v1.md#media-matrix)

Task 2.2 的已批准语义及走读见 [D3](../../../docs/contracts/cloud-edge-sync-v1.md#delivery) 和 [Q6 参数登记](../../../docs/architecture/cloud-edge-sync-v1.md#timing-register)。原完成定义要求确认退避预算。单轮次数/时限及重置条件目前只有开发与测试建议，保持未完成。
