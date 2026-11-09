# Tasks

本清单跟踪纯文档 Apply：领域模型草案、API契约草案、ADR、既有文档接线和交叉核对记录。负责人已通过第二轮 Proposal 技术审阅并批准 D1–D10 作为文档方向；授权不包括业务代码、DDL、迁移、OpenAPI、主规格、运行测试或部署。

## 0. 评审结论与范围

- [x] 0.1 收到明确文档apply指令后，按负责人实际评审结果建立D1–D10结论表，标明C1–C5来源、采纳/调整/延后及理由；若不采纳当前推荐，先同步proposal/design/tasks再写交付草案。验收：结论表有实际日期和来源，不把本次propose当作批准；后续存储/保留/编排参数另列实施前置，范围仍为文档。

## 1. 领域模型草案

- [x] 1.1 创建 `docs/architecture/cloud-capture-media-domain.md`，给出四实体及EdgeCredential/UploadSession支持概念的ERD、基数、可空性、字段/默认值/类型取向、复合唯一键/外键和显式索引建议，并描述创建主体与资源显式读取授权的语义。视频字段设计必须区分采集开始/结束、设备原始时间及时区/UTC偏移或未知标记、视频相对时间基准与墙钟映射、设备时钟来源（如NTP/PTP/GPS/手动/未知）和可空校时偏差/精度、服务端received_at/created_at；给出字段来源、可空性与验证方式，不用接收时间冒充采集时间。验收：按D1/D2/D3/D4/D5/D7/D10走通不可变归属、人工/Edge来源、同会话派生、不同设备/不同采集同SHA仍保留独立asset_id/来源/时间；不对逻辑资产设checksum唯一；区分云端最终Session与Edge离线临时记录，不在此设计离线协议或建MediaBlob/授权表；文首标“v0.1-draft／未实现／无表无接口”。
- [x] 1.2 在领域文档补四实体及上传会话状态迁移、历史/停用/重登记策略。验收：枚举节点/设备启停、Session planned/recording/completed/cancelled、Asset pending_upload/ready/failed、UploadSession uploading/completing/completed/failed/aborted/expired；给出取消与确认先后、过期/失败重试新ID、硬件搬迁保留旧记录、无四实体DELETE、本地原件不因ready自动删除，以及Site/Tenant存在历史资产或保留引用时不得硬删/级联抹除的边界；离线临时状态可记录并待联网同步，不直接覆盖最终云端状态；状态/非法操作与契约一一对应。

## 2. API契约草案

- [x] 2.1 创建 `docs/contracts/cloud-capture-media.md`，展开D8全部操作的完整路径、主体/角色/资源范围、请求响应字段和成功状态。验收：Owner/Admin保持本机构管理范围；coach的场馆访问只是前置，Session/Asset列表、详情、播放及游标重试须满足自己创建或资源显式授权；Session grant包含会话资产，单Asset grant不解锁其Session或其他资产，读取grant不授予Session修改/上传/转授权；明确授权授予/撤销、角色/场馆权限失效和多条合法访问路径并存的结果；用户不能接管别人上传，Edge只续传/确认自己的上传，不提供Edge权威结束Session或四实体DELETE端点。
- [x] 2.2 在契约文档补D6–D8的错误目录、分片/恢复/complete/abort、服务端整对象校验及202查询结果，分别描述请求幂等、逻辑VideoAsset身份与物理文件内容复用。验收：同键同参复用原逻辑结果、同键异参409、并发同键只创一个资源；不同设备/不同采集即使SHA-256相同也成功保留独立asset_id、来源和权限，不仅因hash相同拒绝或替换为已有asset_id；物理复用不共享授权，MediaBlob是否独立建表留业务实施设计。本组同时枚举匿名/跨机构/跨场馆/不同节点/重复完成/取消竞态与一次性凭据不重放等场景，不用checksum替代请求幂等或采集身份，不把分片回执当ready。
- [x] 2.3 在契约文档写版本和边界：Session/Asset按created_at/id稳定游标，先做D3资源过滤再分页，旧游标不绕过撤权；说明nullable started_at、采集时间与入库排序时间的区别、短期URL上限及到期前撤权限制；写明云端最终Session权威不禁止Edge离线临时记录，具体同步协议另Change；列存储/校验、MediaBlob物理设计、父级删除/历史保留清理和幂等期限等后续实施前置。验收：草案推荐、现有事实、未批准参数分列，无四实体已可用或RLS/生产已验收断言；原19个操作和既有错误envelope不变。

## 3. ADR与文档接线

- [x] 3.1 创建 `docs/decisions/0003-capture-media-domain-contracts.md`，逐项承接D1–D10及C1–C5，写明替代方案、取舍、基线afb0e5f、真实评审结论/日期和生效前置。验收：编号和结论与0.1及设计一致，教练资源读取/管理范围、幂等/逻辑资产/物理复用三层、云端最终权威与离线临时记录、采集时间来源和父级删除保留均有决策位置；分清“文档方案获评审”和“业务实施获授权”，不伪造批准日期；MediaBlob/存储/离线协议仍为后续设计门槛。
- [x] 3.2 仅更新 `docs/architecture/cloud-domain-model.md` 未来实体表中EdgeNode/Device与TrainingSession/VideoAsset两行及相邻说明，指向已创建的草案/ADR并保留“未实现，无表/接口”。验收：相对链接可达，diff不改既有六表字段/约束和历史证据，不把TrainingTask/AnalysisTask或Pool/Lane扩张为本change交付。

## 4. 文档集成交付检查

- [x] 4.1 对三份文档和既有接线做ERD↔字段↔约束↔状态↔权限↔API↔ADR交叉核对，并保存结果。验收：D1–D10、C1–C5及本轮定向审阅要求逐项有文档位置；重点核对同场馆coach互不可见未授权训练、单Asset授权不扩大范围、读取不等于管理、不同设备同SHA保留独立采集、云端权威与离线临时记录兼容、采集时间/时钟来源、Site/Tenant删除不抹历史；同时覆盖派生隔离、上传主体、完整性确认和幂等凭据例外，不用strict替代语义核对或把业务测试记为已运行。
- [ ] 4.2 文档apply交付后运行change strict、主规格strict、相对链接和Git差异检查；检查Notion两项直接任务与本PR的阶段、提交/CI绑定、范围和回链。验收：真实命令/来源结果写入交付记录，proposal/design/tasks done且specs skipped；结构通过与内容核对分列；两项总体任务仍按自身范围，不以该文档子范围完成替代全平台完成。
- [ ] 4.3 核对相对本change基线的全部交付文件（含新增/暂存），只允许本change规划/证据、三份文档及既有领域模型接线。验收：services、configs、scripts、.github、主规格及openapi.json与基线一致；预存docs/workflow与.workbuddy另外列出并保持原样、不纳入PR；发布到同一PR并读取当前head实际CI结果，不将旧PR或旧head结果外推。

## Workflow follow-up（2026-11-09）

- Propose 规划在 c07f20e 发布，最初 Apply 进度为0/11；这是历史阶段记录，不代表当前 Apply 状态。
- propose发布即在Notion工程入口及两项直接任务回链change/分支/提交/Draft PR/评审事项，不延迟到apply；未来媒体/Edge/分片任务仅获前置材料，不改变其验收状态。
- 用户已明确授权按当前 tasks 执行纯文档Apply；实施范围以每项验收条件为准。独立verify、archive及本PR合并分别等待后续授权，不继承PR #2批准。
- 业务实施另开change，先对照三份文档与ADR，在写代码前提出行为规格、迁移和运行验证计划；本change不执行主规格sync。
