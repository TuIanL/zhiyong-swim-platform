# M4.1 W3 Remediation

本报告独立记录 W3 的文档修订。负责人确认，当任务取消和同归属设备停用同时成立时，对外收据以 `task_cancelled` 为准，内部审计同时保留两项原因。

## 基线与历史

| 用途 | 提交或证据 |
| --- | --- |
| main 基线 | `94fed6b03d50ccca52f6ec959bcde1636148c65c` |
| 首轮 Verify 核验 Head | `4588e6905ad876fb8bcc1edb5a3280f21703200a`。[首轮报告](../../openspec/changes/define-cloud-edge-sync-contract/verification.md) |
| 第二轮 Verify 核验 Head | `93548e58662f3a94de82b186738d6231928a2c4c`。W3 记录 D4 与 Q7 的组合条件未规定收据 code 优先级。[第二轮报告](cloud-edge-sync-contract-reverify.md#第二轮仍待处理) |
| W3 初次修订及本次补齐的基线 | `ee54dc758869b1f9f64041431cca85f935d83aa0`。已增加 W3.1 并明确优先级及两项审计原因。[基线 CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44660777749) |
| 交付入口 | [Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) · [当前 Head 的 CI](https://github.com/TuIanL/zhiyong-swim-platform/pull/7/checks) |

## 契约与组合验收

| 项目 | 文档断言 |
| --- | --- |
| 首次消费 | 有效 Node 且归属、因果及连续序号合法。对同一分配的组合冲突返回 HTTP 200，`disposition=conflict_recorded`，单一 `code=task_cancelled`。仅设备停用且无任务取消冲突时仍返回 `device_disabled` |
| 内部审计 | 同一消费事务中的逻辑字段 `conflict_reasons` 是有序字符串数组，值恰为 `["task_cancelled","device_disabled"]`。按此顺序比较，拒绝将顺序差异、重复项或额外项视为满足。公开收据沿用原字段 |
| 序号与投影 | 先前已消费接单序号 1。合法采集序号 2 仅消费一次，期望从 2 推进到 3。Inbox、收据与审计同事务持久化。Task 保持 `cancelled`，正常采集投影、上传意图和 `VideoAsset.ready` 均无新写入 |
| 重放 | 同 ID、同信封且当前认证和归属有效时，包含设备状态随后改变的分支，返回原逻辑收据。期望序号保持 3，原有序审计和投影均无新增或重写 |

正式规则位于 [D4](../contracts/cloud-edge-sync-v1.md#late-cancellation-replay)。[W3.1](../contracts/cloud-edge-sync-v1.md#w3-vectors) 记录完整预期，Candidate Contract 和 Design 均回链该向量。M4.3 负责事务及重放运行验收，M4.4 负责离线补投组合联调。

## 检查与阶段边界

- Change strict 和主规格 strict 校验通过。Change 继续使用 `skip_specs: true`，无行为 Delta，Apply Tasks 保持 7/7。
- 核对修订文档的相对路径、锚点、原验收编号、两轮 Verify 报告完整性及 Git diff。差异限于 W3 的契约、追溯和证据文档。
- W3 文档修订已记录。两轮 Verify 的原结论继续对应各自的固定 Head，S2 留待正式 Archive。CI 证据用于 M1–M3 兼容性回归。
