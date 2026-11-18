# Proposal

**M4.1 · Cloud–Edge Reliable Synchronization · 2026-11-18 · 待负责人评审**

## Why

M3 合并后，已登记的节点可以使用受限身份上传视频，云端可以验证整对象并发布媒体。云边仍缺少可独立验收的任务下发、离线事实回报与重连收敛契约。先冻结数据权威、事件格式和失败语义，Edge 和 Cloud 后续可以分别开发、验证和联调。

## What Changes

- 提议冻结 v1 契约，覆盖云端任务分配与取消、Edge 接收确认、最小采集元数据和执行终态回报。定义作用域、版本、事务边界、ACK、补投、对账和冲突语义。
- 保留 Cloud 对正式 TrainingSession、任务控制、媒体验证与报告发布的权威；Edge 记录本地采集和执行事实。已持久接收的任务可离线继续执行，原始视频默认留在场馆。
- 将 M4 划为四个独立验收切片。本轮仅建立 M4.1。契约冻结需取得负责人确认，运行时和接口交付各自另立 Change。
- 以 Requirement/Scenario 对照表、正负例及可复核的环境方案作为评审证据。

## Capabilities

### New Capabilities

- `cloud-edge-sync` — 云边训练任务指令和 Edge 事实的版本化交换、可恢复投递与权威投影。

### Modified Capabilities

当前提案以六份主规格为兼容基线。后续实现 Change 为 Edge 增加同步操作时，应在对应 Delta 中明确扩充 `cloud-edge-registry` 的允许操作范围，并核对 `cloud-training-session` 的取消语义。

## Impact

| 范围 | M4.1 交付 | 后续影响 |
| --- | --- | --- |
| 数据库 | 四件评审文档内的逻辑契约 | M4.2 独立 Edge 本地任务/Inbox/Outbox；M4.3 Cloud 任务、下发日志、Inbox 和窄投影。DDL 与迁移方案分别评审 |
| API | 请求、响应和冲突语义草案 | M4.3 新增节点专用同步路由，沿用当前节点身份与当前授权检查 |
| 媒体 | M3 为既有传输及 `ready` 权威 | 同步回报只传允许的元数据；有明确授权的媒体续传复用 M3 |
| 验收 | 静态规格校验、契约样例走读及负责人决策 | M4.2 和 M4.3 独立验证各自的持久化和事务，M4.4 验证真实双端收敛 |

基线为 `main@94fed6b03d50ccca52f6ec959bcde1636148c65c`。PR #6 已合并，合并后的 main CI 三个 Job 均成功。两个 Notion P1 任务当前均处于待确认，本提案只承接最小工程切片。[PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6) · [main CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894) · [Notion 云边同步任务](https://app.notion.com/p/410f602574aa8181a19ae87e25b62b4d) · [Notion Edge 部署包任务](https://app.notion.com/p/410f602574aa81608463d9de3e26368a)
