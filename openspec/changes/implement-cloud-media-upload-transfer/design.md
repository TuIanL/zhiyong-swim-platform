# Design

## Context

动机与阶段边界见 [Proposal](proposal.md)。基线固定为 main `3352c6b17b2dd3b6921028b25606a999bb69b331`（2026-11-14 实际 fetch）；[PR #5](https://github.com/TuIanL/zhiyong-swim-platform/pull/5) 的服务状态为 merged，head `dbad6a1`、merge `3352c6b`；归档 head 的 [CI 43567828849](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43567828849) 为 success。本轮没有把这些历史结果当成 M3 测试。

### 实查输入及差异

| 输入 | 本次核对结果与处理 |
| --- | --- |
| [五份主规格](../../specs/) | `cloud-training-session` 5、`cloud-media-asset` 8、`cloud-media-authorization` 10、`cloud-edge-registry` 7、`cloud-identity` 10 项；本提案不修改这些文件 |
| Registry身份范围冲突 | `Independent revocable edge credentials` 仍称“只授权所属Node的heartbeat”，与M2已实现的Edge上传意图不一致；本Change新增同名完整MODIFIED增量，明确heartbeat及所属节点上传范围，不改变凭据生命周期或扩大用户权限 |
| [M2 归档](../archive/2026-11-14-implement-cloud-session-asset-foundation/) | proposal/design/tasks/specs/verification/.openspec.yaml 齐全；28/28 是 M2 历史，Verify 的 W1–W4 与 S1 未因合并关闭 |
| [媒体源码](../../../services/cloud/src/swimplatform/media.py) | 意图三对象单事务；cancel 与 create 共用 scoped Session 锁；`_assert_intent_allowed` 在幂等查找前拒绝 cancelled；`_materialize_expiry` 与 abort 仅处理 uploading；`confirmed_parts=[]`；没有 complete、存储或 ready 路径 |
| [授权定义](../../../services/cloud/src/swimplatform/media_access.py) | SQL 谓词用于列表，`can_read_asset/session` 与 `can_manage_session` 用于单资源，外层必须同时执行 `_scope/site_access`；不能只调用不含 Site 检查的内部函数就认为完成授权 |
| [模型](../../../services/cloud/src/swimplatform/models.py)、[0003](../../../services/cloud/src/swimplatform/migrations/versions/20261112_0003_cloud_session_asset.py)、[请求模型](../../../services/cloud/src/swimplatform/schemas.py) | 15 表；ready CHECK 只保证部分字段非空，不证明真实字节；失败词表已含 upload_failed/validation_failed；上传声明 SHA/大小与采集元数据存在；Asset 没有对象引用或独立验证字段 |
| [正式领域模型](../../../docs/architecture/cloud-capture-media-domain.md)、[契约](../../../docs/contracts/cloud-capture-media.md)、[ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) | D1–D10/C1–C5 约束继续适用。部分历史段落仍写“无表/未来”，与 M2 已实现事实冲突；以主规格、迁移、路由和 M2 Verify 为准。原契约 M3 五项为 User/Edge part-urls、User/Edge complete、User playback-url，本次另补 User/Edge 确认与查询、User download-url 五项 |
| [PostgreSQL 并发测试](../../../services/cloud/tests/test_postgresql_media.py) | 已有 `ControlledRace`、两个业务 PID 与第三监控 PID、实际 Lock/wait_event/pg_blocking_pids 证据；复用此强度，不能降为线程到达事件 |
| [配置](../../../services/cloud/src/swimplatform/config.py)、[CI](../../../.github/workflows/ci.yml) | 无 Storage/worker 配置，现有两个数据库 job 不含真实存储；Apply 必须增量补齐，不能以现有 CI 成功声称媒体已验收 |

Notion 的分片任务为「待确认」，验收原文为「上传中断可续传；校验失败不标记 cloud_available；本地原件按策略保留」。`cloud_available` 是产品描述，本实现映射为 **Asset.ready 且存在精确已验证对象**，不额外发明一个可绕过状态机的布尔字段。隐私和首版范围为人工决策输入，部分总体任务摘要仍停留 PR #3 时代；只追加本轮事实，不改它们的属性。

## Goals / Non-Goals

**Goals:** 对同一个 M2 上传意图完成真实分片、恢复、全对象校验、私有持久存储及有权访问；使 SQL 终态和外部存储之间的失败窗口可对账；设计可在两个数据库后端和真实隔离 S3 协议服务上验收。

**Non-Goals:** M4 Outbox/Inbox、批量跨业务同步/冲突裁决；自动凭据续期或 35 天离线恢复；业务删除/保留期限/监护人同意产品；生产部署；HLS/转码/编解码支持承诺、恶意内容检测全平台、分析或报告；MediaBlob/物理去重；Pool/Lane、RLS。媒体探测仅判断允许的容器/媒体元数据，不保证所有浏览器都能解码，也不把拍摄时间从容器推导写回业务字段。

## Decisions

以下 **D22–D31 均为本轮待审阅建议**；继承约束与本次用户明确要求单独注明，不继承历史 Apply 授权。Q1–Q8 是审阅/实施门槛，不是默许的生产决策。

### D22 存储协议及候选比较（G1）

| 选项 | 能力与代价 | 本稿建议 |
| --- | --- | --- |
| 托管 AWS S3 | 原生 multipart/短时签名/HEAD/版本/生命周期；区域、费用、账号及数据边界需负责人决定 | 仅作为 S3 协议参考，不采购、不建桶 |
| 托管阿里云 OSS | 有 multipart/续传、HEAD/签名；原生 API、最小分片和访问端点规则与 S3 不完全相同 | 保留独立 Adapter 可能，不声称一个 S3 Adapter 已支持全部 OSS 行为 |
| 第三方 S3 兼容服务 | 有机会复用适配器；“S3 compatible”不证明所有分页、条件写、版本、错误与签名语义一致 | 每个具体产品/版本必须通过 capability 与集成测试后才能启用 |
| 私有化 Ceph RGW | 官方提供 S3 multipart/对象接口；可控制数据位置，但要自担容量、冗余、TLS、备份/升级和监控 | 私有化候选，也可作为隔离集成服务；本稿不承诺生产部署 |
| 云端本地文件系统 | 简单，但缺少直传 multipart、短签名与真实云对象语义 | 仅测试 double 可用，不作为本次真实存储验收的替代 |

建议首版业务只依赖 `StorageProvider` 协议，具体 SDK 完全封装在 `S3StorageProvider`；可选安装 SDK 的版本/摘要在 Apply 依赖锁中固定，不由路由直接 import。生产 provider、区域、bucket、端点与加密配置仍待 Q1/Q2；测试服务选择不等于生产选型。

| Adapter 操作 | 输入/输出与必要保证 |
| --- | --- |
| capabilities / health | multipart、精确版本或不可变读取、签名、分页、abort/delete/精确 absent 识别；不满足必需能力拒绝启用 |
| create_multipart | 服务端 key、归属元数据、声明类型 → 内部 upload_id；只在保留记录提交后调用 |
| sign_part | 精确对象、upload_id、part number、所需头和期限 → PUT URL；绝不签通用 PutObject/Complete/Delete/List 能力 |
| list_parts / list_multipart | 完整分页迭代器，含编号、真实字节数、opaque ETag；业务层不能只读第一页 |
| complete_multipart | 已冻结的有序回执 → 精确对象版本；解析响应体，处理 HTTP 200 内嵌错误；超时结果是 ambiguous，不是成功 |
| head / open_object | 精确 key+version 或同等不可变句柄；流式读取同一对象；HEAD 的 Content-Type/metadata 仅声明或定位线索 |
| sign_read | 精确已验证版本，GET、Range、inline/attachment 与 expires_at；不返回长期凭据 |
| abort_multipart / delete_exact / inventory | 删除精确句柄/版本，分页扫描本项目命名空间；权限/网络错误与明确 NotFound 分开；确认删除后的 absent 才算成功 |

错误归一为 unavailable、permission_denied、not_found、conflict、ambiguous，保留脱敏 provider request ID；不暴露 SDK 响应、签名 query 或密钥。外部对象位置不能由客户端 URL 传入，避免 verifier/清扫成为 SSRF 或任意删除接口。

研究依据（2026-11-14 查阅官方文档，属于协议事实，不是本项目产品承诺）：

- [S3 分片限制](https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html)：当前编号 1–10000，普通分片下限 5 MiB，末片可更小；列表须处理分页。采用本项目更小上限，不能把 provider 上限当产品承诺。
- [S3 multipart](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)及[Complete API](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html)：按序组装、ETag 清单及响应体错误；合并成功不等于本项目全对象 SHA-256 已验证。
- [S3 presigned URL](https://docs.aws.amazon.com/AmazonS3/latest/userguide/using-presigned-url.html)：是可重用短期 bearer 能力，临时签名凭据可能更早过期；到期前开始的下载可能继续。TTL 不保证强制中断传输。
- [OSS multipart](https://www.alibabacloud.com/help/en/oss/user-guide/multipart-upload)及[分片签名直传](https://www.alibabacloud.com/help/en/oss/user-guide/upload-files-using-presigned-urls)：展示原生接口差异，不照搬其最小分片值。
- [Ceph RGW 对象操作](https://docs.ceph.com/en/latest/radosgw/s3/objectops/)：支持列分片、合并、abort；具体发布版本的签名/版本/条件语义必须实测，不用 latest 文档替代镜像锁定。

### D23 一个 Asset 对应一个独立物理对象（G1、G6）

不建 MediaBlob，不按 SHA 去重；以增加少量存储换取清楚的引用和清理边界。对象 key 由服务端生成，例如 `swim-media/v1/t/{tenant_uuid}/s/{site_uuid}/a/{asset_uuid}/u/{upload_uuid}/o/{object_uuid}`，不使用姓名、邮箱、原文件名或客户端路径。bucket/provider profile 仅来自受控配置。

multipart 合并后的对象始终私有；只有 SQL ready 才可签读 URL。不需要“移动到公开目录”。优先使用版本化对象并把 version ID 固定在验证、最终引用和签名 URL；无版本服务必须证明独占不可变 key、禁止覆盖与精确读取的同等保证，否则拒绝上线。客户端只获 UploadPart，multipart 关闭后不能以旧 part URL 替换完整对象。worker 不复用 key，重试也不能覆盖 ready 内容。

验证前后核对精确身份；断言中不能把 ETag 当 SHA。`media_objects` 保存内部 key/version，不向普通 Asset/Upload 响应暴露；签名 URL 本身可能含 key，因此“不暴露 key”指不提供可绕过授权的裸位置字段，并非能隐藏 URL 的路径。对象元数据包含项目 namespace/tenant/site/asset/upload/object 标记，只由控制面写入，它是对账线索而非单独授权依据。

### D24 数据模型、19 表与迁移设计

新表公共字段：UUID 为 `String(36)`，服务端时间为带时区 UTC，字节数 BigInteger，摘要为64位小写 hex，状态短枚举；全部 FK 用 RESTRICT，均有 tenant/site 范围与创建/更新时间。不改变原 Asset/source/capture IDs。

| 新表 | 字段/可空性 | 键、约束与索引 |
| --- | --- | --- |
| `media_objects` | id；tenant_id/site_id/session_id/asset_id/upload_session_id 全非空；provider_profile/bucket/object_key 非空；provider_upload_id/object_version 可空；phase=`reserved/preparing/uploading/assembled/verified/delete_pending/deleted`；generation>=1；observed_size_bytes/observed_sha256/observed_media_type/verified_at 可空；last_signed_write_expires_at、assembled_at、deleted_at 可空 | upload_session_id 唯一；(tenant,site,session,asset,upload) FK→upload_sessions 同五列新增 UNIQUE；(tenant,site,session,asset,id) UNIQUE 供 Asset 反向引用；(profile,bucket,key) UNIQUE，不按 hash 唯一；phase=verified 要求观测值/验证时间齐全，deleted 要求 deleted_at；按 phase/updated_at 索引 |
| `upload_parts` | id；tenant/site/session/asset/upload 非空；part_number、expected_size_bytes 非空；state=`registered/confirmed/stale`；etag/actual_size_bytes/confirmed_at 成组可空；request_hash 可空 | (upload_id,part_number) UNIQUE；scope FK→upload_sessions 同五列；part_number 1–10000，期望/实际大小正数；确认三字段全有或全空；首次 confirmed_at 不可重写；stale保留原审计而不再作为完成证据 |
| `media_jobs` | id；tenant/site/session/asset/object_id 非空；kind=`initialize/complete/cleanup`；state=`queued/running/retry_wait/succeeded/failed`；attempts>=0、generation>=1；lease_token/lease_until 成组可空，next_attempt_at，last_error_code；accepted_actor_kind/user_id/edge_node_id 及 accepted_auth_session_id/credential_id（完成作业适用，只有 ID，无 token）；created_at/updated_at | 同 scope object FK→media_objects；(object_id,kind) UNIQUE；完成工作主体恰一；state=running 必有租约对；索引(state,next_attempt_at,lease_until)；租约代际条件提交，非进程锁 |
| `media_cleanup_candidates` | id；tenant/site 非空；object_id 可空（存在则同 scope FK）；profile/bucket/key 非空；upload_id/version、内部发现线索可空；kind=`multipart/object`；first_seen_at、last_seen_at、not_before、state、attempts、next_attempt_at、lease/generation、last_error_code、deleted_at | scope FK→sites；精确候选 identity_hash UNIQUE（对 profile/bucket/key/kind/upload_id/version 的规范序列做摘要，保存原句柄复核，NULL 不靠普通 UNIQUE 去重）；按 state/not_before/next_attempt_at 索引；孤儿无 object FK 不代表无引用可直接删除 |

图中 mandatory 关系与上述非空列一致：

```text
TrainingSession 1 --> N VideoAsset 1 --> 0..1 UploadSession
UploadSession   1 --> 0..1 media_objects 1 --> N media_jobs
UploadSession   1 --> N upload_parts
VideoAsset      1 --> 0..1 verified storage_object_ref
Site            1 --> N media_cleanup_candidates --> 0..1 media_objects
```

既有列的增量：

- UploadSession 加 `UNIQUE(tenant_id,site_id,session_id,asset_id,id)`、可空 `part_size_bytes/part_count`（成对设置后不可变）、`complete_manifest_hash/complete_requested_at`（成对可空）；completing/completed 必有清单，旧 M2 行保持空直到准备/complete，不重新计算 expires_at。
- Asset 加可空 `storage_object_ref`（media_objects.id）与 `verified_size_bytes/verified_media_type/verified_at`，复合 FK `(tenant,site,session,id,storage_object_ref)` → media_objects `(tenant,site,session,asset,id)`；ready CHECK 扩展为这些字段、checksum、received_at 均存在，且旧 `size_bytes/media_type` 在 ready 时等于 verified 对应值。pending/failed 的 verified 字段、checksum、正式引用为空；内部失败观察值只保存在 media_objects。M2 `size_bytes/media_type` 在验证前继续表示声明，不改变旧字段含义；UploadSession 永久保留声明值。
- `received_at` 是服务端首次确认完整物理对象已经存在的时间，不是校验结束或采集时间；在最终事务中复制已保存 assembled_at，`verified_at` 另存。失败不伪造 received_at，首次值不被重试覆盖。
- `idempotency_records.operation` 增加 `upload.complete`，resource_kind 继续为 upload_session，复用现有主体配对、部分唯一索引、key/request 摘要；不保存完整请求体、URL、凭据。无 TTL 淘汰以沿用持久 replay；幂等元数据留存不是视频无限保留政策。
- media_jobs 的 accepted主体/认证ID由认证上下文写入，分别RESTRICT引用users/edge_nodes/auth_sessions/edge_credentials；User工作要求user与auth_session配对，Edge工作要求node与credential配对并核对同scope，非完成工作不伪造这些字段。租约/候选均保存累计attempts与安全错误，不覆盖首次观察/首次确认审计。
- 交叉表 completed/ready 配对需要同事务应用服务与真实失败注入证明，单表 CHECK/非空不能证明整对象字节或全部跨表状态。

### D25 身份、授权矩阵及 M2 WARNING 收口

令 P=`/api/v1/tenants/{tenant_id}/sites/{site_id}`，E=`/api/v1/edge`。

| 操作 | User | Edge | 拒绝/限制 |
| --- | --- | --- | --- |
| 意图创建/replay | 当前 `_scope` + S-read/S-manage；新建由自己发起 | 有效节点凭据，同 scope Session；新建 Device active 且属原节点 | User/Edge token 互用401；资源不可见404，已可见但无管理403 |
| part URL / PUT确认 / GET分片 / complete | 当前 `_scope` + S-manage + 原 initiator_user_id | 当前有效凭据 + 原 initiator_edge_node_id；新写/确认/complete 要求来源 Device active | Owner/Admin 也不能接管他人上传；错误为404 upload_session_not_found；read grant 不授写 |
| 播放/下载 URL | 当前 `_scope` + `can_read_asset`（M2 的 A-read）+ ready | 不提供 | Asset-only grant 可直接签对应 Asset，但仍不能读父 Session/兄弟；Athlete 无新入口 |
| 后台作业/清扫 | 内部 worker，不是用户/API token | 不作为 Edge 端点 | 只处理持久授权工作和受控 scope，不创建全局用户或复制 ACL |

**W1**：用户先做身份和能力预检，再锁父 Session，重查当前权限 → 找既有主体/operation/目标/key → 摘要不符409 → 同参 replay 当前原 pair（201）→ 只有无记录才检查 cancelled、新意图大小与 active Device。Edge 同顺序；历史 replay 仍需有效 Edge 凭据和原来源归属，但不因 Device 后来停用重写历史。可在 replay 中按共同协议物化真实过期，不延期。任何 replay 都不签 URL、不重新排完成作业。

**W2**：两次不同键、两个 Device、相同 SHA/大小，创建及验证后仍有两个 asset/upload/object ID、不同来源与采集时间；User 独立导入也不合并。内容去重延后。

**W3**：Session 与 Asset 两类 grant，Owner@T1 PUT、Admin@T2 PUT，读取持久字段证明首次 granted_at/by 不变；Owner@T3 DELETE、Admin@T4 DELETE，证明 revoked_at/by 不变。用可控时钟与两个管理员，不只断言 HTTP 204。

**W4**：utc、offset、iana_timezone（有效 ZoneInfo）分别经真实意图 API + Asset GET 正向往返，核对 UTC 瞬间、原始文本、偏移/时区/时钟来源及 unknown 负向；不能把服务端 received_at 当采集时间。上述测试两后端共享运行。M2 Verify S1 依赖/SQLite datetime 弃用为后续维护建议，不宣称本轮关闭。

### D26 API、分片协议与错误语义（G2、G3、G5）

新增 **10 paths / 10 operations**，预计总计43 paths / 57 operations；其中原 M3 五项有明确覆盖，不扩展 Edge 媒体读取。API版本与既有 envelope 保持不变，OpenAPI 只在 Apply 更新。

| 方法/完整路径（P/E 为上文完整前缀） | 请求/身份 | 成功与状态 |
| --- | --- | --- |
| POST P/upload-sessions/{upload_session_id}/part-urls | User，`{part_numbers:[int]}`，1..签名批上限，不重复 | 准备中202 PreparationRead；就绪200 `{items:[PartUrlRead]}` |
| POST E/upload-sessions/{upload_session_id}/part-urls | Edge，同上 | 同上 |
| PUT P/upload-sessions/{upload_session_id}/parts/{part_number} | User，`{etag,size_bytes}` | 200 ConfirmedPart；相同确认重放保持首次时间 |
| PUT E/upload-sessions/{upload_session_id}/parts/{part_number} | Edge，同上 | 同上 |
| GET P/upload-sessions/{upload_session_id}/parts | User，`limit/cursor` | 200 Page[ConfirmedPart]，与 provider 完整分页对账 |
| GET E/upload-sessions/{upload_session_id}/parts | Edge，同上 | 同上 |
| POST P/upload-sessions/{upload_session_id}/complete | User，Idempotency-Key，`{parts:[{part_number,etag}]}` | 202 CompleteRead 或200已完成 CompleteRead |
| POST E/upload-sessions/{upload_session_id}/complete | Edge，同上 | 同上 |
| POST P/video-assets/{asset_id}/playback-url | User A-read，空对象；不能自报 key/TTL | 200 AccessUrlRead，inline、Range |
| POST P/video-assets/{asset_id}/download-url | User A-read，空对象 | 200 AccessUrlRead，attachment、安全服务端文件名 |

字段形状：

- PartUrlRead：`part_number/url/expires_at/required_headers/expected_size_bytes`。URL 只能授权这条 multipart 的 UploadPart，必须包含实际需要签名的头。浏览器不能可靠强制 Content-Length 的 provider，应由分片确认、配额与 complete 的实际大小核对兜底；不能虚称仅靠 URL 可强制任意字节上限。
- PreparationRead：`upload_session_id/asset_id/transfer_status=preparing/poll_url/retry_after_seconds`；响应同时有 Location 与 Retry-After。准备重试语义以同 upload 绑定实现，不承诺重发同一 URL 字符串。
- ConfirmedPart：`part_number/size_bytes/etag/confirmed_at`。ETag 是 opaque 回执（长度有界、保留 provider 返回的语义），不解释为 MD5/SHA。PUT 自然键为 upload+part，规范化相同 body 自然幂等，不另消耗全局幂等键。
- 分片布局在首次 part-urls 被接受时生成并登记所有 part_number/expected_size，SDK 初始化由持久 initialize 工作执行；并行上传、乱序到达允许，complete 清单必须1..N升序且无空洞。重复签名只是刷新短期能力，不新增记录或延长意图。
- GET parts 按编号分页（默认100，上限1000），cursor 绑定 tenant/site/upload/generation/编号；遍历 provider 内部分页，不把内部 continuation token 暴露为授权。provider 缺失或回执改变将原确认标记stale并返回409 part_conflict，保留首次回执/时间，不覆盖为新确认；可重传原字节恢复原回执，否则须中止后新意图。GET发现已传但未登记回执可在核对大小后补首次确认。快照后必须再核对 generation/status，不能把 I/O 前状态写回。终态查询返回已保存的确认历史，不复活 multipart。
- 既有 GET UploadSession 保留原字段并增量返回 `transfer_status/part_size_bytes/part_count`，`confirmed_parts` 为最后核对的确认列表（有界，非完整性证明）；客户端大列表以 GET parts 为准。metadata GET 不因存储暂时不可用而误改失败终态。
- CompleteRead：`upload_session/asset` 与 `poll_url`。202=已持久接受但未完成；200=SQL已原子completed/ready；poll继续使用既有GET UploadSession及Asset详情。accepted manifest/hash持久固定；合法结构但未确认409，结构、顺序、编号非法422。相同key异body409优先于新状态判断；同清单不同key可回同结果但不能再合并，另一清单409 upload_not_completable。
- 进入completing后布局及首次确认的ETag/size集合冻结，不允许新增/改写分片确认；worker从冻结行重建清单并核对complete_manifest_hash。GET parts此时可读/报告provider变化，但不能把新回执覆盖为accepted manifest；终态后仍只读确认历史。
- AssetRead 增加 `verified_size_bytes/verified_media_type/verified_at`；不增加客户端可写的 source/capture/storage/status 字段。
- AccessUrlRead：`asset_id/url/expires_at/required_headers`，不返回独立对象 key；签发响应 `Cache-Control: private, no-store`、`Referrer-Policy: no-referrer`。播放/下载不做幂等缓存，每次都重新判权并可生成新短 URL。

请求一律 `extra=forbid`。公共错误仍用 `detail.code/message`：身份401；作用域/不可见404；已有可见性却无所需能力403；未知字段/非法布局/枚举/新意图超上限422；状态/幂等/证据冲突409；存储暂时错误503+Retry-After。新增 `transfer_policy_conflict`、`part_conflict`、`part_not_confirmed`、`upload_not_completable`、`asset_not_ready`、`storage_unavailable`、`media_unavailable`。不把 provider 404直接透传成业务资源不存在；在已授权上下文区分 provider 缺失与权限错误。失败原因仍用 M2 封闭词表，内部 error_code 可细分 `size_mismatch/hash_mismatch/type_mismatch/source_disabled/authorization_lost/retries_exhausted`，不改历史公开原因。

### D27 Complete、验证与持久工作（G3）

```text
intent(uploading,pending_upload)
  --> prepare + part transfer + confirmation
  --> accept complete [SQL: completing + manifest + job + idempotency]
  --> assemble exact private object [external I/O]
  --> read ALL bytes + SHA256 + media probe [external I/O]
  --> finalize [SQL: completed + ready + verified reference]
       or terminal failure/abort/expiry/cancel + cleanup registration
```

1. API 预检当前主体/权限与对象 scope。complete 在短事务按 D28 锁顺序重查状态/期限/清单；同参记录优先重放，首次接受把 completing、不可变清单摘要、complete job 与幂等记录一次提交，之后才允许 worker 外部合并；不持数据库连接/行锁等待下载或哈希。
2. Worker 是独立受监督进程/CLI，不用 FastAPI BackgroundTasks 当持久队列。领取 job 使用数据库租约与单调 generation；PG 可用 SKIP LOCKED，SQLite 条件 UPDATE，领取事务短且可回滚。外部 I/O 使用有界连接/读超时和有限重试，所有提交带 lease/generation CAS；续租不改变业务 expires_at。
3. 组装前重新分页核对所有已登记 part 的最新 provider 编号、大小、回执和清单；既有 URL 可能重写分片，SQL确认不是冻结 provider 内容。用冻结回执完成合并，处理内嵌错误；NoSuchUpload 不证明成功，须 HEAD exact key+project metadata+version，再走全对象读取。尚无对象时按 ambiguous 重试/对账，不启动新逻辑上传。
4. 对合并对象记录首次 assembled_at 与 version；逐字节流式累计 size 与 SHA-256。独立 verifier 将同一对象流落到受限临时文件并调用固定版本媒体探测器（候选 ffprobe），不允许网络协议、任意路径、shell拼接或无限CPU/内存/输出；设置文件大小、时间、磁盘空间与进程资源预算。HEAD的Content-Type、后缀、ETag和分片checksum都不是真实类型/整文件hash证据。允许类型和探测器部署门槛见Q4，不能边实施边接受任意类型。
5. size 必须等于 expected_size_bytes，SHA 必须等于 expected_sha256。媒体类型由探测结果规范化：声明空/`application/octet-stream` 可由真实允许类型补全；具体类型声明须与探测类型匹配，否则 validation_failed。文件容器允许不等于浏览器编解码保证；不做转码。验证原始值存 media_objects，Asset 的已验证字段只在最终事务写入。
6. 最终短事务重新锁定 Session/Upload/Asset/Object/Job，重取 server now、未取消、未过期、completing、代际/租约与精确对象身份、不在delete_pending，核对当前发起用户的成员/Site/S-manage和接受complete的用户会话仍有效，或节点active/Device active及接受 complete 的凭据未撤销/过期。失权以 upload_failed 配对收口并清理（方案选择，列入Q4审阅）；不保存明文身份。成功一次写 completed_at、Asset.ready/实际值/received_at/verified_at/引用、Object.verified、Job.succeeded。
7. 暂时 I/O/DB错误保留 completing 与可重试 job；业务期限到达优先 expired，不因重试延长。确定校验失败 `validation_failed`；准备/传输重试耗尽或失权 `upload_failed`。终态配对与清理登记同事务。数据库提交失败可对同一已组装对象重新验证后CAS；旧worker结果作废，不能直接删其曾经处理但已被新代际接管的对象。

“物理请求恰好一次”无法跨 SQL/provider 保证，承诺的是业务逻辑记录唯一、终态一次、精确对账和可重试清理。初始化响应丢失可能留下同 key 多个 MPU，须 list_multipart 找到并清理未被当前绑定选中的句柄；记录先提交再执行外部初始化，避免全部外部副作用没有业务落点。

### D28 状态机、事务与并发（G4）

统一短事务锁顺序：**scoped Session → UploadSession（按id排序）→ Asset（按id排序）→ media_objects → media_jobs/parts/candidate**。GET 如需物化过期也遵守同序；普通无副作用读取不额外锁。预检无权主体后才锁，锁后 refresh 当前身份/资源/状态/now，不能复用 I/O 前 ORM 快照。PG行锁，SQLite条件写锁；不引入进程内互斥。Job领取先提交租约，后续不得持job锁反向等待Session。

| 起点/事件 | 终点与响应 |
| --- | --- |
| uploading + 合规complete | completing / Asset pending；202 |
| completing + 验证最终提交成功 | completed / ready；重复complete200 |
| uploading或completing + abort先赢 | aborted / failed(upload_aborted)，重复abort204不改历史 |
| uploading或completing + now>=expires_at | expired / failed(upload_expired)，不延期 |
| uploading或completing + Session cancel先赢 | failed / failed(session_cancelled)，cancel200；complete409 |
| 校验确定失败 | failed / failed(validation_failed) |
| 准备/传输失败耗尽或权限丢失 | failed / failed(upload_failed) |
| 任一失败终态 + complete | 409 upload_not_completable；同键意图replay201当前终态，不重启 |
| completed/ready + abort、expiry、later Session cancel | 保留首次completed/ready与对象；abort204、重复complete200；不回退 |

cancel 仍一次事务收口所有 uploading/completing 与对应pending资产，并登记所需清理，保持原因第一次胜出；completed Session 的合规补传保持不变。cancel 输赢以**验证最终事务提交**为准，不以complete的202或SDK合并为准。到期恰好边界 `now>=expires_at`，completing不豁免24小时/7天上传期限。

PostgreSQL验收必须覆盖每对两种顺序：Cancel vs finalize、Abort vs finalize、Expiry vs finalize；以及同键/不同键同清单complete、重复确认、租约过期旧worker、GC vs finalize。每例至少两个不同业务backend，第三监控连接确认实际Lock/wait_event/blocker后才放行；CAS类竞争另记录代际和成功行数。存储故障点独立注入，不靠真实sleep竞速。校验I/O期间另一事务能取消/到期，证明没有长时间持SQL锁；限定statement/lock timeout，禁止把连接池不足当并发证据。

### D29 播放、下载与撤权（G5）

从直接Asset路径执行现有 `_scope` + A-read，不要求Asset-only grantee取得父Session读取权。Owner/Admin本Tenant、Coach当前角色/成员/Site+创建者或grant路径，Athlete仍拒绝，Edge没有签读端点。ready后精确HEAD对象版本可用才签发；不存在/无法确认503 media_unavailable，不悄悄改为另一个版本或永久公开URL。

签名TTL为 `min(配置TTL,300秒,当前用户会话剩余期,本次成立授权路径剩余期,provider签名凭据剩余期)`，必须>0。多个路径可选仍成立的一条，不能因某一grant撤销抹掉Owner/Admin或其他grant。签发前最后一次当前授权核验；不在权限判断和签名间做长I/O后继续用旧快照。签名/审计只存actor、asset、动作、结果、TTL/到期时间、request ID，不存完整URL或query。

下载文件名由asset UUID与已确认类型生成并安全编码，不能采纳客户端Content-Disposition；播放inline、支持Range与合法206/416、CORS只列批准origin/方法/头，不开放写桶和公开ACL。撤权阻止后续签发，已发URL在到期前可能复用；到期前已经开始的传输可能继续，TTL不承诺数据回收或即时中断。需要即时撤权代理、HLS和转码时另评审，不在本Change引入第二套资源ACL。

### D30 可重试清扫与孤儿回收（G6）

过期扫描按固定批次查 `expires_at<=now` 的 uploading/completing，按D28锁重查，原子终结上传/资产并排cleanup，不依赖有人GET。cancel/abort/validation_failed/重试耗尽共用登记，清理失败不复活业务终态。清扫运行于显式内部CLI/受监督定时进程，不在API启动时迁移或全桶删除。

清理分两类：

1. **已绑定失败残留**：锁定scope和物理记录，确认上传终态、没有完成工作租约、没有任意有效Asset引用（按精确profile/bucket/key/version查全体引用，不能只看当前Asset或缓存计数），标记delete_pending并递增generation，记录not_before。释放事务后abort精确MPU、delete精确对象版本；再HEAD/list核对不存在，记录deleted。任何权限/网络/不确定结果重试且CLI非零，不能当作absent。
2. **孤儿句柄**：只扫描本项目私有namespace与已批准profile，分页发现没有当前选中绑定的MPU/对象，持久候选、first_seen/last_seen和可信元数据。至少两次观察且过宽限后重查SQL所有引用、活动上传/作业/最新写签名窗口；范围或元数据不符转人工，不删未知tenant/site。删除候选期间不能被另一个publisher接管：同一对象UUID先创建/锁定排他tombstone或锁定现有media_object，发布者必核对候选及generation，阻止“核验无引用后又被引用”。不靠一次清单快照。

清理作业重试耗尽后保留failed/候选与告警，内部CLI可按精确job/candidate ID显式redrive（重新租约、累计attempts不归零、记录执行审计）；每次仍执行完整引用与代际核验，不提供任意key删除入口。

`not_before` 至少晚于已持久 `last_signed_write_expires_at + 迟到I/O宽限`；签名必须先提交该上界后返回客户端。abort响应不等于迟到part已全部消失，之后还须分页list核对；SDK超时产生的迟到对象由后续扫描反复对账。候选worker晚返回不得删除获胜代际引用；无法确认目标安全则告警并保留候选。

本功能只清技术残留。**ready内容不参与按年龄自动删除**，隐私保留/备份/法律保留/业务删除由负责人另决；也不把“未决定保留天数”解释为允许无限期生产保存。生产媒体启用被Q2门禁阻止，开发集成仅用合成媒体。ready不是删除Edge原件的指令，M3不提供远程删本地文件能力。Provider生命周期规则只能在批准后作为兜底，且不得比业务传输期限/宽限更早删除活动MPU。

### D31 配置、部署与双后端交付

新增配置一律 `SWIM_CLOUD_MEDIA_*`/Secret引用，禁止借用父目录.env或PG业务库/真实桶。启用开关默认关闭；关闭时新传输/签名503，M2元数据及终态读取保持可用；旧意图expires_at不因打开开关而重置。生产缺少明确profile、region、私有ACL/版本能力、授权与保留决策记录即拒绝启用，不能fallback本地静态目录。

候选开发profile（**全部待负责人审阅，不是生产冻结值**）：

| 参数 | 候选值/硬约束 | 依赖与验收 |
| --- | --- | --- |
| UploadSession TTL | 已确认默认24h、最长7d，服务端配置 | 原M2语义不变，completing也不延期 |
| EdgeCredential | 已确认7d/最长30d，无自动续期 | 35天断网需受控重签，不是M3补传自动恢复 |
| max_object_bytes | 候选2 GiB，正数且<=布局/provider容量 | 新意图上限收窄须Q3；历史replay不受新策略截断 |
| part_size / max_parts | 候选16 MiB / 硬上限10000，最后一片1..part_size | `N=ceil(size/part_size)`，固定后配置变化不改已有布局；配置非法启动失败 |
| 签名批次 | 候选100个；查询默认100/上限1000 | 编号唯一、总大小有界；provider分页不能遗漏 |
| part URL TTL | 候选300秒，上限300秒且不越过意图/签发身份期限 | 重试可刷新URL，不刷新意图；先保存写窗口 |
| access URL TTL | 候选默认60秒，硬上限300秒 | 现用户要求最大5分钟；不等于强制中断已有传输 |
| verifier | 候选固定版本ffprobe、MP4允许列表；类型策略需Q4 | 仅合成合法/伪装/损坏样本，执行资源预算和版本/镜像摘要在Apply固定 |
| 外部I/O预算 | 候选connect5s/read30s；验证总预算10min，临时磁盘至少max_object+余量 | 需按对象规模在Apply试验校准，耗尽不ready；不能无限等待 |
| 作业租约/重试 | 候选120s、30s续租、5次；指数退避上限5min | 重试/续租不越过业务期限，失败有终态/审计 |
| 清扫 | 候选每60s/100条；迟到宽限10min、孤儿观察24h且至少两次 | 仅技术残留；默认先dry-run清单，自动清理需Q5批准，失败非零 |

Apply部署包计划包含配置样例、独立worker/sweep命令、健康检查、启动/暂停/排空顺序、Secret及最小对象权限、私有bucket/CORS/版本检查、临时磁盘配额和恢复runbook。没有外部消息服务前置；SQL持久工作只服务本对象传输，不扩成M4领域事件总线。存储服务容量/多副本/备份由具体部署方案决定，不能把开发单机服务当高可用生产。

监控：upload/preparation/completing数与最长年龄、验证吞吐/耗时、size/hash/type失败、租约重领/旧代际拒绝、对象未绑定窗口、清理pending/最老候选/失败次数、签发拒绝与URL期限。日志仅安全ID/结果/耗时/request ID，移除Authorization、签名query、Secret、原文件名与原始媒体内容。安全/运维审计限本流程，不扩张为通用全平台审计系统。

## Risks / Trade-offs

- SQL与provider不共享事务 → 保留/意图先提交、外部I/O可重试、完整对象重新核验、代际条件提交与孤儿对账；接受短期不可读残留，不接受假ready。
- 旧part URL可重传/乱序，签名不能普遍强制字节数 → 服务端布局、确认/complete最新证据、整对象hash、配额与延后清理；不宣称撤销即阻断已有URL。
- 真实视频内容不可信、探测器有解析风险 → 固定版本、无网络/无特权、有界CPU/内存/磁盘、合成测试；具体支持格式需批准。
- 版本/条件写在兼容服务有差异 → adapter能力门禁和真实集成测试；对未测产品不宣称兼容。
- 新支持表与Asset反向引用有依赖环 → pending先无正式引用，media_object后建立，再由成功finalize回填；迁移按下节顺序处理，两后端失败回滚验证。
- 长期保留与未成年人授权未决 → 仅允许合成测试数据，生产启用前负责人决策；不顺手实现无限保存/自动删全部原件。
- Node/Device停用或主体失权时正在校验工作如何收口会影响可见行为 → 本稿建议最终提交前再判权，失权失败不ready；列Q4供明确确认，不静默采用宽松异步授权。

## Migration Plan

1. Apply新增0004，down_revision=`20261112_0003`，名称/日期在实际实施时确定；0001–0003字节保持不变。先检查M2资产没有异常ready（M2公开不可达）；发现直接插库的异常ready必须停止迁移并给出计数，不能编造验证/存储引用回填。
2. 新增UploadSession五列复合UNIQUE与布局/清单列；建media_objects→upload_parts→media_jobs→media_cleanup_candidates；再给Asset加验证列/同scope反向引用/新CHECK；最后扩幂等operation词表。SQLite batch重建时保留外键开启和显式事务，PG原生DDL事务；保留UUID/声明/原始采集时间/授权/幂等摘要，不填任何假checksum。
3. PostgreSQL应用批准表集合15→19，列出四张而不是ALL TABLES；migration/app身份、swim_cloud、version仅SELECT、canary/DDL/TRUNCATE/SET ROLE拒绝和真实容器归属/精确清理继续保留。
4. 受控迁移中断覆盖新表创建后与既有表重建中，失败回到0003结构/版本/数据；纯历史数据0003→0004→0003→0004往返。降级前若有任意媒体支持记录、验证引用/已ready数据或upload.complete幂等记录，拒绝并列分类计数，不自动删物理对象或丢弃记录；先经独立批准的导出/处置后才能重试。
5. 功能默认关。Apply验收用隔离临时数据库与专用storage namespace，只用生成媒体；逐项过M2 W1–W4、完整SQLite、完整PG及真实存储集成后才提供可启用开发profile。部署不执行生产迁移/建桶；回滚先关新签发、排空/暂停worker、保留数据库和对象对账证据，不回滚已发布迁移脚本。

## 验证与追溯

| ADR既定方向 | 本稿保持方式 |
| --- | --- |
| D1/D2 固定归属/来源 | D23–D25复合键、原发起主体、移动硬件仍用旧来源ID；不原地搬迁历史 |
| D3/D8 资源授权/路径/播放 | D25/D26/D29复用M2谓词，分User/Edge，短签名≤300秒与撤权限制 |
| D4/D10 云端权威/时间/离线 | D25保持原始采集字段，D28仅云端事务裁定；不要求采集必须在线，也不实现M4临时ID同步 |
| D5/D9 不可变资产/历史保留 | D23/D24/D30精确版本、不覆盖原件、RESTRICT、引用安全；不新增业务DELETE或本地删除 |
| D6/D7 完整上传/三层身份 | D26–D28真实分片与整对象验证，W1/W2区分幂等/逻辑asset/物理字节，不按hash合并 |
| C1/C5 分片/请求幂等 | G2/G3及W1明确可恢复传输和complete域；不是单PUT或checksum去重 |
| C2/C3/C4 业务实体/组织/角色来源 | Session仍不同于AnalysisTask，不建Pool/Lane或学员关系，不以草稿路径扩大角色权限 |

| 原需求/任务 | 设计与Spec落点 | 后续任务组与验收证据 |
| --- | --- | --- |
| G1/存储独立 | D22–D24，cloud-media-transfer的private/preparation | 2/3：Adapter contract +真实服务分页/合并/签名/失败恢复，配置门禁 |
| G2/分片续传 | D25–D26，layout/confirmation/resume | 4：User/Edge全链、乱序/缺失/重复/大列表、响应丢失恢复 |
| G3/完整校验 | D27，whole-object/final transaction与asset增量 | 5：真实字节hash/size/type、错误声明、无部分提交 |
| G4/并发 | D28，terminal races/worker recovery | 6：真实PG双业务PID+监控、两方向与故障点 |
| G5/访问授权 | D25/D29，authorization增量 | 7：角色矩阵、Asset-only grant、撤权/到期/Range、5分钟上限 |
| G6/过期孤儿 | D30，cleanup/orphan | 8：活引用与GC竞态、迟到分片、未知归属拒绝、失败非零 |
| M2 W1 | D25、asset replay + Session cancel增量 | 1.2：User/Edge取消后同键同参/异参/新键/撤权测试 |
| M2 W2/W3/W4 | D25、asset/authorization增量 | 1.3/1.4/1.5：两设备同SHA、两管理员审计、三种基准正向 |

Notion唯一任务来源，以下不是新任务或状态修改：

| 原任务与当前状态 | 本Change承接分类 | 交付/完成边界 |
| --- | --- | --- |
| [P1 分片上传](https://app.notion.com/p/410f602574aa8129ab07d088ad80aa5b) 待确认 | 直接交付G1–G6 | 任务1–10的真实实现/契约/测试/部署证据；本轮只有规划 |
| [P0 媒体权限](https://app.notion.com/p/410f602574aa811094bec51f53fe50e3) 未开始 | 直接交付上传和下载子范围 | 统一谓词+短期签名；关键帧/图表/PDF/业务替换仍后续 |
| [P0 数据模型](https://app.notion.com/p/410f602574aa811bbad3c6e452a065b6) 进行中 | 直接交付传输支持模型子范围 | 新迁移/历史保留/引用安全；不代表完整平台领域完成 |
| [P0 架构API](https://app.notion.com/p/410f602574aa816582ccc14817ce4601) 进行中 | 直接交付单对象契约子范围 | 原M3五项+新增五项，Adapter/配置/交付记录 |
| [P0 RBAC](https://app.notion.com/p/410f602574aa816e87dcd70f56c4100e) 进行中 | 直接交付媒体操作授权子范围 | 原谓词复用/撤权/身份隔离，RLS不实施 |
| [P1 隐私保留](https://app.notion.com/p/410f602574aa8121a9e4c5cfcb5131d2) 待确认 | 人工前置/后续排除 | 不实施同意、保留期限或业务删除；Q2/Q5 |
| [P0 首版范围](https://app.notion.com/p/410f602574aa8180b6c5c589e2117b01) 待确认 | 人工输入/仅提供前置 | Q3/Q4支持格式/容量/试点；不将本片视为端到端试点完成 |

## 审阅决策与 Open Questions

| ID | 未决内容与本稿建议 | 停止/实施门槛 |
| --- | --- | --- |
| Q1 | 首个Adapter建议S3协议；真实集成服务建议隔离Ceph RGW或经确认的S3兼容测试服务，具体版本/镜像摘要和许可尚未选定 | Apply前确认开发/CI实现profile；生产产品/区域不因确认测试profile冻结 |
| Q2 | 生产产品、区域、数据责任/隐私授权、未成年人同意、保留/备份/删除窗口、全视频默认同步策略均未定 | 生产启用前负责人决策；不阻塞合成数据的规划或经授权开发，但不能报生产就绪 |
| Q3 | 默认16MiB分片、2GiB对象、100批签名等候选；新增意图由2**53收窄有兼容影响 | Apply前明确批准大小/数量/TTL配置；旧意图保留并可明确拒绝物理准备，不静默截断或改声明 |
| Q4 | 媒体允许列表/探测器/资源预算；建议先MP4容器并独立验证，不承诺转码。建议最终提交重查当前主体/接受凭据和来源状态，失权则upload_failed | Apply前确认可观察格式与失权行为；当前提案规格表达安全上界，不视为已批准业务政策 |
| Q5 | 只删技术残留；迟到宽限10min、孤儿24h/两次观察、自动清扫或先dry-run待确认 | 自动物理删除前确认；ready与本地原件不纳入此参数；业务保留删除另阶段 |
| Q6 | 作业租约、并发数、退避和I/O预算为开发候选 | Apply基于有界故障试验校准并写配置/证据，不改状态机/范围；不得无限重试 |
| Q7 | SigV4/CORS/Range/版本化与端点域名的具体配置 | 在选定测试profile后填写；生产TLS/域名/Secret不写入仓库，能力不满足拒绝启用 |
| Q8 | 即时撤权代理、HLS/转码、MediaBlob共享、35天身份恢复、M4同步冲突协议 | 明确后续，不作为本M3偷偷增加的前置或已实施能力 |

Q1/Q3/Q4涉及实现profile或可观察行为，明确留待这次Draft审阅确认，**未解决不得自行Apply**；用户已要求在产品和区域等未决条件下提交Propose，本稿以候选方案供审阅，不填“默认已同意”。Q6/Q7是可延后校准/配置细节，不能因此改变规格安全边界。

本轮完成后只交付提案与Draft PR/Notion回链。没有独立Verify、Archive、主规格同步或Merge授权；所有实施验收仍为待执行。
