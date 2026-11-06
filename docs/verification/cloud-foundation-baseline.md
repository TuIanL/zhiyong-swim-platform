# 云端基础验证与要求追溯

记录日期：2026-11-06。事实代码基线为 `7082b729785957252ff5797a057f3151c6dd25c2`，文档变更为 `formalize-cloud-foundation-baseline`，评审入口为 [PR #1](https://github.com/TuIanL/zhiyong-swim-platform/pull/1)。本文件记录文档实施和证据核对，不追认事前审批或生产验收。

后续独立verify已完成，见[核验报告](../../openspec/changes/archive/2026-11-06-formalize-cloud-foundation-baseline/verification.md)：对apply提交`b3139f1`的全部适用检查通过，12/12交付已核实；无CRITICAL/WARNING/SUGGESTION，3项规格检查为Not applicable。下文保留apply当时的记录与未验证业务范围，不代表独立verify仍未执行。该变更现已按用户明确调用的archive流程归档；归档后检查见[归档记录](../../openspec/changes/archive/2026-11-06-formalize-cloud-foundation-baseline/archive.md)，PR尚未合并。

## 五项现有主规格追溯

以下要求均来自[相同代码提交的cloud-identity主规格](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/openspec/specs/cloud-identity/spec.md)，无新增/修改要求。源码链接证明实现位置；测试链接证明用例存在，运行结论另绑定具体CI或历史本地记录。不能只凭函数存在就将其记为新测试通过。

| 现有要求 | 源码证据 | 已有测试用例 | 证据适用边界 |
| --- | --- | --- | --- |
| Ordinary account registration | [`register`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L82)、[`Registration`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/schemas.py#L32) | [`test_public_registration_rejects_privileged_fields`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L29)、[`test_registration_normalizes_email_and_does_not_leak_secrets`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L18) | 拒绝4种额外字段及邮箱规范化；不含邮箱验证/防滥用全链路 |
| Revocable sessions | [`identity`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L32)、[`login`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L91)、[`logout`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L118) | [`test_login_uses_hashed_tokens_and_logout_revokes_immediately`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L41)、[`test_expired_and_deactivated_sessions_are_rejected`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L53) | token摘要、过期、停用和当前会话退出；不含全部设备退出或密码重置 |
| Tenant resource isolation | [`membership`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L47)、[`list_tenants`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L139)、[`get_tenant`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L145)、[`site_access`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L61) | [`test_tenant_creation_and_cross_tenant_isolation`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L80)、[`test_cross_tenant_site_id_and_foreign_keys`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L148) | 有限用户/资源与跨机构site ID；不含PostgreSQL/RLS、连接池或并发隔离 |
| Explicit site scope | [`site_access`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L61)、[`list_sites`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L202)、[`remove_member`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/api.py#L182) | [`test_member_roles_and_site_scopes`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L98)、[`test_site_grant_revoke_and_member_removal`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L127) | 显式授权、撤销、成员移除级联；以coach为主，不是逐角色逐操作穷举 |
| Isolated database validation | [`main`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/cli.py#L8)、[`create_app`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/src/swimplatform/main.py#L11)、[临时库fixture](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/conftest.py) | [`test_startup_never_creates_schema`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L177)、[`test_cli_refuses_external_or_legacy_database`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L186)、[`test_migration_matches_models_and_ready`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_cloud_foundation.py#L169) | SQLite真实迁移、启动不建表、初始化拒绝外部目标；没有连接真实PostgreSQL |

安装回归另见 [`test_installed_package_finds_new_project_from_other_directory`](https://github.com/TuIanL/zhiyong-swim-platform/blob/7082b729785957252ff5797a057f3151c6dd25c2/services/cloud/tests/test_installed_package.py#L7)，防止pytest源码路径掩盖wheel安装后的根目录定位问题；它不测试业务权限。

## 历史运行结果与本次复查

| 证据 | 对应代码 | 结果/来源 | 本次如何使用 |
| --- | --- | --- | --- |
| 首版本地运行 | `7082b72` | [原记录](../verification.md)：22 passed、独立venv/wheel、pip check、真实health/ready/OpenAPI | 保留原文件原貌；本次未在本机重跑业务测试、安装依赖或启动HTTP服务 |
| 首版CI | `7082b72` | [42226710642](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42226710642)：completed/success | 本次通过GitHub连接器复查head_sha和结论，与代码基线一致 |
| 规划PR CI | `1db3952` | [42237575940](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42237575940)：先前已核实success | 只支持规划提交；不是apply提交结果 |

本地历史记录有1条Starlette/AnyIO BlockingPortal弃用警告；历史测试通过不等于没有依赖升级风险。CI配置见[工作流](../../.github/workflows/ci.yml)，push和PR会自动运行测试；最新文档提交的CI状态以PR对应head为准，不外推旧运行。

## 本变更的文档实施记录（apply阶段历史）

用户在本次对话确认规划草案无异议，随后明确调用apply；因此本次发布[基线](../baseline/cloud-foundation.md)、[ERD](../architecture/cloud-domain-model.md)、[RBAC](../contracts/cloud-rbac.md)、[API契约](../contracts/cloud-foundation.md)及本文。用户的草案确认不等于全平台架构批准或生产可部署。

本轮实际文档检查如下，均在2026-11-06执行：

| 实际检查 | 结果与边界 |
| --- | --- |
| 模型与迁移AST对照及人工复核 | 6张表的字段/类型/空值、主键、唯一、单列/复合外键和CASCADE一致；3个显式索引一致。只解析源码，没有连接数据库或执行迁移 |
| API交叉检查 | 文档操作集合=路由AST集合=原OpenAPI集合；14个path、19个operation，无重复/遗漏；7种请求、5种Read响应的字段已核对 |
| 要求/测试追溯 | 主规格5项要求均有对应行；引用的测试函数、源码符号及固定commit行锚点存在。区分源码与历史运行证据，没有把未覆盖组合计为通过 |
| 文档链接与范围 | 已检查五份文档的相对链接、固定提交源码链接及函数行锚点；ERD、RBAC、API和限制一致；已保留PATCH默认覆盖、无role CHECK、管理角色授权例外及athlete覆盖缺口 |
| `openspec validate formalize-cloud-foundation-baseline --strict --json` | 1/1通过；skip_specs仅有说明性INFO，不存在规格增量 |
| `openspec validate --specs --strict --json` | cloud-identity 1/1通过；主规格原文保持不变 |
| Git差异及原文件字节比较 | 本次仅5份约定文档及本change任务记录有变化；`git diff --check`通过。原`docs/verification.md`、OpenAPI快照及主规格字节不变；无业务源码/迁移/配置/依赖/测试修改 |
| 数据与运行边界 | 本轮未在本机重跑业务测试、启动HTTP、安装依赖、连接数据库或接触旧数据；PostgreSQL/RLS未实施 |

本次源码/链接检查使用一次性只读脚本和人工复核，不新增业务测试或持久测试工具。可直接复查上述源码及链接；OpenSpec/Git命令可在工程根目录重跑。文档发布后的自动CI必须另核对对应head，不能用规划或首版CI替代。

评审状态：草案内容已由用户确认，正式文档已实施并可审阅；本次只完成apply范围内的检查记录，尚未运行独立`openspec-verify-change`工作流。待按当前交付进行verify/评审后，再决定归档；归档、主规格sync和PR合并均未由任务勾选自动执行。项目总体状态继续以Notion任务库为准。

## Apply收口与Notion回链

12项文档任务已经逐项执行并由CLI确认完成；完成的是本change的文档实施，不是总体平台的业务验收。正式文档首次发布于提交`3096ae5`，最终任务收口继续提交同一PR；最新head和自动CI以PR为准。五份文档均已回链到四项既有任务，各次写入返回保存成功、无警告；未重复建立项目任务或填写负责人/截止日期。

| 既有Notion任务 | 本次记录 | 总体状态 |
| --- | --- | --- |
| [OpenSpec基线](https://www.notion.so/410f602574aa813c91bdf17c4ba49ed2) | 基线、规格追溯、正式文档和PR入口 | 待验收；尚未独立verify/归档 |
| [数据模型与历史资产取舍](https://www.notion.so/410f602574aa811bbad3c6e452a065b6) | 六表ERD、真实约束、权威关系及未来实体边界 | 进行中；完整领域/云边权威源/PostgreSQL仍未验收 |
| [租户隔离与RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e) | 当前矩阵、检查链、既有负向证据与覆盖缺口 | 进行中；完整角色组合/平台角色/RLS仍待后续 |
| [架构与接口契约](https://www.notion.so/410f602574aa816582ccc14817ce4601) | 19项API、请求响应、错误/版本及兼容性 | 进行中；Edge/媒体/分析/云边总体架构未冻结 |

下一步先对当前交付执行独立verify/评审，再按授权决定归档与合并；后续PostgreSQL仅有[提案准入说明](../baseline/cloud-foundation.md#后续postgresql验证的提案准入)，尚未创建或实施新change。

## 未验证和覆盖缺口

- RBAC矩阵不是测试覆盖率表；完整逐角色、逐操作、资源归属和授权撤销组合尚未穷举，见[RBAC证据](../contracts/cloud-rbac.md)。
- 场馆PATCH默认覆盖、框架422、ready独立503结构等已从源码确认；并非每个响应/错误分支均有独立HTTP用例。
- role CHECK、唯一owner约束、RLS、所有权转移和并发版本控制尚未实现；文档描述不是数据库验证。
- PostgreSQL方言、时区、事务/锁、连接池租户上下文、生产隔离、安全审计与部署尚未验证。
- Pool/Lane、设备、业务档案、训练/媒体/分析、结果/报告、云边同步、UI及模型服务不在当前实现和本变更验收范围。
