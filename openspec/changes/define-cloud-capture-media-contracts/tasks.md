# Tasks

本清单是后续文档apply任务，propose阶段全部保持未完成。范围只有领域模型草案、API契约草案、ADR及既有文档接线；不含业务代码、DDL、迁移、OpenAPI、运行测试或部署。设计D1–D10尚待负责人评审。

## 0. 评审结论与范围

- [ ] 0.1 收到明确文档apply指令后，按负责人实际评审结果建立D1–D10结论表，标明C1–C5来源、采纳/调整/延后及理由；若不采纳当前推荐，先同步proposal/design/tasks再写交付草案。验收：结论表有实际日期和来源，不把本次propose当作批准；后续存储/保留/编排参数另列实施前置，范围仍为文档。

## 1. 领域模型草案

- [ ] 1.1 创建 `docs/architecture/cloud-capture-media-domain.md`，给出四实体及EdgeCredential/UploadSession支持概念的ERD、基数、可空性、字段/默认值/类型取向、复合唯一键/外键和显式索引建议。验收：按D1/D2/D4/D5，逐条走通不可变tenant/site/挂接、人工来源为空、Edge来源匹配节点、派生同租户/场馆/会话及父引用不变；明确哪些约束由FK、检查约束或应用事务保证，与现有六表命名对照；文首标“v0.1-draft／未实现／无表无接口”。
- [ ] 1.2 在领域文档补四实体及上传会话状态迁移、历史/停用/重登记策略。验收：枚举节点/设备启停、Session planned/recording/completed/cancelled、Asset pending_upload/ready/failed、UploadSession uploading/completing/completed/failed/aborted/expired；给出取消与确认先后、过期/失败重试新ID、硬件搬迁保留旧记录、无四实体DELETE及本地原件不因ready自动删除等场景，状态/非法操作与契约一一对应。

## 2. API契约草案

- [ ] 2.1 创建 `docs/contracts/cloud-capture-media.md`，展开D8全部操作的完整路径、主体/角色/资源范围、请求响应字段和成功状态。验收：路径参数统一，用户与Edge前缀分开；逐端点对照既有RBAC检查链，明确新资源athlete限制；用户不能接管别人的上传、Edge只能续传/确认自己的上传且来源设备匹配，不存在Edge结束Session或四实体DELETE端点。
- [ ] 2.2 在契约文档补D6–D8的错误目录、分片清单/签名/进度恢复/complete/abort、服务端整对象校验及202查询结果、请求幂等与内容去重。验收：匿名/非成员/跨场馆/不同节点/重复完成/同键异参/并发同键/取消与确认竞态各有输入和结果；一次性凭据不缓存或重放明文；不用edge_node_in_use代表不存在的删除操作，不用checksum代替幂等键，不把客户端分片回执当作ready。
- [ ] 2.3 在契约文档写版本和边界：新Session/Asset列表按created_at/id稳定游标，说明nullable started_at、cursor范围、分页建议、短期URL上限与到期前撤权限制；列存储/校验能力、保留清理与幂等期限等后续实施前置。验收：草案推荐、现有已实现事实、未批准参数分列，无四实体已可用或RLS/生产已验收断言；原19个操作和既有错误envelope不被改写。

## 3. ADR与文档接线

- [ ] 3.1 创建 `docs/decisions/0003-capture-media-domain-contracts.md`，逐项承接D1–D10及C1–C5，写明替代方案、取舍、基线afb0e5f、真实评审结论/日期和生效前置。验收：编号和结论与0.1及设计一致，分清“文档方案获评审”和“业务实施获授权”，不伪造创建日即批准日；未选存储产品等事项仍为后续实施门槛。
- [ ] 3.2 仅更新 `docs/architecture/cloud-domain-model.md` 未来实体表中EdgeNode/Device与TrainingSession/VideoAsset两行及相邻说明，指向已创建的草案/ADR并保留“未实现，无表/接口”。验收：相对链接可达，diff不改既有六表字段/约束和历史证据，不把TrainingTask/AnalysisTask或Pool/Lane扩张为本change交付。

## 4. 文档集成交付检查

- [ ] 4.1 对三份文档和既有接线做ERD↔字段↔约束↔状态↔权限↔API↔ADR交叉核对，并保存结果。验收：D1–D10、C1–C5及设计中的关键正负场景逐项有文档位置；尤其核对来源可空与图一致、派生隔离、不可变归属、云端控制Session、上传发起主体、整对象确认、幂等凭据例外；不得用strict替代语义核对或把未运行的业务测试记为通过。
- [ ] 4.2 文档apply交付后运行change strict、主规格strict、相对链接和Git差异检查；检查Notion两项直接任务与本PR的阶段、提交/CI绑定、范围和回链。验收：真实命令/来源结果写入交付记录，proposal/design/tasks done且specs skipped；结构通过与内容核对分列；两项总体任务仍按自身范围，不以该文档子范围完成替代全平台完成。
- [ ] 4.3 核对相对本change基线的全部交付文件（含新增/暂存），只允许本change规划/证据、三份文档及既有领域模型接线。验收：services、configs、scripts、.github、主规格及openapi.json与基线一致；预存docs/workflow与.workbuddy另外列出并保持原样、不纳入PR；发布到同一PR并读取当前head实际CI结果，不将旧PR或旧head结果外推。

## Workflow follow-up

- 本轮只收口propose；规划done/skipped不等于文档apply完成。明确apply前不创建上述三份正式文档，也不勾选任务。
- propose发布即在Notion工程入口及两项直接任务回链change/分支/提交/Draft PR/评审事项，不延迟到apply；未来媒体/Edge/分片任务仅获前置材料，不改变其验收状态。
- 用户评审后明确文档apply，再逐项交付；独立verify、archive及本PR合并分别等待后续授权，不继承PR #2批准。
- 业务实施另开change，先对照三份文档与ADR，在写代码前提出行为规格、迁移和运行验证计划；本change不执行主规格sync。
