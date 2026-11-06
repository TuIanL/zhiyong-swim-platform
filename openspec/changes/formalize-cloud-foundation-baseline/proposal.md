# Proposal

## Why

新版云端基础已在提交 `7082b729785957252ff5797a057f3151c6dd25c2` 实现，但当时只建立主规格，没有通过完整 OpenSpec change 留存设计、任务和需求追溯。现在需要如实补录历史基线，形成可评审的 ERD、权限矩阵、API 契约和证据映射，支撑后续 PostgreSQL 验证与领域扩展。

本变更为事后文档登记，创建日期为 2026-11-06；不追认事前审批，不把测试通过等同于产品、架构或生产部署验收通过。

## What Changes

- 记录既有实现的提交、独立工程边界、历史验证来源、已知限制和待评审事项；区分本轮文档校验与此前的代码/CI验证。
- 提交六张表的 ERD、主外键/唯一约束、归属规则及后续实体的取舍边界。
- 固化为评审草案的角色—资源—操作矩阵、服务端校验链路和跨机构/场馆负向用例映射。
- 对照生成的 OpenAPI，整理 14 个 path、19 个 HTTP operation（17 个业务操作及2个健康操作）的鉴权、请求、响应、错误、版本与兼容性说明。
- 将主规格的5项要求与代码、测试、历史验证和 Notion 任务关联，明确哪些行为仅有源码证据、哪些已有运行证据。
- 在后续 apply 阶段把已评审材料同步到正式文档位置，完成文档验证后再申请归档；本提案阶段不执行这些清单。
- 本变更不修改 API 行为、业务代码、数据库模型、迁移、运行配置、依赖或测试；不连接、迁移或导入旧数据库，不接入 PostgreSQL/RLS、UI、Edge、媒体或模型服务。

## Capabilities

### New Capabilities

无。本变更只补充文档与治理记录，不新增系统能力。

### Modified Capabilities

无。`cloud-identity` 的5项现有行为要求保持不变。根据文档型变更规则，`.openspec.yaml` 明确设置 `skip_specs: true`，不生成规格增量，也不修改或同步主规格。

## Impact

- 当前规划产物：本 change 的 `proposal.md`、`design.md`、`tasks.md` 及 CLI 元数据。`design.md` 包含可直接审阅的 ERD、权限/API清单与证据映射。
- 后续 apply 的正式文档目标：`docs/baseline/cloud-foundation.md`、`docs/architecture/cloud-domain-model.md`、`docs/contracts/cloud-rbac.md`、`docs/contracts/cloud-foundation.md`、`docs/verification/cloud-foundation-baseline.md`。现有 `docs/verification.md` 作为历史验证记录保留；不覆盖或倒写历史。
- Notion 复用现有 OpenSpec 基线、数据模型、RBAC、架构契约四项任务，补充 change 链接和阶段说明，不重复建任务，不把总体平台设计或待验收能力标为已完成。
- 无新增依赖或破坏性接口变更。当前 SQLite 通过不能证明 PostgreSQL/RLS、并发事务、生产隔离或完整权限验收。
