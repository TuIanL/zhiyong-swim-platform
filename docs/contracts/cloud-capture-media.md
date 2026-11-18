# 云端采集与媒体 API 契约

> **当前实现基线：19 张业务表、43 paths / 57 operations；M2 元数据与 M3 单对象媒体传输已实施**
>
> M2 的 TrainingSession、VideoAsset、UploadSession 意图与资源读取授权，以及 M3 的分片传输、持久校验作业、ready 状态和短期播放/下载 URL 已按独立 Changes 实施。运行时契约以[OpenAPI 快照](openapi.json)和源码为准。RustFS 仅是隔离 CI profile；生产存储、保留/删除和隐私政策未冻结。MediaBlob、转码、HLS 与云边同步不在范围内。

- OpenSpec Change：`define-cloud-capture-media-contracts`
- 本文包含 M2/M3 实施后的当前 API 契约；运行时以 OpenAPI 快照与源码为准。
- 关联：[领域模型草案](../architecture/cloud-capture-media-domain.md)、[ADR 0003](../decisions/0003-capture-media-domain-contracts.md)、[当前基础 API 契约](cloud-foundation.md)、[当前 RBAC 契约](cloud-rbac.md)。

## 1. 适用边界

当前产品包含初始身份六表、Cloud Edge Registry 四表、M2 五表及 M3 四张媒体传输支持表，共19张业务表；API 为43 paths / 57 operations。基础19项与Registry 12项保持兼容，M2 的16项媒体元数据操作及 M3 的10项传输/访问操作均已实现并进入[OpenAPI 快照](openapi.json)。业务错误采用 `{"detail":{"code":"...","message":"..."}}` envelope；逐操作响应与错误以源码及快照为准。

所有 P 路径以 `/api/v1/tenants/{tenant_id}/sites/{site_id}` 为前缀。Edge 路径以 `/api/v1/edge` 为前缀并使用节点凭据；Edge token 不能当用户 Bearer 使用。请求/响应模型、字段、状态码与错误已由 M2/M3 实施；此处概述便于阅读，精确契约以 OpenAPI 快照为准。

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
- Owner/Admin 可向本机构、具有该 Site 访问权的 Coach 授予/撤销资源读取 grant；Coach 不得转授权。M2 已实现独立 Session 与 Asset grant 记录及授予/撤销主体、时间审计字段。
- 撤销一条 grant 后，后续 API 读取和新的播放 URL 签发不再使用该授权路径；若创建者身份、另一项有效 grant 或 Owner/Admin 本机构范围仍合法，访问按剩余路径继续判断。
- 撤销 Session grant 同时停止经该 grant 访问其未来新增资产；显式 Asset grant 等独立路径不被连带撤销。角色、机构成员或 Site 权限失效时，即使 grant 未到期也不再放行 Coach。
- 所有 Session/Asset 列表、详情、Session 子列表、播放签发和游标后续页必须使用同一资源谓词。先授权过滤，再计算返回列表/游标/可见数量；不能以总数或分页差异泄露未授权资源。

### 2.3 播放 URL 与撤权边界

POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/playback-url` 每次签发时重新检查 A-read、Asset ready 和当前成员/场馆授权。URL 默认有效 **60 秒**、硬上限 **300 秒**，且不得晚于当前身份/授权有效期；不得把裸 Asset ID 或对象存储 key 当 URL 授权。

撤销 grant、Coach Site 权限或成员身份后，服务端立即拒绝后续详情/播放签发；但已发出的签名 URL 在自身到期前仍可能被持有人使用，不能承诺即时撤回。它是有期限的 bearer capability；外泄 URL 也可能在 TTL 内被复用。若产品要求即时撤权，后续必须评审代理播放或可撤销 token 等新方案，不能把当前短期 URL 描述成即时可撤。

## 3. TrainingSession 与媒体端点（M2/M3 已实施）

Cloud Edge Registry 的11个用户管理操作和1个Edge heartbeat已实施，见[当前Registry API契约](cloud-edge-registry.md)。以下列出当前已实现的 Session、Asset、grant、UploadSession 及传输操作。资源不存在、跨机构或调用者不可读取时按不泄露策略返回404；明确的机构内角色不足返回403。

下表共 26 个媒体操作：M2 的16个资源/意图操作与 M3 的10个分片/完成/访问操作。完成请求由持久 worker 异步执行；具体状态码及错误以表格、运行时 OpenAPI 和实现为准。

| 方法与路径 | 主体 / 范围 | 请求主要字段 | 成功响应 |
| --- | --- | --- | --- |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions` | S-read 过滤后的调用者 | query: status、limit、cursor | 200 Page[SessionRead] |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions` | Owner/Admin 或有 Site 访问权的 Coach | SessionCreate | 201 SessionRead；created_by 由云端身份填入 |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}` | S-read | 无 | 200 SessionRead |
| PATCH `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}` | S-manage | SessionPatch，仅 title/status | 200 SessionRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/video-assets` | 先 S-read，再按 A-read | query: status、limit、cursor | 200 Page[AssetRead] |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}` | A-read | 无 | 200 AssetRead |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/playback-url` | A-read 且 Asset ready | 无 | 200 AccessUrlRead；默认60秒、硬上限300秒且不晚于身份/授权期限 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/download-url` | A-read 且 Asset ready | 无 | 200 AccessUrlRead；短期 attachment URL |
| PUT `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/read-grants/{user_id}` | Owner/Admin；目标为同机构且有 Site 访问权的 Coach | GrantPut，可选 expires_at | 204；赋予 S-read 并覆盖 Session 当前/未来资产 |
| DELETE `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/read-grants/{user_id}` | Owner/Admin | 无 | 204；移除这一授权路径 |
| PUT `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/read-grants/{user_id}` | Owner/Admin；目标为同机构且有 Site 访问权的 Coach | GrantPut，可选 expires_at | 204；只赋予目标 Asset 的 A-read |
| DELETE `/api/v1/tenants/{tenant_id}/sites/{site_id}/video-assets/{asset_id}/read-grants/{user_id}` | Owner/Admin | 无 | 204；移除这一授权路径 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/training-sessions/{session_id}/upload-sessions` | S-manage 用户；只能以自己为发起人 | UploadIntentCreate | 201 UploadIntentRead + 初始 AssetRead |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}` | 原发起用户且有 S-manage | 无 | 200 UploadSessionRead + 已确认分片 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/part-urls` | 原发起用户且有 S-manage | PartURLsRequest（每次最多100个） | 202 准备中；准备完成后 200 PartURLRead 数组 |
| PUT `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/parts/{part_number}` | 原发起用户且有 S-manage | PartConfirmation | 200 已由对象存储核实的分片回执 |
| GET `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/parts` | 原发起用户且有 S-manage | query: limit、cursor | 200 已确认分片页；可恢复丢失回执 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/complete` | 原发起用户且有 S-manage | CompleteRequest + Idempotency-Key | 202 工作中；同键 completed/ready 返回200；终态失败409 |
| POST `/api/v1/tenants/{tenant_id}/sites/{site_id}/upload-sessions/{upload_session_id}/abort` | 原发起用户且有 S-manage | 无 | 204 |
| POST `/api/v1/edge/sessions/{session_id}/upload-sessions` | 有效节点凭据；Session 同 tenant/site，Device 属于该节点且 active | EdgeUploadIntentCreate | 201 UploadIntentRead + 初始 AssetRead |
| GET `/api/v1/edge/upload-sessions/{upload_session_id}` | 原发起节点、有效凭据 | 无 | 200 UploadSessionRead + 已确认分片 |
| POST `/api/v1/edge/upload-sessions/{upload_session_id}/part-urls` | 原发起节点、有效凭据 | PartURLsRequest（每次最多100个） | 202 准备中；准备完成后 200 PartURLRead 数组 |
| PUT `/api/v1/edge/upload-sessions/{upload_session_id}/parts/{part_number}` | 原发起节点、有效凭据 | PartConfirmation | 200 已核实分片回执 |
| GET `/api/v1/edge/upload-sessions/{upload_session_id}/parts` | 原发起节点、有效凭据 | query: limit、cursor | 200 已确认分片页 |
| POST `/api/v1/edge/upload-sessions/{upload_session_id}/complete` | 原发起节点、有效凭据 | CompleteRequest + Idempotency-Key | 202 工作中；completed/ready 返回200；终态失败409 |
| POST `/api/v1/edge/upload-sessions/{upload_session_id}/abort` | 原发起节点、有效凭据 | 无 | 204 |

首版不提供 Edge 全局结束 Session 的端点、不提供四实体 DELETE，也不提供 Edge 对其他节点上传的接管/完成/中止操作。Edge 只为自己发起的上传会话续传、查询和确认。

## 4. 请求与响应字段

Session/Asset/Upload 请求模型已由 M2/M3 实施并拒绝未知字段。tenant_id、site_id、created_by、origin、source_edge_node_id、created_at、received_at、status 中由服务端决定的字段不能由调用方覆盖。当前 Edge Registry 的实际请求字段/校验见[Registry API契约](cloud-edge-registry.md)。

| 请求模型 | 字段 | 来源和校验 |
| --- | --- | --- |
| SessionCreate | title? | created_by_user_id/status/时间由云端产生；创建默认 planned |
| SessionPatch | title?, status? | 只有 S-manage；仅修改 title 合法；status 可省略，若提供须为非空有效枚举并满足状态机；至少提供一个可写字段，空 PATCH 返回 422；不接受归属、creator 或历史时间字段 |
| GrantPut | expires_at? | 目标 Coach 必须是本机构成员并具该 Site 访问权；M2 持久记录授予/撤销主体、时间及有效期 |
| UploadIntentCreate | expected_size_bytes, expected_sha256, media_type, capture_metadata | 人工来源；initiator/creator 由登录身份写入；Asset pending_upload |
| EdgeUploadIntentCreate | device_id, expected_size_bytes, expected_sha256, media_type, capture_metadata | origin=edge/source_node 由凭据解析；device 必属该 node/Site；不接受自报另一来源 |
| capture_metadata | device_capture_started_at_raw?, device_capture_ended_at_raw?, device_time_basis, device_timezone?, device_utc_offset_minutes?, video_timebase_kind, video_timebase_metadata?, device_clock_source, device_clock_offset_ms?, device_clock_accuracy_ms? | 与领域模型字段同名；原始设备时间与服务端时间分开；unknown 显式表示；不根据 Site 时区猜设备时区 |
| PartURLsRequest | part_numbers[] | 每次1..100项、编号唯一且在已登记布局内；新传输采用16 MiB分片、最大2 GiB对象；历史大意图可读/重放/中止/过期，但准备返回409 `transfer_policy_conflict` |
| PartConfirmation | etag, size_bytes | 核对对象存储实际分片编号、大小及 ETag；相同确认幂等，不同回执409 |
| CompleteRequest | parts[{part_number,etag}] | 固定升序且完整；逐项与持久确认及对象存储核对；客户端回执不是完整性证明 |

Session 与 Asset 列表按不可变 `(created_at,id)` 降序分页，默认 limit 20、上限 100；planned Session 的 started_at 可空，不作为排序键。游标绑定 tenant/site、筛选条件和版本；每次续页重新检查当前身份、grant 和资源过滤，旧游标不绕过撤权。先过滤可见资源再形成 page 和 next_cursor。节点/设备列表当前不承诺分页。

| 读取模型 | 主要响应字段 |
| --- | --- |
| SessionRead | id, tenant_id, site_id, created_by_user_id, title, status, started_at, completed_at, cancelled_at, created_at, updated_at |
| AssetRead | id, tenant_id, site_id, session_id, origin, creator/source IDs, derived_from_asset_id, status/failure_reason, 服务端 UTC 与设备采集时间字段、received_at, media_type, declared size/checksum, verified_size_bytes/verified_media_type/verified_at, created_at, updated_at |
| UploadSessionRead | id, asset_id, status, initiator_user_id/initiator_edge_node_id, expected_size_bytes/expected_sha256/media_type, expires_at, confirmed_parts[], transfer_status, part_size_bytes/part_count, completed_at/failure_reason, created_at/updated_at |
| UploadIntentRead | upload_session: UploadSessionRead, asset: AssetRead |
| PartURLRead | part_number, url, expires_at, expected_size_bytes, required_headers |
| CompleteRead | UploadSessionRead, AssetRead, poll_url |
| AccessUrlRead | asset_id, url, expires_at |
| PlaybackUrlRead | asset_id, url, expires_at；URL 是有期限的 bearer capability |
| Page[T] | items[], next_cursor?；不含未授权 total_count |

响应中的服务端时间均为 UTC date-time；设备时间字段保留原始值、基准和不确定性。checksum_sha256 是服务端整对象校验结果，不用于逻辑身份或权限。Asset API 不暴露存储对象 key。

## 5. 分片、恢复、完整性与状态

推荐流程：

1. 原发起用户/节点在目标 Session 创建 UploadSession；云端在同一事务内创建 pending_upload Asset 与 UploadSession，记录发起主体、不可变归属、来源及采集元数据。
2. 原发起主体申请限定对象/分片/动作的短时 part URL 并直接上传；不能对桶或任意对象取得通用写权限。
3. 断线后查询 UploadSession，依据服务端确认的分片列表补传；本地分片回执只作客户端进度提示。
4. 原发起主体提交 complete；云端以同事务写入有序 manifest、主体域幂等记录及持久 worker 作业，再由 worker 逐项核对对象存储分片、合并对象并验证完整字节数、整对象 SHA-256 与 ffprobe 的 MP4 容器结果。校验成功才将 Asset 置 ready。工作中为202，后续 GET 查询；同键/同 manifest 在 completing 返回202、在 completed/ready 返回200；失败/过期/中止终态返回409且保留原原因；同键不同 manifest 返回409 `idempotency_conflict`。
5. 显式 abort、过期、校验失败或 Session 取消使尚未 ready 的 VideoAsset 进入 failed，并将对应 UploadSession 原子终结为 aborted、expired 或 failed；随后拒绝 complete 和新 URL。已签上传 URL 在自身到期前仍可能写入对象，但不能使失败/过期 Asset 变 ready。清理先 dry-run，隔离测试可在两次观察、宽限、精确归属与引用核验后删除；ready 资产、本地原件及未知归属对象不会被自动删除。

UploadSession 状态为：uploading、completing、completed、failed、aborted、expired。Asset 状态为：pending_upload、ready、failed。终态映射为 `completed → ready`、`failed/aborted/expired → failed`；Session 已取消时 complete 返回 409 `upload_not_completable`，并将仍未完成的 UploadSession 设为 failed、关联 pending Asset 设为 failed。完成校验结果、UploadSession 终态与 Asset 终态须原子提交；failed/aborted/expired 不能再完成或回到 pending_upload/ready。

Session cancel、complete、abort 与 expiry 竞争使用父级优先事务锁顺序 `Session → UploadSession → Asset → media_objects → media_jobs/parts/cleanup`；外部对象存储 I/O 在数据库事务外执行。取消先获胜时，活动上传和对应 pending Asset 一并失败；complete 先完成整对象校验并提交时，UploadSession.completed 与 Asset.ready 一并提交，之后的 Session cancel 不回退 Asset。事务失败不能只写入其中一侧；重复请求返回唯一已提交结果，状态输家返回当前终态或 409。到期处理须能重试，将过期的 uploading/completing 与 Asset.pending_upload 共同终结，不能遗留无限期 pending_upload。隔离环境的精确版本/分片残留清理已实施；生产保留与删除政策仍待决策。

请求字段/枚举值无效（包括无效 Session 状态枚举或空 SessionPatch）返回 422；目标枚举合法、但当前状态机不允许该迁移时返回 409。新建上传意图的业务上限为2 GiB，分片为16 MiB，每次最多签100个Part URL且最长300秒；下载 URL 默认60秒、硬上限300秒，并且不晚于当前用户身份/授权有效期。上传意图仍沿用 M2 TTL 语义。历史大于2 GiB的合法意图仍可读取、同键重放、中止和过期；物理准备返回409 `transfer_policy_conflict`。验证期间原 User Session 或 Edge Credential 失效时，最终提交不能 ready，必须终结为 `failed/upload_failed`。`completing` 也允许显式中止；终态不被后续过期检查覆盖。

Session 状态为 planned、recording、completed、cancelled。云端有权主体推进最终业务状态。Cloud cancel 与 upload complete 并发时以云端事务的先后结果为准：cancel 先确认则未完成 UploadSession.failed、对应 Asset.failed，complete 返回 409；完整性确认先提交则 UploadSession.completed、Asset.ready，后续 cancel 不删除既有资产。枚举有效但目标迁移与当前状态冲突用 409；字段缺失、格式无效或枚举值不属于契约用 422。completed Session 可以接收规则允许的补传但不能回退状态。

## 6. 幂等、逻辑 Asset 身份与物理复用

### 6.1 请求幂等

对会创建资源或接受 complete 的可重试写请求发送 `Idempotency-Key`。服务端键域包括 tenant/site、已认证主体（user 或 edge_node）、operation 和目标资源；请求参数摘要必须一致。相同键/相同参数/相同主体并发时仅创建一个逻辑资源/工作并返回当前状态；同键异参返回409 `idempotency_conflict`。重试仍检查当前身份与授权；上传意图的历史合法请求先完成身份、资源权限与既有幂等记录检查，再应用新2 GiB策略，避免旧请求被 Pydantic 输入收窄提前拒绝。

一次性凭据签发例外：同键重试不重新签发并且不重放明文，返回 409 `credential_secret_not_replayable` 及调用者原本可见的 credential_id；撤销或查询后用新键签发。密钥明文不得写日志、幂等缓存或普通读取响应。

### 6.2 逻辑 VideoAsset 身份

asset_id 标识一次独立的采集、导入或派生记录。只有被证明是同一请求的幂等重试才复用逻辑资源。不同设备的视频、同一设备的不同采集、独立人工导入，即使 SHA-256 相同，也成功创建不同 asset_id，分别保留来源、时间和授权；不按 (tenant,session,checksum) 设逻辑唯一性，不因 hash 相同拒绝创建或返回已有 Asset 代替新采集。离线重传识别“同一次采集”的规则由后续同步协议提供，不通过 hash 推测。

### 6.3 物理文件内容复用

存储层可选复用相同字节，但必须保留每个逻辑 Asset 的独立来源、归属、读取 grant、审计和生命周期。SHA-256用于完整性验证/可选物理比较，不是 Asset 身份或授权凭证。MediaBlob 是否独立建表、复用范围、引用计数/回收协议留待业务实施设计；本 Change 不建该表。清理一个逻辑引用不得删除仍被其他保留 Asset 引用的物理内容。

## 7. 错误目录

错误对象沿用当前业务 envelope。以下列出本契约涉及的已实现错误；最终以对应路由与[OpenAPI快照](openapi.json)为准：

| HTTP | 建议 code | 场景 |
| --- | --- | --- |
| 401 | unauthorized / edge_unauthorized | 用户身份或 Edge Credential 无效/过期；Edge 与 User 身份不互换 |
| 403 | forbidden | 已确认机构成员但不具备管理、授权授予或操作权限 |
| 404 | tenant_not_found / site_not_found / training_session_not_found / video_asset_not_found / upload_session_not_found | 非成员、资源跨机构/场馆或调用者无资源读取路径；避免泄露资源存在性 |
| 409 | state_conflict / idempotency_conflict / upload_not_completable / part_not_confirmed / part_conflict / transfer_policy_conflict / asset_not_ready | 状态冲突、同键异参、终态上传、缺片/回执不一致、历史意图超出新物理传输策略、Asset尚未ready |
| 422 | validation_error | 请求字段/组合/枚举无效或缺少必要字段；SessionPatch 为空或无可写字段 |
| 503 | storage_unavailable / media_unavailable | 存储暂不可用、配置或对象版本无法满足当前请求；不会退化为公开访问 |

每个请求只应用与其身份阶段一致的错误：无效身份先于目标资源；目标不在调用者可见范围按 404；可见机构内角色不足按 403；字段或枚举无效按 422；字段及目标状态均合法、但当前状态机不允许该迁移按 409。当前基础 API 的所有实际错误仍见[既有契约](cloud-foundation.md)，本草案不改其检查顺序。

## 8. 离线与历史边界

云端是 TrainingSession 最终业务权威，不要求 Edge 必须在线创建 Session 才能开始采集。Edge 离线可生成临时本地记录并在恢复联网后同步；云端须依后续 Change 定义的授权、归属、身份映射、重复和冲突规则接纳或拒绝。此处不定义同步端点、Outbox/Inbox、ID 映射或冲突策略；临时本地状态不能直接覆盖云端最终状态。

首版不提供四实体 DELETE。Site/Tenant 的未来删除不能级联清掉历史 Session、Asset、来源或仍被保留的共享内容引用；有历史资产/活动引用/未满足保留条件时应停用或归档父级并保留稳定 ID。物理清理、保留期限与审计流程另行设计。ready 不表示本地原件可删。

## 9. 兼容性与剩余边界

- M2/M3 不改变现有19个基础操作或12个Registry操作；OpenAPI 现在包含 M2/M3 的26个媒体操作，总计57个 operation。
- M3 的开发/CI 使用固定 RustFS 隔离profile与 boto3 版本。该 profile 的集成证据不构成生产厂商/区域选型或生产就绪结论。
- 生产存储区域、视频隐私与监护人同意、保留/备份/删除政策仍未冻结；不能启用生产媒体存储。MediaBlob、即时撤权代理、HLS、转码、分析/报告与 M4 云边同步仍为后续范围。
- 采集时间字段与来源、时区/偏移、相对时间轴映射、设备时钟来源、可空校时偏差/精度和服务器 received_at/created_at 应纳入实现；不能用服务端接收时间代替拍摄时间。
- M3 已实现的行为需继续由后续独立 Verify 与 CI 证据验收；短期签名 URL 在到期前不能保证即时撤权。生产、隐私政策和完整保留治理不由本 Change 完成。

完整设计决策及来源见 [ADR 0003](../decisions/0003-capture-media-domain-contracts.md)；字段、约束与状态见[领域模型草案](../architecture/cloud-capture-media-domain.md)。
