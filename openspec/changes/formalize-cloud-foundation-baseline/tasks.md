# Tasks

本清单建立于propose，初始全部未执行；当前apply进度以下方勾选和CLI结果为准。此前 `7082b72` 的代码实现与22项测试属于历史事实，不直接计为本change任务完成。`specs` 已通过 `skip_specs: true` 有意跳过，无主规格同步任务。

## 1. 历史基线与证据登记

- [x] 1.1 发布 `docs/baseline/cloud-foundation.md`，记录事后登记日期、事实基线提交、独立工程边界、历史验证和未验收范围；核对日期/commit与 `design.md`、Git历史一致，且不出现事前审批或生产验收通过的误述。
- [x] 1.2 发布 `docs/verification/cloud-foundation-baseline.md` 的5项主规格追溯表，逐项链接当前代码、测试和原CI记录；核对每条测试名称真实存在、证据对应正确提交，并区分源码证据、历史运行结果及未验证项，保留 `docs/verification.md` 原貌。

## 2. 数据模型与扩展边界

- [x] 2.1 发布 `docs/architecture/cloud-domain-model.md` 中六表ERD与主键、外键、唯一性、索引和级联目录；逐项对照 `models.py` 与 `20261106_0001`，确认复合外键与实际数据库约束一致，不把API角色限制写成DB CHECK/RLS。
- [x] 2.2 在同一文档记录全局账号、机构成员、场馆授权的权威关系及Pool/Lane、Edge、学员档案、训练/媒体/分析等后续实体边界；核对各项均标为已实现、未实现或待提案，不生成新DDL，不默认导入旧库或跨目录依赖旧应用。

## 3. RBAC与负向用例

- [x] 3.1 发布 `docs/contracts/cloud-rbac.md` 的角色—资源—操作矩阵及服务端检查链；逐项对照身份、membership、manager和site_access，确认管理角色的机构级权限、owner保护、401/403/404/409和场馆授权撤销例外均与源码一致。
- [x] 3.2 为该矩阵列出已有负向测试和缺口，明确coach/athlete共享判断不等于两个角色已被穷举测试；用实际测试函数及场景核对覆盖标签，不新增或修改业务测试，也不将未运行/未覆盖组合计为通过。

## 4. API、错误与版本契约

- [x] 4.1 更新 `docs/contracts/cloud-foundation.md`，逐项列出14个path对应的19个HTTP operation（业务17、健康2）、权限、输入schema和成功响应；以生成的OpenAPI及路由源码交叉核对，确保没有遗漏方法、重复操作或越权授予描述。
- [x] 4.2 在接口文档记录当前422框架结构、自定义detail错误、ready的503、v1/0.1.0版本标识、无分页/幂等及场馆PATCH默认覆盖语义；对照schemas/main/api确认这些是当前事实，改进行为仅列为后续提案，不顺手修改代码或OpenAPI。

## 5. 跨文档评审与任务衔接

- [x] 5.1 交叉检查基线、ERD、RBAC、API和追溯表的数据/权限/范围一致性；运行 `openspec validate formalize-cloud-foundation-baseline --strict` 与主规格strict校验，并用Git差异确认仅有本change及约定文档修改、无代码/迁移/运行配置/依赖/测试/主规格变化。
- [ ] 5.2 把正式文档、Git评审入口和本change阶段回链到现有Notion四项任务，保留总体平台未完成范围；逐项读取更新结果，确认未把仅有草案/历史测试的事项写成产品批准或总体任务完成。
- [x] 5.3 形成文档变更的实际验证与评审状态记录，说明本轮运行了哪些检查、引用了哪些历史结果，以及未验证事项；确认未代替负责人批准产品/架构、未在缺少完整证据时声称可归档，且正式文档已可审阅。
- [x] 5.4 记录后续独立PostgreSQL验证提案的准入范围和前置条件：专用实例/身份、六表迁移、约束、时区/事务、租户过滤及RLS策略评审；核对本change未创建该实现提案、连接数据库或实施RLS。

## Workflow follow-up

- 用户已确认规划草案，并明确授权 `/openspec-apply-change formalize-cloud-foundation-baseline`；本清单记录该次实际文档实施，验证与评审状态见 `docs/verification/cloud-foundation-baseline.md`。
- 文档apply及验证后再按流程评审和归档；规格增量已跳过，不执行主规格sync。
- PostgreSQL、完整权限、媒体与其他功能在各自的新change内推进，不在本change归档前顺带实施。
