# Cloud Media Transfer：Apply 实施与回归记录

- 日期：2026-11-14（Asia/Shanghai）
- OpenSpec Change：`implement-cloud-media-upload-transfer`
- 分支：`feat/cloud-media-upload-transfer`
- 批准 Proposal Head：`d36273a3c49176dd2639f3349d2f09eae8fe9ebd`
- Apply 代码验证 Head：`b2ccced661083967f9ef4fabb27282abba9270e3`
- PR：[Draft PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6)
- Apply Tasks：42/42；本记录只记录 Apply 证据，不构成独立 OpenSpec Verify。

本轮按负责人授权在开发环境与隔离 CI 实施。main 基线保持 `3352c6b17b2dd3b6921028b25606a999bb69b331`。生产存储、隐私与监护人同意、保留/备份/删除政策没有在本 Change 冻结。

## 1. 交付范围

| 面 | 实际交付 |
| --- | --- |
| 数据库 | 新迁移 `20261114_0004_cloud_media_transfer`；新增 `media_objects`、`upload_parts`、`media_jobs`、`media_cleanup_candidates`。保留 0001–0003；升级后共 19 张业务表。 |
| 传输服务 | 新增统一 `StorageProvider` 协议与 S3 adapter，固定 `boto3==1.44.3`；按服务端生成的精确对象 key、版本与 scope metadata 管理私有对象。 |
| API | 新增 10 个 HTTP 操作：User/Edge 分片准备与签名、分片确认、分片列表/恢复、complete、播放 URL 和下载 URL。总计 43 paths / 57 operations。 |
| 作业与验证 | 持久 initialize/complete worker、租约与 generation fencing、实际全对象 SHA-256/字节数、固定版 ffprobe 受限 MP4 探测、最终身份与授权复核、原子 `completed + ready` 提交。 |
| 清理 | 有界过期清扫、精确 multipart/object-version 清理、分页孤儿发现、双次观察/宽限、dry-run 默认值及失败重试/人工处理。 |
| CI | PostgreSQL 17 专用可销毁实例；真实 S3-compatible RustFS 隔离 job；SQLite、PG 与 storage 三类完整验收分别保留。 |

不在本 Change 范围：MediaBlob、按摘要合并逻辑资产、M4 Outbox/Inbox 与批量同步、HLS/转码、Edge 本地原件删除、RLS、生产部署及生产存储政策。

## 2. 审阅修订与安全语义

### M2 W1–W4

- W1：身份与当前资源能力核验后，在 cancelled 新建检查前按主体域查询既有幂等记录；同参重放原 Asset/UploadSession 当前终态，异参返回 `idempotency_conflict`，新键仍因 cancelled 被拒。User 与 Edge 路径均有共享 API 测试。
- W2：相同 SHA 不折叠逻辑资产。共享 API 与 RustFS 实测用两个 Device 和不同幂等键上传相同字节，验证不同 Asset/UploadSession、来源、采集时间和物理对象版本。
- W3：Owner/Admin 对 grant 的后续 PUT/DELETE 不覆盖首次 `granted_at/by` 与首次 `revoked_at/by`；共享持久字段测试覆盖。
- W4：UTC、显式 offset 和 IANA timezone 的有效组合可往返；非法/不一致组合拒绝；原始设备时间字符串不改写，服务端 `received_at` 不冒充采集时间。

### 大小、幂等与终态

- 新意图上限 2 GiB、固定分片 16 MiB、每批最多 100 个签名；Part URL 最长 300 秒，访问 URL 默认 60 秒、硬上限 300 秒。
- M2 历史意图先通过结构解析、身份/资源权限检查和既有幂等查找；历史超过 2 GiB 的意图仍可读取、同键重放、中止和到期。其物理准备返回 `transfer_policy_conflict`，不更改已声明容量。
- Complete 相同 key/manifest：`completing` 返回 202 并复用原作业；`completed/ready` 返回 200；`failed/expired/aborted` 返回带原终态的 409，不重新排队或改写原因；同键不同 manifest 返回 409 `idempotency_conflict`。

### 锁、身份与外部 I/O

- 业务行采用 `Session → UploadSession → Asset → media_objects → media_jobs/parts/cleanup` 顺序；SQLite 用事务内条件写维持竞争语义，PostgreSQL 以行锁和条件代际更新裁定竞争。
- 对象存储、下载流、ffprobe 均不在持有业务事务锁时执行；最终 ready 短事务重新检查 scope、当前用户权限/原认证会话、Edge Credential、Node/Device 状态、UploadSession 状态和期限、generation 与精确对象版本。
- 最终身份在验证期间失效时不提交 ready，UploadSession 与 Asset 配对 `failed/upload_failed` 并保留作业原因。User 登录过期、登出、角色失权、Edge Credential 到期和 Device 停用场景由隔离存储测试覆盖。长时间上传/校验因此可能成功传输但无法形成 ready；客户端须重新获得有效身份并创建新意图。
- PostgreSQL 受控竞争使用两个业务 backend 与独立监控连接，断言互异 `pg_backend_pid()`、`wait_event_type=Lock` 与 `pg_blocking_pids()`；锁等待和释放均有界，不使用单连接或随机 sleep 冒充证据。

## 3. 数据库、兼容性与部署

- 四张新增表使用 scope 复合键、外键 RESTRICT、状态/字段 CHECK、候选精确对象身份、唯一约束与必要索引；应用 PostgreSQL 身份只获批准的 19 张业务表必要 DML/SELECT。原初始六表、0001–0003 迁移及 M2 既有字段/幂等数据保持不变。
- SQLite 批量迁移、PostgreSQL 迁移反射、失败回滚、降级保护和历史 M2 记录保留均有测试；含 M3 行、对象引用或新幂等语义时拒绝有损降级。
- 保持旧身份 19 操作、Registry 12 操作和 M2 16 操作兼容；OpenAPI 快照与运行时一致，为 43 paths / 57 operations。
- 媒体 profile 默认关闭；应用启动不自动迁移或创建 bucket。隔离 CI 固定 RustFS `1.0.5-glibc` linux/amd64 镜像 digest `sha256:f36a122c886d99206df9a1dc1efcc96543db3ae206718e0527509dbf1b27c662`（Apache-2.0），ffprobe 为 6.1.1。该 profile 是开发/CI 能力测试，不代表生产产品选择。

## 4. 测试与 CI 证据

完整 workflow run [43605429270](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43605429270) 的 artifact metadata 将分支 head 绑定到 `b2ccced661083967f9ef4fabb27282abba9270e3`；三个 job 均成功。

| 环境 | 结果 | 证据 |
| --- | --- | --- |
| 本机 SQLite 完整测试 | **194 passed / 91 skipped**；skip 为 PostgreSQL 与真实存储标记。Python 3.13/SQLite datetime adapter 有 202 条弃用警告。 | 本机 `/tmp/swim-m3-venv`，`python -m pytest services/cloud/tests` |
| CI SQLite | **194 passed / 91 skipped / 0 failed** | Run [43605429270](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43605429270)，`test` job |
| PostgreSQL 17 | **265 passed / 20 skipped / 0 failed**；收集 ledger `shared=189`、`postgresql=76`。包含独立连接、Cancel/Abort/Expiry 与 Finalize 双向竞争、分片确认/准备、作业租约及 cleanup-vs-finalize。 | 同一 run，`PostgreSQL 17 validation`；[PG evidence artifact](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43605429270/artifacts/14118401915) |
| 真实 RustFS S3-compatible | **15 个 storage 场景通过 / 0 失败**；真实分片 PUT/List/Complete/HEAD、SHA/ffprobe、ready、断点/丢回执恢复、Range、访问 URL 到期、身份变化、精确清理和孤儿回收均执行。 | 同一 run，`Isolated media transfer (RustFS)`；[RustFS evidence artifact](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43605429270/artifacts/14117833621) |
| PostgreSQL 容器清理 | 主清理 `removed`；CI 兜底确认 `absent`、exit 0。 | 同一 run，PostgreSQL job 原始日志 |
| RustFS 容器清理 | 精确归属验证后 `removed`。 | 同一 run，RustFS job 日志及脱敏 evidence artifact |

本机未运行 Docker 真实服务；真实 PostgreSQL 与 RustFS 结论只取自上述隔离 CI，不把本机 SQLite 结果替代它们。

### CI 失败与修复轨迹

保留的失败 run 记录为 Apply 调试证据，没有将中间失败改写成通过：

- [43602578421](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43602578421)：首次完整 CI 暴露受控并发监听器在准备请求阶段被提前触发、测试事件与真实 worker 线程不一致，以及 RustFS 编排在设置环境前读取 run id。将并发监听延迟到受控请求开始，改用不同 backend PID/数据库锁观测，并调整编排初始化顺序。随后 run 43603697126 继续发现并修复两项残余并发问题。
- [43603697126](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43603697126)：发现 PostgreSQL 过期竞争测试监听错锁行、并发确认可能读取 stale ORM 状态，以及 RustFS `docker rm --time` 无效。修正竞态监测行、确认后刷新数据库状态，并将 RustFS 停止与删除分为两个有效 Docker 命令。
- [43604480302](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43604480302)：RustFS 测试暴露 initialize worker 未接收 media settings，以及测试误读未公开的 scope 字段；二者均修正。
- [43604761277](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43604761277)：真实媒体用例发现测试账号名冲突、过期时间注入违反 deadline CHECK、Edge 失权用例的声明 SHA 与真实媒体不一致。测试改为唯一主体、保持期限约束并使用真实媒体 SHA。
- [43605160624](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43605160624)：complete 幂等终态用例还发现一个期限时间注入违反 CHECK；调整历史时间戳，保留原约束。

以上失败均由后续 run 43605429270 的 SQLite、PostgreSQL 和真实 RustFS job 全绿验证修复。新增任务/测试证据没有删减失败场景或放宽失败语义。

## 5. OpenSpec 与契约检查

- Change strict：`openspec validate implement-cloud-media-upload-transfer --strict` 通过。
- 主规格 strict：`openspec validate --specs --strict`，5/5 通过；按 Apply 边界尚未执行主规格同步。
- `git diff --check` 与 Python `compileall` 通过。
- 运行时 OpenAPI 与 `docs/contracts/openapi.json` 一致（43 paths / 57 operations）。
- Proposal、Design、Tasks、6 份 Spec Delta、实现路由、模型/迁移和正式 API/领域文档按同一 D 决策及 42 项验收对照。
- 独立 OpenSpec Verify、Archive、PR Ready、Merge 与生产部署均未执行。

## 6. 已知限制与交接

- RustFS/S3 协议适配只证明固定隔离 profile 的能力，不构成生产供应商、区域、隐私、监护人授权、保留/备份/删除或灾备决策。
- 不含即时撤销已签 URL、媒体转码/HLS、云边批量同步、Edge 离线身份恢复、RLS 或生产部署。
- SQLite datetime adapter 与 GitHub runner 的 Node.js action 弃用警告未影响结果；仍是后续维护事项。
- M3 Apply 交付后等待负责人独立 Verify 授权；Notion 原 P1 任务的状态、负责人、日期保持原样，本轮只追加证据链接。
