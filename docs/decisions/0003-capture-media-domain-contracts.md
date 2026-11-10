# ADR 0003：云端采集与媒体领域模型及 API 契约方向

- 状态：**v0.1-draft／未实现／无表无接口**
- 评审：D1–D10 方向已通过 Proposal 技术审阅，仅作为文档设计方向
- 日期：2026-11-09
- OpenSpec Change：define-cloud-capture-media-contracts
- 设计基线：main@afb0e5fce4c187c8d3c3d5607d2a675375c2a04d
- Proposal 评审基线：c07f20e103155aca5de9523be670dae813638cbc
- 来源：[Proposal](../../openspec/changes/archive/2026-11-10-define-cloud-capture-media-contracts/proposal.md)、[Design D1–D10 / C1–C5](../../openspec/changes/archive/2026-11-10-define-cloud-capture-media-contracts/design.md)、负责人 2026-11-09 第二轮 Proposal 技术审阅与文档 Apply 授权。
- 配套：[领域模型草案](../architecture/cloud-capture-media-domain.md)、[API 契约草案](../contracts/cloud-capture-media.md)、[既有云端领域模型](../architecture/cloud-domain-model.md)。

## 1. 决策范围与评审结论

负责人第二轮 Proposal 技术审阅通过，并明确批准当前 D1–D10 设计方向、授权按现有任务执行**文档 Apply**。此结论只批准形成 v0.1 草案的方向，不等于生产架构冻结、业务代码/数据库/API 实施批准、安全/生产验收或总体平台完成。

本 ADR 以已实现的云端身份基线提交 afb0e5f 为事实边界，只记录新增采集/媒体领域的建议。未来实现须另建行为 OpenSpec Change，在代码前提出规格、迁移、权限和测试计划；若实施与本 ADR 不同，应在该 Change 明确说明并重新评审。本文不选择对象存储，不建 MediaBlob/授权表，不定义离线协议，不实施 RLS 或生产部署。

## 2. 来源差异 C1–C5

| 编号 | 来源与核对结果 | 评审后的处理 |
| --- | --- | --- |
| C1 分片上传 | Notion 技术文档 07 §6 与分片上传 P1 描述分片、断点续传、SHA-256 和确认；一次 PUT 不能承接该范围 | 采纳：UploadSession、分片恢复和完整对象校验写入文档契约；仅完整对象验证成功后 Asset 才 ready。存储、分片限制和校验 worker 留实施前置 |
| C2 Session / 任务与离线边界 | Notion 07 实体表列 TrainingSession、AnalysisTask，但未列 TrainingTask；其 API 章节有 /training-tasks。Notion 03 描述训练任务和 Edge 分配 | 采纳：TrainingSession 代表训练业务记录，不把 TrainingTask 与 AnalysisTask 混为一体。云端为 Session 最终业务权威，同时允许 Edge 离线临时记录，恢复联网后按后续同步规则接纳；具体协议另 Change |
| C3 Pool / Lane | Notion 03 及组织模型任务涉及泳池/泳道；当前六表没有这些实体 | 延后：本 Change 只引用 Site，不增加 Pool/Lane 字段、表或 API；另开组织模型设计 |
| C4 路径与角色 | Notion 03/07 是领域路径和未来角色草稿，不是现有四角色授权实现 | 采纳并收窄：Owner/Admin保持本机构管理范围；Coach 的 SiteMembership 只是前置，必须自己创建 Session/Asset 或取得资源显式读取授权；读取不等于管理/上传/转授权 |
| C5 幂等 | Notion 07 §7 对任务创建要求 Idempotency-Key；不能据此宣称所有现有接口已有幂等 | 采纳：只对明确可重试的新建/上传意图/完成请求设计作用域幂等；独立采集的逻辑 Asset 身份和可选物理内容复用分别处理。不同设备/不同采集同 SHA-256 保留独立资产。一次性凭据不重放明文 |

来源原页：[Notion 07](https://www.notion.so/410f602574aa81cda7bff8c3ed483f4d)、[Notion 03](https://www.notion.so/410f602574aa8170b565f7fc4c5eab30)。Notion 页面中标为草稿的内容作为需求来源对照，而非已实现事实。D9 的 Site/Tenant 历史保留边界还直接落实负责人本轮定向审阅要求。

## 3. D1–D10 决策记录

| ID | 评审结果 | 采用方向与理由 | 替代方案及取舍 |
| --- | --- | --- | --- |
| D1 固定归属 | 采纳 | EdgeNode/Device/Session/Asset 的机构、场馆及父记录归属创建后不变。硬件跨馆/跨机构搬迁时重新登记新 ID，旧录像继续引用旧来源，避免改写历史 | 不做原地级联迁移；部署历史表能表达复杂搬迁，但扩张范围，留组织/部署 Change |
| D2 来源链 | 采纳 | Device 必挂 EdgeNode；Edge Asset 来源由可信凭据解析并与 Device 归属匹配；人工 Asset 无设备来源；派生 Asset 保留父来源 | 不合并 Device 与 EdgeNode，避免多机位身份丢失；不允许同馆节点代替其他节点确认上传 |
| D3 用户/Edge 授权 | 采纳 | 用户 Bearer 与 EdgeCredential 分离。Owner/Admin管理和读取本机构资源。Coach 必须有机构成员及 Site 访问，并满足自己创建或资源 grant 的 S-read/A-read；Session grant 覆盖 Session 当前及未来资产；单 Asset grant 不开放 Session/兄弟资产；读取不授予管理、上传或转授权 | 不把场馆授权当视频授权，不用机器人用户 Bearer 替代 Edge 凭据。授权记录物理表结构未决 |
| D4 Session 权威 | 采纳 | 云端是 Session 最终业务权威；仅 S-manage 路径推进云端状态；Edge 离线可以生成本地临时 Session/采集记录，联网后按未来协议同步，不能由临时状态直接覆盖云端终态 | Session 不绑单节点；不在此合并 TrainingTask/AnalysisTask，不增加编排/自动完成机制 |
| D5 Asset 不可变与访问 | 采纳 | Asset 归属/来源不可变；派生父 Asset 同 tenant/site/session 且 ready。访问按 D3 逐次判定；相同字节不共用逻辑资产 ACL | 不覆盖原件，不开放跨 Session 派生/共享；转码/分析生产另 Change |
| D6 完整上传 | 采纳 | 采用 UploadSession 分片、恢复、complete、abort 与服务端整对象校验；校验成功才 ready；202 查询与重试需幂等 | 不以单 PUT 或客户端分片回执替代完整对象完整性；具体存储/worker 未定 |
| D7 三层身份 | 采纳 | 请求幂等键处理同一业务请求重试；asset_id 标识独立采集/import/derive；SHA-256用于完整性和可选物理内容比较。不同设备/不同采集同 hash 仍有独立 ID、来源、时间、ACL | 不按 checksum 合并或拒绝逻辑 Asset；MediaBlob 是否建表、物理引用及回收另交业务实施设计 |
| D8 路径、分页、播放 | 采纳 | 用户/Edge 操作分前缀；S-read/S-manage/A-read落到具体端点。Session/Asset 游标稳定、先资源过滤再分页、续页重查授权。播放 URL 建议最多 5 分钟；撤权阻止新签发，但已签 URL 到期前不能保证失效 | 不给现有 19 个操作增加隐含变化；若需即时 URL 撤权，另评审代理或可撤 token |
| D9 删除与历史 | 采纳 | 四实体没有 DELETE；节点/设备停用、Session 取消。Site/Tenant 有历史媒体、活动引用或保留义务时不得硬删/级联抹历史，先停用/归档并保留稳定 ID。物理清理需无其他保留引用 | 不复制现有六表 CASCADE 作为媒体策略；具体保留期限、导出、清理路径留实施前置 |
| D10 时间与云边边界 | 采纳 | 分开设备采集原始时间、基准/时区或偏移、视频相对时间轴/墙钟锚点、clock source、可空偏差/精度与服务端 received_at/created_at。未知值显式保留。云端最终权威不禁止 Edge 离线临时记录 | 不以入库时间伪装拍摄时间，不默认设备时钟准确；时钟对齐算法与离线协议另 Change |

### 3.1 特别授权语义的具体解释

1. Session read grant 在该 grant 有效期间覆盖该 Session 已有和之后新建的所有子 Asset，包括未来创建的派生 Asset（只要它仍属于同一 Session）。授权失效后不能再依该 grant 读取未来或既有 Asset。
2. 单 Asset grant 只覆盖该 Asset；撤销 Session grant 不会撤销独立 Asset grant，撤销其中任何一条路径也不抹除创建者自身或 Owner/Admin 的其他有效访问权。
3. 权限检查撤销后立即生效于新的 API 读取和 URL 签发。已发出的播放 URL 是短期 bearer URL，持有者仍可能在到期前使用；建议上限 5 分钟，不承诺即时撤销。若更高即时性是需求，需另行设计并评审。
4. 云端可以拒绝把离线临时记录接纳为正式 Session；该拒绝/映射协议不由本 ADR 定义。此边界不要求 Edge 采集时在线，也不允许临时本地状态无条件覆写最终云端状态。

## 4. 实施前置与未决边界

- 对象存储产品/区域、服务端整对象哈希与媒体元数据核验能力。
- 分片大小/数量、签名 URL 上限实施值、幂等键保存期和过期处理。
- Session/Asset grant 的数据库表示；不得由这份 ADR 推导出特定授权表。
- MediaBlob 是否独立建表、不同逻辑 Asset 的物理复用范围、引用安全与垃圾清理；本 Change 不建 MediaBlob 表。
- Site/Tenant 保留/归档/删除与审计流程、共享内容的最终清理规则；本 Change 不新增删除 API/外键。
- Edge 离线本地记录的上传协议、ID 映射、授权重验、重复检测、并发和状态冲突解决。
- 教练—学员关系、池/泳道、训练编排、分析任务/结果、RLS 和生产部署。

## 5. 后果与停止边界

- v0.1 三份正式草案和既有领域模型接线可供后续 Change 使用，但所有条目保持“草案/未实现/无表无接口”。
- 当前实现仍只有原六表与 19 个既有 HTTP 操作；主规格 cloud-identity 不因纯文档 Change 修改。
- 实现授权必须单独取得，随后建立行为规格、数据库/接口实施及权限/并发/上传测试；文档 Apply 不能被解释为业务 Apply。
- 本 ADR 不等于独立 Verify，不归档 OpenSpec Change，不改变 Draft PR 状态，不授权合并。
