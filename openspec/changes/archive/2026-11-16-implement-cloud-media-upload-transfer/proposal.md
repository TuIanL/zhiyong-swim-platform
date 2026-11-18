# Proposal

## Why

main `3352c6b17b2dd3b6921028b25606a999bb69b331` 已合并 M2（[PR #5](https://github.com/TuIanL/zhiyong-swim-platform/pull/5)），能原子创建逻辑 Asset、UploadSession 与幂等记录，却不能接收、校验或安全播放媒体。M3 要补齐单个媒体对象的可恢复传输与验证闭环，让 `ready` 成为服务端完整对象校验成功的可信承诺，而不是客户端回执。

## What Changes

- 本轮已获 **Apply** 授权，按原有 42 项任务在同一 Change 与 Draft PR #6 中实施。范围限开发环境和隔离 CI；不执行独立 Verify、Archive、主规格同步、PR Ready、Merge 或生产部署。
- G1：统一 `StorageProvider` 协议并实现首个 S3 协议适配器。真实隔离集成 profile 固定为 RustFS `1.0.5-glibc`、linux/amd64、镜像 `ghcr.io/rustfs/rustfs@sha256:f36a122c886d99206df9a1dc1efcc96543db3ae206718e0527509dbf1b27c662`（Apache-2.0）；该 profile 仅为开发/CI 能力测试，不是生产存储选型。Python SDK 固定为 boto3 `1.44.3`（Apache-2.0）。
- G2：用户和 Edge 分开的 part-urls、分片确认、分片查询/恢复协议；服务端固定分片布局，核对真实 provider 回执，限制编号、大小、数量、签名动作与有效期。首次物理准备可异步返回 202。
- G3：complete 冻结分片清单并持久化校验作业。相同 key/manifest 在 `completing` 返回 202 并继续原作业，在 `completed/ready` 返回 200 当前结果，在 `failed/expired/aborted` 返回带原终态诊断的 409；同 key 不同 manifest 返回 409 `idempotency_conflict`。服务端读取同一不可变对象的全部字节，计算 SHA-256、实际大小并探测媒体类型，成功后同事务提交 `UploadSession.completed + VideoAsset.ready`。
- G4：统一 Session → UploadSession → Asset → 存储记录的 scoped 锁顺序；长时间存储 I/O 在事务外执行，租约/fencing 防止旧 worker 提交。覆盖 cancel、abort、expiry、重复 complete、重复分片确认与崩溃恢复；PostgreSQL 必须用真实独立连接证明合法胜负顺序。
- G5：复用 M2 的当前成员/Site 与 S-read/S-manage/A-read 授权。新增短时播放与下载 URL，签发前重查 A-read 和 ready，签名有效期硬上限 300 秒；撤权阻止新签发，既有 URL 的剩余有效期及已开始传输限制如实记录。
- G6：可重试过期清扫、multipart abort、验证失败残留和孤儿对象回收。先做引用核验、终态和代际检查、清理登记，再删精确物理句柄；未知归属、权限错误与无法确认删除均不得报成功。不得自动清除仍被有效 Asset 引用的内容或 Edge 本地原件。
- M2 WARNING-1：同主体/作用域/键/摘要命中时重放原 Asset/UploadSession 的**当前终态**，取消不复活上传；新键在 cancelled Session 上仍 409，同键异参仍幂等冲突，User/Edge 一致。WARNING-2/3/4：补齐同 SHA 独立采集、grant 首次审计字段及 UTC/Offset/IANA 正向端到端回归，分别进入规格与任务。
- 拟新增四张支持表 `media_objects`、`upload_parts`、`media_jobs`、`media_cleanup_candidates`（15 → 19 表）；扩展 Asset 的验证字段/存储引用、UploadSession 的分片布局和 complete 清单摘要，以及共享幂等操作词表。**不建 MediaBlob，不做物理内容去重**，每个逻辑 Asset 保留独立来源、时间、授权和对象引用。
- 新建意图采用 2 GiB 上限、16 MiB 固定分片及每次最多 100 个签名；保留 M2 对历史合法意图的请求解析能力。必须先确认身份、当前资源权限和既有幂等记录，再仅对真正新建的请求应用容量策略。历史超过 2 GiB 的意图仍可读取、同键重放、中止和到期；物理准备返回 `transfer_policy_conflict`，不得更改原声明。
- 首版仅接受通过固定版本、无网络且受限资源的 `ffprobe` 检查的 MP4 容器；声明类型与探测结果须一致，不转码。最终发布 `ready` 前重新核验当前主体权限、被接受的原身份有效性、Edge Node/Device 状态、UploadSession 状态与期限；身份失效则以 `upload_failed` 配对失败并保留安全审计原因。
- M3 只负责单对象链路；M4 才负责完整云边 Outbox/Inbox、批量任务同步、冲突解决和跨实体最终一致性。排除自动凭据续期/35 天离线恢复、生产部署、学员/监护人业务、转码/HLS、分析、业务删除与保留政策自动化、RLS。

## Capabilities

### New Capabilities

- `cloud-media-transfer`：私有存储适配、可恢复分片、complete 持久作业、完整对象校验、并发终态裁定、故障恢复与安全物理清扫。

### Modified Capabilities

- `cloud-media-asset`：允许经过完整对象校验的 ready；明确声明值/验证值与不可变对象绑定、终态 replay、同 SHA 独立采集和合法采集时间组合。
- `cloud-media-authorization`：媒体传输主体边界、当前 A-read 下的短时播放/下载签发、grant 重复请求的首次审计字段保证。
- `cloud-training-session`：区分取消后的既有意图重放与新建，明确取消与 completing/finalize 的竞争及已 ready 资产保留。
- `cloud-identity`：扩展显式批准表集合为 19，增加 M3 增量迁移/安全降级与最小权限证据，保留现有容器真实归属、独立连接、清理失败非零等保证。
- `cloud-edge-registry`：消除“节点凭据只授权 heartbeat”与 M2 已实现节点上传意图的文字冲突，明确仅扩展到所属节点发起的上传，仍不授予用户权限或他人资源权限。

## Impact

- 基线实查：15 张业务表、33 paths / 47 operations；`media.py` 无分片/complete/ready 路径，`upload_read.confirmed_parts` 恒空；M2 已归档且四项 WARNING 未关闭。README、领域/API/ADR 的部分历史段落仍写“未来/无表”，以主规格、0003、实际代码及 [M2 Verify](../2026-11-14-implement-cloud-session-asset-foundation/verification.md) 定位真实能力，不在本轮改写历史。
- Apply 预计触及云端模型、新增 0004（不改 0001–0003）、存储适配模块、worker/清扫 CLI、API/schema、双后端与真实对象存储集成测试、依赖锁、CI、部署说明及正式领域/契约文档；均是后续实施任务。计划新增 10 个 HTTP 操作（含原契约 M3 五项），已有 47 个操作只做明确列出的增量/修复。
- 直接复用 [P1 分片上传与完整性校验](https://app.notion.com/p/410f602574aa8129ab07d088ad80aa5b)；关联 [P0 媒体权限](https://app.notion.com/p/410f602574aa811094bec51f53fe50e3)、[数据模型](https://app.notion.com/p/410f602574aa811bbad3c6e452a065b6)、[接口架构](https://app.notion.com/p/410f602574aa816582ccc14817ce4601)、[RBAC](https://app.notion.com/p/410f602574aa816e87dcd70f56c4100e)。[隐私/保留/删除](https://app.notion.com/p/410f602574aa8121a9e4c5cfcb5131d2)与[首版范围](https://app.notion.com/p/410f602574aa8180b6c5c589e2117b01)是待决输入，不能把本 Change 当作这些总体任务完成；不创建重复任务，不改任何状态、负责人或日期。
- Apply 验收须通过完整 SQLite、PostgreSQL 与真实隔离存储集成；所有 CI 结果绑定最终实际 Head。生产供应商/区域、隐私与监护人同意、保留/备份/删除政策仍未冻结，生产媒体存储保持禁用。
