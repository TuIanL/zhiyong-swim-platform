# Cloud Edge Registry Archive 记录

- Change：`implement-cloud-edge-device-foundation`；schema：`spec-driven`。
- 归档日期：2026-11-11（Asia/Shanghai）。
- PR：[#4 Draft](https://github.com/TuIanL/zhiyong-swim-platform/pull/4)，base `main`。
- 归档前 PR head：`904a4c0dfeeb818089b4e94c26c6074f8b146e84`；修复代码核验基线：`a9c7f21d483ddfc292f6e8870ebfddce19b324b9`。
- Apply 任务：14/14；第二轮独立 Verify：9/9 Requirements、33/33 Scenarios、CRITICAL 0 / WARNING 0 / SUGGESTION 5。

## OpenSpec 归档与主规格同步

先按已批准的 delta 同步主规格，再运行项目当前 OpenSpec CLI 正式归档命令：

```bash
openspec archive implement-cloud-edge-device-foundation --yes --json
```

CLI 返回归档目录 `2026-11-11-implement-cloud-edge-device-foundation`，`specsUpdated=false`、增删改计数均为 0；这表示两项增量已先行同步，归档时无需重写主规格。

- `cloud-edge-registry`：新建主规格，含 Delta 的 7 项 ADDED Requirements。
- `cloud-identity`：更新 `Isolated database validation` 与 `PostgreSQL schema integrity` 两项 MODIFIED Requirements；其余 8 项要求逐字节保留。
- 为满足当前 OpenSpec strict 的要求描述长度规则，`Isolated database validation` 将原有身份、schema 与最小权限细节整理进其既有“Restricted application identity”场景；需求名称、行为边界及 Change 的 33 个场景总数保持不变。
- 没有将 S1–S5 提升为新 Requirement，也未扩大 Change 范围。

## 历史文件与核验记录

- [README](README.md)、[Proposal](proposal.md)、[Design](design.md)、[Tasks](tasks.md)、[Spec Delta](specs/)、[.openspec.yaml](.openspec.yaml) 均保留。
- [首次未通过 Verify](verification.md) 未被覆盖；[第二轮通过的 Verify](verification-remediation.md) 原文保留，结论仍为 CRITICAL 0 / WARNING 0 / SUGGESTION 5，并保留 S1–S5。
- Apply 的 [14/14 交付报告](../../../../docs/verification/cloud-edge-device-foundation-apply.md) 与 [Apply 后 W1/W2/W3 修复报告](../../../../docs/verification/cloud-edge-device-foundation-remediation.md) 仍在正式验证文档目录。
- 归档前的九份 Change 文件经 SHA-256 核对后逐字节保留；原始六表迁移 `20261106_0001` 与四表增量迁移 `20261110_0002` 均未改。

## 归档后检查

- 活跃 Change：0。
- 主规格 strict：`cloud-edge-registry` 与 `cloud-identity` 均通过。
- 已归档 Changes strict：4/4 通过，包含本 Change；Apply Tasks 保持 14/14。
- `git diff --check`、Markdown 相对链接及标题锚点检查通过。
- Notion 项目工程入口和原 P1 Edge Node 任务记录本次归档与主规格同步；Edge Node 任务保持待验收，不代表整个模块或总体架构已完成。

最终归档提交、与该 head 绑定的 CI 和 Draft 状态已同步到 [PR #4](https://github.com/TuIanL/zhiyong-swim-platform/pull/4) 与 Notion 工程入口。
