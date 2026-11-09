Warning: truncated output (original token count: 6095)
Total output lines: 192

# 云端采集与媒体 API 契约草案

> **v0.1-draft／未实现／无表无接口**
>
> 本文是经 2026-11-09 第二轮 Proposal 技术审阅通过的 API 设计方向，不是现有路由、OpenAPI 或业务权限实现。本 Change 只交付文档；MediaBlob、授权记录物理模型、存储适配器和校验服务均未实现。

- OpenSpec Change：`define-cloud-capture-media-contracts`
- 业务事实基线：`main@afb0e5fce4c187c8d3c3d5607d2a675375c2a04d`
- 关联：[领域模型草案](../architecture/cloud-capture-media-domain.md)、[ADR 0003](../decisions/0003-capture-media-domain-contracts.md)、[当前基础 API 契约](cloud-foundation.md)、[当前 RBAC 契约](cloud-rbac.md)。

## 1. 适用边界

当前产品仅实现账号、机构、成员、场馆六表及 14 paths / 19 operations；本文件中的采集/媒体路径均为未来建议，未加入 OpenAPI。既有成功响应、Bearer 身份链和业务错误 envelope 仍以[基础契约](cloud-foundation.md)为准：应用错误建议继续使用 `{"detail":{"code":"...","message":"..."}}`。本草案不改既有 19 个 operation。

所有 P 路径以 `/api/v1/tenants/{tenant_id}/sites/{site_id}` 为前缀。Edge 路径以 `/api/v1/edge` 为前缀并使用节点凭据；Edge token 不能当用户 Bearer 使用。请求/响应模型名与字段是草案方向，具体长度、分片限制、过期时间和校验库须由业务实施 Change 定案。

## 2. 认证、角色与资源授权

### 2.1 请求检查次序

用户请求先验证 Bearer 与活跃账号，再验证 tenant membership / role，再确认 path 中 Tenant/Site 归属一致和 Site 访问权，最后检查 Session/Asset 资源级范围。Edge 请求先验证专用节点凭据、节点 active 与凭据未撤销，再校验节点、Device、Session、上传意图之间的同租户/同场馆归属。客户端提交的 tenant、site、creator、source 身份都不是授权依据。

Owner/Admin 继续拥有本机构管理范围：可管理该机构全部场馆的节点和设备，并访问该机构内的 Session/Asset；不跨机构。其机构级资源权不依赖显式 SiteMembership。Coach 的 Site 访问只是前置条件，不等于该场馆所有训练视频的访问权。

定义三个资源能力：

| 能力 | Coach 判定 | Owner/Admin 判定 |
| --- | --- | --- |
| S-read | 当前机构成员 + 当前 Site 访问 + Session 由自己创建或有效的 Session read grant 覆盖 | 当前机构范围内全部 Session |
| S-manage | Session 创建者且仍有 Site 访问；或本机构 Owner/Admin | 当前机构范围内全部 Session |
| A-read | 当前机构成员 + 当前 Site 访问 + Asset 由自己创建、有效 Asset read grant 覆盖，或对父 Session 有 S-read | 当前机构范围内全部 Asset |

用户创建身份必须由云端认证写入，不能通过请求字段自认所有权。Asset 创建主体和 UploadSession 发起主体是可区分的：管理范围不允许 Owner/Admin 接管别人的上传意图、冒用幂等键或重放结果。

### 2.2 Session 与 Asset 的授权范围

- 一项有效的 Session read grant 适用于指定 Session，并覆盖授权有效期间该 Session 的**所有当前及未来新增 VideoAsset**。Coach 在 Session 子列表读取这些资产时，仍需先通过 S-read；然后每项资产按 A-read 计算。该 grant 不授予 S-manage、上传、修改状态或转授权。
- 单 Asset read grant 只允许读取/播放目标 Asset；它不开放父 Session 详情、Session 子列表中的其他资产或同场馆其他录像。可由该 Asset 的直接详情路径访问。
- Owner/Admin 可向本机构、具有该 Site 访问权的 Coach 授予/撤销资源读取 grant；Coach 不得转授权。授权记录采用什么表或关联结构留待业务实施设计，不是本 Change 的建表决定。
- 撤销一条 grant 后，后续 API 读取和新的播放 URL 签发不再使用该授权路径；若创建者身份、另一项有效 grant 或 Owner/Admin 本机构范围仍合法，访问按剩余路径继续判断。
- 撤销 Session grant 同时停止经该 grant 访问其未来新增资产；显式 Asset grant 等独立路径不被连带撤销。角色、机构成员或 Site 权限失效时，即使 grant 未到期也不再放行 Coach。
- 所有 Session/Asset 列表、详情、Session 子列表、播放签发和游标后续页必须使用同一资源谓词。先授权过滤，再计算返回列表/游标/可见数量；不能以总数或分页差异泄露未授权资源。

### 2.3 播放 URL 与撤权边界

POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/playback-url` 每次签发时重新检查 A-read、Asset ready 和当前成员/场馆授权。建议签名 URL TTL 上限 **5 分钟**，不得把裸 Asset ID 或对象存储 key 当 URL 授权。

撤销 grant、Coach Site 权限或成员身份后，服务端立即拒绝后续详情/播放签发；但已发出的签名 URL 在自身到期前仍可能被持有人使用，不能承诺即时撤回。它是有期限的 bearer capability；外泄 URL 也可能在 TTL 内被复用。若产品要求即时撤权，后续必须评审代理播放或可撤销 token 等新方案，不能把当前短期 URL 描述成即时可撤。

## 3. 端点总表（全部为建议操作）

用户前缀 P 定义见第 1 节；本表中的完整路径均展开书写，以便独立核对操作面。资源不存在、跨机构或调用者不可读取时按不泄露策略返回 404；明确的机构内角色不足返回 403。方法、路径和状态均未进入现有 OpenAPI。

| 方法与路径 | 主体 / 范围 | 请求主要字段 | 成功响应 |
| --- | --- | --- | --- |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes` | Owner/Admin，本机构 Site | query: status 可选 | 200 EdgeNodeRead 数组 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes` | Owner/Admin | EdgeNodeCreate | 201 EdgeNodeRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}` | Owner/Admin | 无 | 200 EdgeNodeRead |
| PATCH `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}` | Owner/Admin | EdgeNodePatch，仅 name/status | 200 EdgeNodeRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials` | Owner/Admin | 无 | 200 CredentialRead 数组，不返回密钥 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials` | Owner/Admin | CredentialCreate | 201 CredentialIssued；secret 只返回一次 |
| DELETE `/api/v1/tenants/{tenant_id}/sites/{site_id}/edge-nodes/{edge_node_id}/credentials/{credential_id}` | Owner/Admin | 无 | 204；仅撤销凭据，不删除节点 |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/devices` | Owner/Admin，本机构 Site | query: edge_node_id/status 可选 | 200 DeviceRead 数组 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/devices` | Owner/Admin | DeviceCreate | 201 DeviceRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/devices/{device_id}` | Owner/Admin | 无 | 200 DeviceRead |
| PATCH `/api/v1/tenants/{tenant_id}/sites/{site_id}/devices/{device_id}` | Owner/Admin | DevicePatch，仅 name/status | 200 DeviceRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions` | S-read 过滤后的调用者 | query: status、limit、cursor | 200 Page[SessionRead] |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions` | Owner/Admin 或有 Site 访问权的 Coach | SessionCreate | 201 SessionRead；created_by 由云端身份填入 |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}` | S-read | 无 | 200 SessionRead |
| PATCH `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}` | S-manage | SessionPatch，仅 title/status | 200 SessionRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/video-assets` | 先 S-read，再按 A-read | query: status、limit、cursor | 200 Page[AssetRead] |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}` | A-read | 无 | 200 AssetRead |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/playback-url` | A-read 且 Asset ready | 无 | 200 PlaybackUrlRead，TTL ≤ 5 分钟 |
| PUT `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/read-grants/{user_id}` | Owner/Admin；目标为同机构且有 Site 访问权的 Coach | GrantPut，可选 expires_at | 204；赋予 S-read 并覆盖 Session 当前/未来资产 |
| DELETE `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/read-grants/{user_id}` | Owner/Admin | 无 | 204；移除这一授权路径 |
| PUT `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/read-grants/{user_id}` | Owner/Admin；目标为同机构且有 Site 访问权的 Coach | GrantPut，可选 expires_at | 204；只赋予目标 Asset 的 A-read |
| DELETE `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/read-grants/{user_id}` | Owner/Admin | 无 | 204；移除这一授权路径 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/upload-sessions` | S-manage 用户；只能以自己为发起人 | UploadIntentCreate | 201 UploadIntentRead + 初始 AssetRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}` | 原发起用户且有 S-manage | 无 | 200 UploadSessionRead + 已确认分片 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/part-urls` | 原发起用户且有 S-manage | PartUrlRequest | 200 PartUrlRead 数组 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/complete` | 原发起用户且有 S-manage | CompleteRequest | 202 completing 或 200 completed + AssetRead |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions…1095 tokens truncated…name, status, config_revision, applied_config_revision, last_seen_at, created_at, updated_at |
| DeviceRead | id, tenant_id, site_id, edge_node_id, name, kind, status, hardware_serial, created_at, updated_at |
| SessionRead | id, tenant_id, site_id, created_by_user_id, title, status, started_at, completed_at, cancelled_at, created_at, updated_at |
| AssetRead | id, tenant_id, site_id, session_id, origin, creator/source IDs, derived_from_asset_id, status, capture_metadata（含与创建请求同名的 device_capture_started_at_raw / device_capture_ended_at_raw）, received_at, media_type, size_bytes, checksum_sha256, created_at, updated_at |
| CredentialRead | id, edge_node_id, issued_at, expires_at, revoked_at；绝不返回 token 明文/hash |
| CredentialIssued | credential: CredentialRead, secret: string；仅创建响应一次返回 |
| UploadSessionRead | id, asset_id, status, expected_size_bytes, expected_sha256, expires_at, confirmed_parts[], completed_at |
| UploadIntentRead | upload_session: UploadSessionRead, asset: AssetRead |
| PartUrlRead | part_number, url, expires_at, required_headers |
| PlaybackUrlRead | asset_id, url, expires_at；URL 是有期限的 bearer capability |
| Page[T] | items[], next_cursor?；不含未授权 total_count |

响应中的服务端时间均为 UTC date-time；设备时间字段保留原始值、基准和不确定性。checksum_sha256 是服务端整对象校验结果，不用于逻辑身份或权限。Asset API 不暴露存储对象 key。

## 5. 分片、恢复、完整性与状态

推荐流程：

1. 原发起用户/节点在目标 Session 创建 UploadSession；云端在同一事务内创建 pending_upload Asset 与 UploadSession，记录发起主体、不可变归属、来源及采集元数据。
2. 原发起主体申请限定对象/分片/动作的短时 part URL 并直接上传；不能对桶或任意对象取得通用写权限。
3. 断线后查询 UploadSession，依据服务端确认的分片列表补传；本地分片回执只作客户端进度提示。
4. 原发起主体提交 complete；云端逐项核对分片、合并对象并验证整对象 bytes、SHA-256 和媒体元数据。校验成功才将 Asset 置 ready。校验进行中可返回 202，后续 GET 查询状态；完成后的重复 complete 返回同一 Asset，不重复创建或合并。
5. 显式 abort、过期、校验失败或 Session 取消使尚未 ready 的 VideoAsset 进入 failed，并将对应 UploadSession 原子终结为 aborted、expired 或 failed；随后拒绝 complete 和新 URL。已签上传 URL 在自身到期前仍可能写入对象，但不能使失败/过期 Asset 变 ready，孤儿对象清理策略另行设计。

UploadSession 建议状态：uploading、completing、completed、failed、aborted、expired。Asset 建议状态：pending_upload、ready、failed。终态映射为 `completed → ready`、`failed/aborted/expired → failed`；Session 已取消时 complete 返回 409 `upload_not_completable`，并将仍未完成的 UploadSession 设为 failed、关联 pending Asset 设为 failed。完成校验结果、UploadSession 终态与 Asset 终态须原子提交；failed/aborted/expired 不能再完成或回到 pending_upload/ready。

Session cancel、complete、abort 与 expiry 竞争必须通过同一事务边界串行化，或通过基于当前状态的条件更新保证只有一个事务提交。取消先获胜时，活动上传和对应 pending Asset 一并失败；complete 先完成整对象校验并提交时，UploadSession.completed 与 Asset.ready 一并提交，之后的 Session cancel 不回退 Asset。事务失败不能只写入其中一侧；重复请求返回唯一已提交结果，状态输家返回当前终态或 409。到期处理须能重试，将过期的 uploading/completing 与 Asset.pending_upload 共同终结，不能遗留无限期 pending_upload。对象存储的实际回收仍属后续设计。

请求字段/枚举值无效（包括无效 Session 状态枚举或空 SessionPatch）返回 422；目标枚举合法、但当前状态机不允许该迁移时返回 409。分片数/大小、URL 有效期、服务端校验 worker、孤儿对象清理期限都是后续实施门槛；不得降低为“所有分片已收到即 ready”。

Session 状态为 planned、recording、completed、cancelled。云端有权主体推进最终业务状态。Cloud cancel 与 upload complete 并发时以云端事务的先后结果为准：cancel 先确认则未完成 UploadSession.failed、对应 Asset.failed，complete 返回 409；完整性确认先提交则 UploadSession.completed、Asset.ready，后续 cancel 不删除既有资产。枚举有效但目标迁移与当前状态冲突用 409；字段缺失、格式无效或枚举值不属于契约用 422。completed Session 可以接收规则允许的补传但不能回退状态。

## 6. 幂等、逻辑 Asset 身份与物理复用

### 6.1 请求幂等

对会创建资源、上传意图或确认完成的可重试写请求发送 `Idempotency-Key`。服务端键域建议包括 tenant/site、已认证主体（user 或 edge_node）、HTTP operation 和目标资源；请求参数摘要必须一致。相同键/相同参数/相同主体并发时仅创建一个逻辑资源并返回同一资源/当前状态；同键异参返回 409 `idempotency_conflict`。重试时仍检查当前身份与授权，缓存不绕过撤权。保留期限与过期键处理留待实施定案。

一次性凭据签发例外：同键重试不重新签发并且不重放明文，返回 409 `credential_secret_not_replayable` 及调用者原本可见的 credential_id；撤销或查询后用新键签发。密钥明文不得写日志、幂等缓存或普通读取响应。

### 6.2 逻辑 VideoAsset 身份

asset_id 标识一次独立的采集、导入或派生记录。只有被证明是同一请求的幂等重试才复用逻辑资源。不同设备的视频、同一设备的不同采集、独立人工导入，即使 SHA-256 相同，也成功创建不同 asset_id，分别保留来源、时间和授权；不按 (tenant,session,checksum) 设逻辑唯一性，不因 hash 相同拒绝创建或返回已有 Asset 代替新采集。离线重传识别“同一次采集”的规则由后续同步协议提供，不通过 hash 推测。

### 6.3 物理文件内容复用

存储层可选复用相同字节，但必须保留每个逻辑 Asset 的独立来源、归属、读取 grant、审计和生命周期。SHA-256用于完整性验证/可选物理比较，不是 Asset 身份或授权凭证。MediaBlob 是否独立建表、复用范围、引用计数/回收协议留待业务实施设计；本 Change 不建该表。清理一个逻辑引用不得删除仍被其他保留 Asset 引用的物理内容。

## 7. 错误目录

错误对象沿用当前业务 envelope；这里的 code 是未来建议，不表示当前服务端已注册：

| HTTP | 建议 code | 场景 |
| --- | --- | --- |
| 401 | unauthorized / edge_unauthorized | 用户身份失效；Edge 凭据缺失/无效/撤销/节点已停用 |
| 403 | forbidden | 已确认机构成员但不具备管理、授权授予或操作权限 |
| 404 | tenant_not_found / site_not_found / training_session_not_found / video_asset_not_found / upload_session_not_found | 非成员、资源跨机构/场馆或调用者无资源读取路径；避免泄露资源存在性 |
| 409 | state_conflict / idempotency_conflict / credential_secret_not_replayable / upload_not_completable | 请求值本身合法，但当前状态机不允许目标迁移或分片/已取消 Session 状态不允许完成；同键异参或一次性密钥重放 |
| 422 | validation_error / immutable_field | 请求字段/组合/枚举无效、未知或不可变字段、SessionPatch 为空或未包含可写字段 |

每个请求只应用与其身份阶段一致的错误：无效身份先于目标资源；目标不在调用者可见范围按 404；可见机构内角色不足按 403；字段或枚举无效按 422；字段及目标状态均合法、但当前状态机不允许该迁移按 409。当前基础 API 的所有实际错误仍见[既有契约](cloud-foundation.md)，本草案不改其检查顺序。

## 8. 离线与历史边界

云端是 TrainingSession 最终业务权威，不要求 Edge 必须在线创建 Session 才能开始采集。Edge 离线可生成临时本地记录并在恢复联网后同步；云端须依后续 Change 定义的授权、归属、身份映射、重复和冲突规则接纳或拒绝。此处不定义同步端点、Outbox/Inbox、ID 映射或冲突策略；临时本地状态不能直接覆盖云端最终状态。

首版不提供四实体 DELETE。Site/Tenant 的未来删除不能级联清掉历史 Session、Asset、来源或仍被保留的共享内容引用；有历史资产/活动引用/未满足保留条件时应停用或归档父级并保留稳定 ID。物理清理、保留期限与审计流程另行设计。ready 不表示本地原件可删。

## 9. 兼容性与实施门槛

- 新端点全部是规划契约；不改变现有 19 操作、现有错误 envelope、数据库或 openapi.json。
- 业务实施前需评审存储产品/区域、完整对象校验与媒体解析、分片限制、幂等保留期限、grant 持久化结构、MediaBlob 物理模型/清理、Site/Tenant 历史保留和离线同步协议。
- 采集时间字段与来源、时区/偏移、相对时间轴映射、设备时钟来源、可空校时偏差/精度和服务器 received_at/created_at 应纳入实现；不能用服务端接收时间代替拍摄时间。
- 角色/授权、跨机构与跨场馆过滤、未来 Session 子资产、播放 URL 到期前撤权限制均须由未来行为 Change 明确规格和测试。本稿不宣称产品行为已实现或经安全/生产验证。

完整设计决策及来源见 [ADR 0003](../decisions/0003-capture-media-domain-contracts.md)；字段、约束与状态见[领域模型草案](../architecture/cloud-capture-media-domain.md)。
