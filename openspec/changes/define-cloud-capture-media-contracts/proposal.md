# Proposal

## Why

现有六表只覆盖账号、机构、成员与场馆，EdgeNode、Device、TrainingSession、VideoAsset 的关系及 API 尚无实现。先形成可评审的领域、权限、生命周期和 API 草案，避免未经评审的归属与历史策略固化进迁移。

初稿创建于 2026-11-08，2026-11-09 依负责人指令修订并发布 propose；事实基线为 `main@afb0e5f`。本轮只发布规划；后续文档 apply 另等明确授权，四实体的业务实施另开行为 change。

## What Changes

- 文档 apply 计划创建 `docs/architecture/cloud-capture-media-domain.md`：四实体 ERD、基数、字段及复合约束、不可变归属、采集来源、派生链、状态与历史保留；显式列出凭据和上传会话两个支持概念。
- 计划创建 `docs/contracts/cloud-capture-media.md`：用户侧和设备侧路径、身份/角色/资源范围、请求响应、错误、稳定游标、分片上传与恢复、幂等及短期播放 URL。
- 计划创建 `docs/decisions/0003-capture-media-domain-contracts.md`：对应设计 D1–D10，分别标明来源事实、推荐方案、实际评审结论和后续实施前置，不把本提案写成已批准架构。
- 更新 [cloud-domain-model.md](../../../docs/architecture/cloud-domain-model.md) 的「未实现实体与后续提案边界」表，把四项指向新草案，同时保留「未实现、无表/接口」的事实标注。
- 推荐首版采用：节点/设备 tenant/site 与挂接关系不可原地迁移；派生资产保持同租户/场馆/会话；云端Session最终状态由云端授权路径推进，Edge可保存离线临时记录；当前Edge上传API只完成自己发起的上传，不据此权威结束整个会话。完整推荐、替代方案与评审问题见[设计](design.md)。
- 按负责人本轮定向审阅进一步约束：Owner/Admin保持本机构管理范围；coach在有效场馆权限之上，仅能读取自己创建或资源级显式授权的Session/Asset，读取授权不自动授予Session管理权。API列表、详情、播放与授权撤销使用同一资源过滤语义。
- 分离请求幂等、逻辑VideoAsset身份与物理内容复用：不同设备/不同采集即使SHA-256相同，也保留独立asset_id、来源、采集时间和授权；MediaBlob是否独立建表留后续业务实施设计。
- 云端是Session最终业务权威，允许Edge离线生成临时本地记录并在联网后同步；具体离线协议另行提案。文档字段任务包含采集起止、视频时间基准、设备时钟来源/偏差及服务端接收时间，未知值不伪造成精确UTC。
- 历史资产保留约束覆盖Site/Tenant生命周期，不能经父记录删除级联抹除录像、来源或仍被保留资产引用的内容；具体保留/处置与物理清理设计留待业务实施。
- 校验 ERD、字段、约束、状态、API、错误及 ADR 一致；与[既有领域模型](../../../docs/architecture/cloud-domain-model.md)、[RBAC](../../../docs/contracts/cloud-rbac.md)和[基础 API 契约](../../../docs/contracts/cloud-foundation.md)逐项对照，保留草案与已实现事实的界限。
- 不改变：业务代码、模型、迁移、OpenAPI 快照、测试、依赖、CI、README 的实现状态描述。本 change **不产生任何 DDL**，也不声称 Edge、设备、采集、上传或播放已可用。

## Capabilities

### New Capabilities

无。本 change 只交付文档，不改变产品行为，因此沿用 `skip_specs: true`。未来采集/媒体实施 change 必须在 propose 阶段、写代码之前形成拟实现行为的规格增量；候选能力名届时依据真实范围确定，不将本草案提前同步为主规格。

### Modified Capabilities

无。`cloud-identity` 的注册、会话、机构隔离、场馆授权与 PostgreSQL 验证要求均不变。

## Impact

- 交付物只有文档；运行中的应用、数据库、开发命令与测试集合不受影响。
- 支持概念 EdgeCredential、UploadSession 和资源显式授权只解释认证、上传与访问语义；MediaBlob/授权记录是否独立建表、物理复用与回收由业务实施设计决定，不扩展到完整设备PKI、离线同步或存储产品选型，不产生数据库对象。
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
- 逐项对照五项Notion来源差异C1–C5、十项设计D1–D10与11项文档任务；核对固定归属/硬件重登记、人工与Edge来源、同会话派生、资源级教练读取/管理边界、分片恢复/确认、请求幂等/逻辑资产/物理复用三层、离线临时记录与最终云端权威、采集时间来源及父级删除保留边界。
- 本change的12处本地相对链接均可达；未来三份正式文档以计划路径列出，未创建空文件。原主规格、业务源码、迁移、契约/OpenAPI、依赖及CI文件没有改动。
- 预存工作流模板、核对记录和agent记忆三份文件哈希一致，不纳入PR。本机未运行不受规划修改影响的业务测试；自动CI与实际head的绑定另在PR和Notion记录。

## 本轮定向评审追溯（2026-11-09）

| 负责人要求 | 修订位置 | 文档apply验收任务（仍未执行） |
| --- | --- | --- |
| 教练仅访问自己创建或明确授权的资源，Owner/Admin保持机构管理 | D3、D5、D8、C4；S-read/S-manage/A-read与显式读grant操作 | 1.1、2.1、2.3、4.1 |
| 请求幂等、VideoAsset身份、物理内容复用分离；不同设备同SHA保留独立来源 | D2、D5、D7、C5及来源关系表；MediaBlob设计延后 | 1.1、2.2、4.1 |
| 云端Session最终权威与Edge离线临时记录兼容 | D4、D10、C2；离线协议另Change | 1.1、1.2、2.3、4.1 |
| 采集时间/时间基准/时钟来源；Site/Tenant删除不能抹历史资产 | D9、D10；保留/共享内容回收不由本Change落地 | 1.1、1.2、2.3、3.1、4.1 |
| 规划一致性、strict/链接及PR/Notion同步，保持Propose | 本表、C1–C5、D1–D10及发布证据 | 本轮只检查规划与同步；所有11项实施任务仍未勾选 |
