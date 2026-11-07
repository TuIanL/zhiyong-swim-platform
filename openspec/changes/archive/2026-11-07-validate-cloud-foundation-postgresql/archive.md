# PostgreSQL 云端基础验证归档记录

- change：`validate-cloud-foundation-postgresql`
- schema：`spec-driven`
- 归档日期：2026-11-07（Asia/Shanghai）
- 授权：负责人要求先修复 W1/W2、完善 S1 后归档，并明确选择先同步主规格再归档；S2 记录为后续改进。
- 产物：proposal/specs/design/tasks 全部 done；CLI 任务16/16，无未完成项。

## 规格同步

唯一增量 [cloud-identity](specs/cloud-identity/spec.md) 已合入[主规格](../../../specs/cloud-identity/spec.md)。1项修改为 Isolated database validation，5项新增为 PostgreSQL schema integrity、PostgreSQL authorization parity、Timezone independent authentication deadlines、PostgreSQL transactional account operations、Reproducible PostgreSQL validation evidence。

同步保留原标题、Purpose 与其余4项要求，主规格共10项要求、22个场景；6个增量要求全部逐块核对一致，无删除或重命名，无剩余待同步操作，也无 delta 操作标题混入主规格。同步后主规格 strict、归档前 change strict 均通过。

## 修复及测试证据

[核验报告](verification.md)保留独立 verify 历史及后续修复复核：W1 的18格拒绝写入与六表无副作用、owner/admin自身授权撤销、严格201；W2 三个唯一写入各自证明不同物理连接；S1 类别非空与12项防退化回归。当前 CRITICAL0/WARNING0/SUGGESTION1，唯一 S2 由负责人明确留后续改进：仍未单独解析平台 manifest digest，不把 index digest 或 Docker image ID 改名充当该证据。

实现修复提交 `4e3153098eefec9ae0fca1dee0a909d65caa1927`；归档前最终收口提交 `5fcab84fff71315ad2f8be67ee5fe02ff6d3b20b` 的 [CI 42331063389](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42331063389) 已 success：SQLite112 passed/39 skipped、PG150 passed/1 skipped，shared111/PG39，真实 removed、兜底 absent/exit0，run id `2e63a4493d7d0494`。本机完整结果及 P1 修复历史见[验证报告](../../../../docs/verification/cloud-foundation-postgresql.md)。

归档提交只改规格、文档和路径；其最新 head 与对应 CI 在 [PR #2](https://github.com/TuIanL/zhiyong-swim-platform/pull/2) 和 [Notion 当前阶段](https://www.notion.so/410f602574aa81288834cc297ae5b039)单独绑定，不用归档前结果替代。PR 保持 Draft，main `4968750` 未变，未执行 Merge。

## 归档完整性与范围

移动前后对原6份文件逐一核对 SHA-256 一致，含 `.openspec.yaml`、原提案、设计、任务、增量和核验记录；随后仅修正设计中的2处相对路径，并新增本记录。固定提交的历史证据链接保持原指向。

四项原 Notion 任务复用：云端基础与隔离基线待验收，数据模型与 RBAC 进行中。归档不代表整体任务完成；RLS、生产数据库部署、平台角色与未来领域仍未验收，不扩大本次业务范围。合并 PR 仍需负责人后续明确授权。
