# Proposal

**M4.1 · Cloud–Edge Reliable Synchronization · 二轮 Propose · 待负责人签认**

## Why

M3 合并后，已登记的节点可以使用受限身份传输媒体，云端可以验证整对象并发布媒体。任务控制、离线事实回报及重连仍需要共同契约。M4.1 先交付可独立评审的文档，让 Edge 和 Cloud 实施切片可以引用同一份设计和验收证据计划。

## What Changes

- 以纯文档契约记录方向、信封、角色与范围、任务生命周期、ACK、冲突、重试、重连和安全停止。把原 R1–R8 及 19 个 Scenario 移至 [候选行为契约与样例](candidate-contract.md)，保留 ID 和追溯，另补任务控制、凭据及 PostgreSQL 验收向量。
- 继承负责人已批准的本地优先与有效身份边界。已业务接单的任务可在一般断网或自然过期时继续本地执行，原片默认留场馆。云端凭据受服务端截止及撤销约束，媒体传输继续走 M3。
- 推荐一个 Session 在整个 v1 生命周期最多一个任务，每个任务固定一个节点、一次分配，终态也占用名额。创建与指派原子提交。Q1 待签认，选择活动任务唯一的替代方案时须先修改契约及其验收。
- 审阅 [Q1–Q7 决策表](design.md#decision-signoff)。后续由 M4.2、M4.3 分别提出范围内的行为 Delta，M4.4 验收真实双端收敛。实际能力以实施验收证据为准。

## Capabilities

### New Capabilities

无。沿用 [采集与媒体领域契约归档先例](../archive/2026-11-10-define-cloud-capture-media-contracts/proposal.md)，本 Change 声明 `skip_specs: true`。候选行为文档位于 Change 根目录，未来 M4.1 归档只保存文档。

### Modified Capabilities

无。M4.2/M4.3 应在各自的实施 Change 中增列已签认且由本切片交付的 Delta。M4.3 需显式评审 Registry 的同步权限与 Session 取消的增量；此前主规格仍为当前行为权威。

## Impact

| 范围 | M4.1 文档交付 | 后续影响 |
| --- | --- | --- |
| 数据库及 API | 任务控制、同步路由、数据与锁序设计 | M4.2 独立 Edge 持久化；M4.3 增量 Cloud 任务、日志、Inbox 和投影。迁移与业务入口在实施 Change 审查 |
| 媒体 | 记录 M3 传输、权限、验证和既有状态边界 | 合成闭环验证元数据；获准的媒体传输复用 M3 |
| 验收 | 决策表、候选行为、协议样例、两层矩阵 | 后续以各切片的测试、运行证据和实现验收判定满足 |

原始评审 Head 为 `b2bb18313d9fc1b66d85ee391b8e11aee23bff1d`。基线为 `main@94fed6b03d50ccca52f6ec959bcde1636148c65c`，合并后 main CI 三项通过。[Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) · [PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6) · [main CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894)
