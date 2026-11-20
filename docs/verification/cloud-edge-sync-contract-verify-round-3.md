# M4.1 第三轮独立 OpenSpec Verify

**2026-11-20（Asia/Shanghai） · `define-cloud-edge-sync-contract`**

**W3 在 M4.1 文档契约范围内正式关闭。0 CRITICAL、0 WARNING、1 SUGGESTION。** S2 继续留待正式 Archive。工程核验可交由负责人作归档决策。

## 固定对象与证据

| 项目 | 基线 |
| --- | --- |
| 第三轮核验 Head | `e350c753184cc36828c6f2659967c9f462e55a0c`，本地、远端 PR 和 CI Run 绑定一致 |
| PR #7 | `docs/m4-cloud-edge-sync-contract → main`，Open / Draft / 未合并。[Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7) |
| main | `94fed6b03d50ccca52f6ec959bcde1636148c65c` |
| 首轮与第二轮 | 分别固定于 `4588e69` 和 `93548e5`，两份报告与其各自首次入库的 Git blob 逐字节一致。[首轮 Verify](../../openspec/changes/define-cloud-edge-sync-contract/verification.md) · [第二轮 Verify](cloud-edge-sync-contract-reverify.md) |
| W3 修订 | `ee54dc7` 固定重叠条件下的收据优先级，`e350c75` 固定审计数组并补追溯和报告。[W3 Remediation](cloud-edge-sync-contract-w3-remediation.md) |

## OpenSpec 核验

| 维度 | 结果 |
| --- | --- |
| 完整性 | `spec-driven`，Proposal、Design、Tasks 均完成。Apply Tasks **7/7**，剩余 0。CLI 确认 specs skipped，`skip_specs: true` 且无行为 Delta。Spec Coverage 不适用 |
| 正确性 | 完成 W3 组合条件、对照分支和重放的契约走读。M4.1 是纯文档交付，行为 Delta 的实现映射与运行场景覆盖不适用。W3.1 的运行取证仍归 M4.3/M4.4 |
| 一致性 | D4、Q7 样例、W3.1、Candidate Contract、Design 与 W3 Remediation 一致。Q1–Q7 签认及 P01–P10 隔离范围保留。代码模式检查不适用，PR 差异只有文档及 Change 元数据 |

## W3 关闭依据

第二轮 W3 记录了 D4 与 Q7 同时成立时收据 code 的歧义。第三轮将有效 Node 身份、同归属 Assignment 和 Device、已经消费的 `accepted@1` 及合法连续的 `capture.recorded@2/v1` 作为组合场景输入，逐项核对如下。

| 路径 | 核验结果 |
| --- | --- |
| 任务已取消且设备已停用，首次消费 | HTTP 200、`disposition=conflict_recorded`，公开收据只使用 `code=task_cancelled`，关联原事件、分配及序号。消费事务内的内部字段 `conflict_reasons` 严格等于有序字符串数组 `["task_cancelled","device_disabled"]`，两项各出现一次。数组未进入公开响应结构 |
| 投影与水位 | 同事务新增一条 Inbox 及其收据和冲突审计，期望序号 2 推进到 3。Task 保持 `cancelled`，无正常采集投影、上传意图或 `VideoAsset.ready` |
| 相同信封重放 | 当前认证和归属合法时返回原逻辑收据。设备状态随后改变时仍沿用原 code 和审计数组顺序。期望序号保持 3，原 Inbox、收据、审计及业务投影均无新增或重写 |
| 原有边界 | 仅同归属 Device 停用且无任务取消冲突时，Q7 仍给出 `device_disabled`。凭据无效、越域、异参、缺序的原拒绝规则仍适用。首投和重放均受现行身份与归属校验约束 |

正式规则与组合向量分别可从 [D4](../contracts/cloud-edge-sync-v1.md#late-cancellation-replay) 和 [W3.1](../contracts/cloud-edge-sync-v1.md#w3-vectors) 定位。Candidate Contract 将 Q2/Q7、R3/R6 和 W1.3 追溯到 W3.1，Design 对应 M4.3 的事务与重放验证以及 M4.4 的离线组合复测。

第二轮对 W1/W2 的关闭和 S1 的满足结论继续成立。W1 原矩阵、S1 段落与 M1–M7 保留。**S2 为本轮唯一 SUGGESTION**，在正式 Archive 中复核文档移位后的相对路径和锚点。

## 静态检查

- Change strict 通过。主规格 strict 6/6、既有归档 strict 6/6。六份主规格、既有归档、实现代码、OpenAPI、迁移和 CI 配置与 main 一致。
- 核对十二份 Markdown，126 个相对链接和 69 个锚点可达。10 个代码块 JSON 样例及 3 个内联 JSON 对象可解析，公开 JSON 样例未新增内部审计字段。保留原 8 个 Requirement、19 个 Scenario、19 个 T/A/C/L 向量、W1 七项、S1 四项和 M1–M7。
- 对 main、第二轮 Head 和当前工作树运行 `git diff --check` 均通过。相对 main 的 13 个路径只含 Markdown 和 Change 元数据。两轮历史 Verify 报告、原 Apply 报告、Tasks 和 ADR 均保留。

## 固定 Head 的 CI

[CI Run 44690046107](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107) 已完成，3/3 Job 成功。三份原始日志均检出 `refs/pull/7/merge` 的 `0dcabcad88ee255931a3fa36ad205242b0968cbf`。该 GitHub 测试合并提交相对固定 Head 领先 1、落后 0、文件差异为零。两份 artifact 元数据均绑定 Run ID 和 `e350c75` 的完整 SHA。[GitHub Compare](https://github.com/TuIanL/zhiyong-swim-platform/compare/e350c753184cc36828c6f2659967c9f462e55a0c...0dcabcad88ee255931a3fa36ad205242b0968cbf)

| Job | 结果与清理 | 证据 |
| --- | --- | --- |
| SQLite | 210 passed、92 skipped | [原始日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107/job/136133401283) |
| PostgreSQL 17 | 281 passed、21 skipped。专用容器 `swim-pg-test-56d8e4d4bba052ed` 清理为 `removed`，复查 `absent`、退出码 0 | [原始日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107/job/136133400874) · [Artifact](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107/artifacts/14607679023) |
| 隔离 RustFS | 成功，ffprobe 6.1.1-3ubuntu5。专用容器 `swim-rustfs-22b51a5e2f27` 清理为 `removed` | [原始日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107/job/136133401257) · [Artifact](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44690046107/artifacts/14608301497) |

CI 证据范围为 M1–M3 兼容性回归。第三轮止于独立报告，PR 保持 Draft。
