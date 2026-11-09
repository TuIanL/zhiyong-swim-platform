# Proposal

## Why

现有六表只覆盖账号、机构、成员与场馆，EdgeNode、Device、TrainingSession、VideoAsset 的关系及 API 尚无实现。先形成可评审的领域、权限、生命周期和 API 草案，避免未经评审的归属与历史策略固化进迁移。

初稿创建于 2026-11-08，2026-11-09 依负责人指令修订并发布 propose；事实基线为 `main@afb0e5f`。本轮只发布规划；后续文档 apply 另等明确授权，四实体的业务实施另开行为 change。

## What Changes

- 文档 apply 计划创建 `docs/architecture/cloud-capture-media-domain.md`：四实体 ERD、基数、字段及复合约束、不可变归属、采集来源、派生链、状态与历史保留；显式列出凭据和上传会话两个支持概念。
- 计划创建 `docs/contracts/cloud-capture-media.md`：用户侧和设备侧路径、身份/角色/资源范围、请求响应、错误、稳定游标、分片上传与恢复、幂等及短期播放 URL。
- 计划创建 `docs/decisions/0003-capture-media-domain-contracts.md`：对应设计 D1–D10，分别标明来源事实、推荐方案、实际评审结论和后续实施前置，不把本提案写成已批准架构。
- 更新 [cloud-domain-model.md](../../../docs/architecture/cloud-domain-model.md) 的「未实现实体与后续提案边界」表，把四项指向新草案，同时保留「未实现、无表/接口」的事实标注。
- 推荐首版采用：节点/设备 tenant/site 与挂接关系不可原地迁移；派生资产保持同租户/场馆/会话；训练状态只由云端授权用户推进；设备只完成自己发起的上传，不结束整个会话。完整推荐、替代方案与评审问题见[设计](design.md)。
- 校验 ERD、字段、约束、状态、API、错误及 ADR 一致；与[既有领域模型](../../../docs/architecture/cloud-domain-model.md)、[RBAC](../../../docs/contracts/cloud-rbac.md)和[基础 API 契约](../../../docs/contracts/cloud-foundation.md)逐项对照，保留草案与已实现事实的界限。
- 不改变：业务代码、模型、迁移、OpenAPI 快照、测试、依赖、CI、README 的实现状态描述。本 change **不产生任何 DDL**，也不声称 Edge、设备、采集、上传或播放已可用。

## Capabilities

### New Capabilities

无。本 change 只交付文档，不改变产品行为，因此沿用 `skip_specs: true`。未来采集/媒体实施 change 必须在 propose 阶段、写代码之前形成拟实现行为的规格增量；候选能力名届时依据真实范围确定，不将本草案提前同步为主规格。

### Modified Capabilities

无。`cloud-identity` 的注册、会话、机构隔离、场馆授权与 PostgreSQL 验证要求均不变。

## Impact

- 交付物只有文档；运行中的应用、数据库、开发命令与测试集合不受影响。
- 支持概念 EdgeCredential、UploadSession 只用于解释四实体的认证与上传生命周期，不扩展到完整设备PKI、同步或存储产品选型，不产生数据库对象。
- 后续业务实施的前置：对象存储与整对象校验能力、保留/清理期限、凭据策略、离线同步、学员参与关系。文档 apply 可以显式记录这些未决参数与准入门槛，不把它们隐藏在“已冻结”契约中。
- 排除范围：Pool/Lane、学员/教练业务档案、分析任务与结果、报告、云边同步事件、Web 前端、RLS、生产部署。四项实体之外的模型不因本提案被顺带批准。
- 文档标记 `v0.1-draft／未实现／无表无接口`。评审通过只推进明确授权的阶段，不能直接触发业务实施。
- 2026-11-09 重读 Notion：直接推进[数据模型任务](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)与[架构契约任务](https://www.notion.so/410f602574aa816582ccc14817ce4601)，总体状态保持进行中；媒体授权、Edge注册、分片上传和组织模型是后续依赖。设计列出五项来源对照 C1–C5、D1–D10 及任务映射，propose 发布时即回写工程入口和原任务。

## 提案交付与停止边界

- 本次工作分支 `docs/define-cloud-capture-media-contracts`，只发布本 change 规划文件与结构/内容核对证据到 Draft PR；工作流模板和 agent 记忆保留未跟踪。
- 规划完成与文档任务进度分别报告；[任务](tasks.md)全部保持未完成。本轮不是独立 verify，不创建三份正式交付文档、不 apply、不 archive、不 merge。
- 负责人先评审设计推荐，明确 apply 后再按任务交付草案；不同意的取舍先修改规划。PR head、CI 和 Notion 回链由真实发布结果绑定，不复用 PR #2 的证据。

## 本轮propose核对（2026-11-09）

- change strict、主规格strict通过；规划产物done/specs skipped，CLI文档任务0/11。结构校验不代表业务能力已实现。
- 逐项对照五项Notion来源差异C1–C5、十项设计D1–D10与11项文档任务；核对固定归属/硬件重登记、人工与Edge来源、同会话派生、训练控制、分片恢复/确认、凭据与幂等例外、撤权后的URL期限和无四实体删除操作。
- 本change的12处本地相对链接均可达；未来三份正式文档以计划路径列出，未创建空文件。原主规格、业务源码、迁移、契约/OpenAPI、依赖及CI文件没有改动。
- 预存工作流模板、核对记录和agent记忆三份文件哈希一致，不纳入PR。本机未运行不受规划修改影响的业务测试；自动CI与实际head的绑定另在PR和Notion记录。
