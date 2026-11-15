# Independent OpenSpec Verify — Cloud Media Transfer

- 核验日期：2026-11-15（Asia/Shanghai）
- Repository：TuIanL/zhiyong-swim-platform
- PR：[#6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6)，核验时仍为 Draft
- Change：implement-cloud-media-upload-transfer
- 固定 Apply 代码 Head：ba2216b058ebcbf3b51d59fcd80d6f073ad36961
- main 基线：3352c6b17b2dd3b6921028b25606a999bb69b331
- 固定 CI：[Run 43606071954](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43606071954)
- Apply Tasks：文件记载 42/42；本报告不改写该历史状态。

本报告只审计固定 Apply Head。提交本报告产生的文档提交不属于被验证的业务代码 Head，也不构成对该新提交执行过业务回归的声明。PR 工作流 checkout 是临时 merge ref 5b323dfe0ddcf047a457dac2b637c6ed8a2bd537，其输入为固定 PR head 与 main 基线；两个 CI artifact 的 metadata head_sha 均为固定 Apply Head。

## 结论摘要

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| CRITICAL | 1 | 永久授权 grant 会清空登录会话期限，播放和下载 URL 可越过登录会话期限。 |
| WARNING | 3 | ready 对象的物理版本缺失未在签发前探测且指定 RustFS 负向场景未执行；User/Edge 已冻结分片布局会受配置更新影响；Apply 报告中的最终 head/CI 仍指向较早提交。 |
| SUGGESTION | 2 | CI 有 Python/SQLite 与 GitHub Actions 弃用警告；已发签名 URL 的撤权窗口是对象存储能力边界，应在客户端和运营说明中持续明确。 |

**判定：有合并阻断问题；不满足 Archive 条件；需要定向修复并复验。** 42 项任务都有至少一个实现或测试落点，但不能按 42/42 宣告全部独立验收通过：4.2、7.1、7.2、10.1、10.3 的验收证据分别受 V3、V2/V1、V2/V3、V1/V2 与 Apply 报告 head 不一致影响。其它已取得证据的场景见下方逐要求追溯表。

V1 是实际权限期限越界，属于 CRITICAL。V2 的 CI 没有在 RustFS 中删除精确 ready 版本后请求播放/下载；本机 Docker daemon 不可用，因此指定物理存储负向场景为 **Not verified**，不能把 stub API 探针升级成真实存储通过。V3 已用真实 API 请求重现，User 和 Edge 均拒绝了首次布局中合法的末片。

## 固定基线与证据

### Pull request 与源码状态

- PR 当前 open、draft=true、mergeable=true；head 为 ba2216b058ebcbf3b51d59fcd80d6f073ad36961，base main 为 3352c6b17b2dd3b6921028b25606a999bb69b331。本轮没有改变 PR 状态、main 或业务源码。
- Apply 报告 [cloud-media-upload-transfer-apply.md](../../../docs/verification/cloud-media-upload-transfer-apply.md) 仍写 Apply head b2ccced661083967f9ef4fabb27282abba9270e3、CI 43605429270。PR 正文、CI artifact metadata 和 Notion 已引用较新的 ba2216b / 43606071954。旧报告没有给出最后一个提交的完整测试证据，任务 10.3 的最终证据链不完整；这是报告可追溯性问题，不会把旧 run 冒充新 run。
- 变更相对 main 只新增迁移 services/cloud/src/swimplatform/migrations/versions/20261114_0004_cloud_media_transfer.py；0001–0003 历史迁移未改写。当前 schema 为 19 张业务表。
- CI logs 的 checkout 为 PR 合并临时 ref，不能将 merge ref SHA 当成 Apply code head。PR 元数据及两个 artifact 的 workflow_run.head_sha 明确绑定固定 head。

### Run 43606071954 原始日志与 artifacts

| Job / artifact | 原始结果 | 绑定与清理证据 |
| --- | --- | --- |
| SQLite test | 194 passed / 91 skipped / 0 failed；203 warnings | Job 成功；91 个 skip 是 PostgreSQL 与独立 RustFS 标记，不等同于全部业务场景跳过。 |
| PostgreSQL 17 validation | 265 passed / 20 skipped / 0 failed；收集 ledger shared=189、PostgreSQL=76 | Run id f74268ac52cda110；主清理 removed；cleanup-run-file 为 absent、exit 0。15 个 storage 案例在单独 RustFS job 运行，5 个为 SQLite 专属。 |
| Isolated media transfer (RustFS) | 15 passed / 0 failed | RustFS 1.0.5 linux/amd64，镜像 digest sha256:f36a122c886d99206df9a1dc1efcc96543db3ae206718e0527509dbf1b27c662；容器按本次 run/name/id/label 校验后 removed。 |
| PG artifact | postgresql-evidence，ID 14118535563，digest sha256:65fbe8d3d151235f7c2c0cfe3e137f35429ee69d0c91adf0ef62270ca6ae8869 | artifact metadata head_sha=ba2216b；包含 JUnit 与脱敏 JSON。 |
| RustFS artifact | rustfs-media-evidence，ID 14117424479，digest sha256:dcfab48a681ed87ee639ab45aebea2091863ea6650fc19f86236484cbefc2958 | artifact metadata head_sha=ba2216b；包含 JUnit 与脱敏 JSON。 |

PostgreSQL JUnit 属性记录了两个业务 backend PID 与第三个 lock-monitor PID，三者互异；监控记录 wait_event_type=Lock、wait_event=transactionid、pg_blocking_pids(second_pid) 指向第一业务 PID。受控顺序覆盖 Cancel/Abort/Expiry 与 Finalize 的两边胜出、重复 complete、分片确认/准备、GC 与 finalize、租约接管。不是线程启动或随机 sleep 的替代证据。

RustFS 15 个通过的存储场景包括完整上传/断点恢复/私有 Range、相同字节保留不同设备来源、provider Complete 后数据库版本记录前崩溃恢复、真实分片大小校验、错误大小精确版本清理、伪装非 MP4 拒绝、过期和精确 MPU 清理、User/Edge 身份失效、角色/设备撤权、取消后对象清理、分页孤儿发现及不得删除 ready 引用。该集合没有 V2“ready 版本被删除后请求 URL”案例，也没有 V3“重新加载不同分片配置后恢复旧布局”案例。

## V1–V3 定向实证

探针通过真实 FastAPI 路由、SQLAlchemy SQLite 测试数据库和可观测的 provider stub 发起请求；临时探针文件在审计后移除，没有进入提交。V2 的 stub 只用来确认路由是否调用对象存在性 API，不能证明真实 RustFS 对不存在版本的响应。

| 编号 | 构造与观测 | 预期 | 结论 |
| --- | --- | --- | --- |
| V1 URL TTL | 登录 AuthSession 剩约 10 秒；有效永久 SessionReadGrant；读取 TTL=60 秒。分别请求 playback-url 与 download-url，均返回 200，expires_at - now = 60s，provider 收到 TTL=60。另测 30 秒有效 Session grant、永久但已撤销 Asset grant，结果为 30 秒。 | 所发 URL TTL 必须不超过当前登录会话与实际授权路径剩余期限。 | **Fail / CRITICAL**：永久 grant 分支把 deadlines=[]，一并丢弃 AuthSession deadline；有限 grant 与 revoked grant 分支符合预期。 |
| V2 Ready 物理版本丢失 | DB 中置 ready Asset 与 verified 精确 version，但 provider stub 无对象并且没有 head/get 存在性方法；播放及下载路由均返回 200 并调用 signer。独立 CI RustFS 没有先删除 exact ready version 再请求的用例；本机 Docker daemon 不可用，未执行真实 RustFS 物理缺失场景。 | 物理精确版本不能确认存在时返回 503 media_unavailable，不返回 URL、不改签最新版本、不改写 ready 历史。 | **Not verified / WARNING**：API 路由当前只检查 DB 绑定对象；S3 signer 只生成 presigned URL。真实物理缺失后的 API 状态仍缺实证，当前实现没有签名前 HEAD。 |
| V3 冻结布局 | User 与 Edge 各创建 40 MiB 意图，数据库布局置为首次保存的 16 MiB、3 片；将 app 当前配置改成 32 MiB 后请求 part 3。两条路由均返回 422“分片编号超出上传布局”。重新请求 part 1 仍返回 expected size 16 MiB；DB 布局仍是 16 MiB/3 片。 | 已存在布局始终由持久化的 part_size/count 决定；合法末片可续传，末片大小为剩余字节。 | **Fail / WARNING**：重新加载配置影响了编号上限，虽没有改写 DB 布局，却打断合法断点恢复。 |

对应位置：

- V1：media_transfer.py 1017–1053，永久 grant 清空期限在 1042–1043 行。已有 test_media_transfer_storage.py 172 行附近覆盖有限 grant 和短配置 TTL，但没有“短 AuthSession + 永久 grant”。
- V2：media_transfer.py 1003–1010、1059–1064；storage.py 247–255 的 S3 sign_read 仅生成签名，不与 provider 交互。RustFS 测试缺失指定负向场景。
- V3：User media_transfer.py 566–576，Edge 670–679 行。两个分支均先按当前 settings 重算 count，再读取持久 layout。

## Findings

### CRITICAL

#### C1 — 永久授权路径绕过登录会话的 URL TTL 上限

- Requirement/Scenario：cloud-media-authorization / Signed access is short lived and explicitly revocable only for new issuance / URL expiry Range and download disposition；同时适用于播放和下载 URL TTL。
- 位置：services/cloud/src/swimplatform/media_transfer.py 1017–1053，尤以 1042–1043 行为因果点。
- 复现：AuthSession 剩 10 秒；当前有效永久 SessionReadGrant；read URL 配置 60 秒；调用 playback-url 或 download-url。
- 实际：两请求均 200，签名 URL TTL 为 60 秒，超出 AuthSession 约 50 秒。provider 签发的数据仍是精确对象版本，但 URL 是 bearer capability；登录会话失效后仍可使用它。
- 预期：TTL 不超过 AuthSession 剩余期限和仍然有效的授权路径期限。永久授权只表示 grant 不过期，不表示登录凭据 deadline 消失。
- 为什么现有测试没拦截：test_media_transfer_storage.py 覆盖有限 grant 和极短配置 TTL，但没有短登录会话与永久有效 grant 的组合；CI 全绿不能覆盖未构造的组合。
- 最小修复建议：保留 deadlines=[auth.expires_at] 永远作为身份上限；永久 grant 只表示不追加 grant deadline，不能清空已有 auth deadline。增加 User playback、download 的永久 grant/短 AuthSession 测试，并保留有限、多 grant OR、撤销一路径测试；SQLite 与真实 RustFS 各验证签名 TTL 和过期后 provider 拒绝。

### WARNING

#### W1 — ready 对象的精确物理版本未在 URL 签发前确认存在

- Requirement/Scenario：cloud-media-authorization / Current asset authorization governs access signing / Non-ready or missing physical object；cloud-media-transfer / Final verification commits both terminal states / Replaced or missing object。
- 位置：media_transfer.py 1003–1010、1059–1064；storage.py 247–255。
- 复现：DB 保留 ready/verified 与 object_version；在 provider 删除该精确版本后分别请求播放和下载 URL。
- 实际：固定 RustFS CI 没有执行该场景。API runtime stub 探针证明路由未调用 head_object/open_object 就返回 200 并生成签名 URL；这不是物理存储负向实证。S3 adapter 的签名方法本身不请求 S3，因此不能确认版本存在。
- 预期：返回 503 media_unavailable，响应不含 URL；不签最新 key/version，不改写已提交的 ready 状态。
- 为什么现有测试没拦截：RustFS 15 个场景验证上传与成功访问、异常 Complete、Range 和清理，但没有在 ready 后删除精确 version 再请求 URL；API 单测也没有断言调用精确版本 HEAD。
- 最小修复建议：补充有界的精确版本可用性检查并将 provider NotFound 与权限/网络错误分别映射；添加 RustFS 真实删除版本用例，断言 503、无 URL、Asset 仍 ready 且 storage_object_ref/version 不变。独立 RustFS 实测完成前本项保持 WARNING/Not verified。

#### W2 — 已保存的 multipart 布局仍受进程当前配置限制

- Requirement/Scenario：cloud-media-transfer / Bounded multipart layout and part credentials / Invalid part request；Resume queries reconcile all parts / Network interruption and lost receipt；cloud-training-session / Cancellation closes unfinished uploads / Upload operations follow the parent-first lock order。
- 位置：media_transfer.py 566–574 与 670–677 行；持久期望大小计算在 624 行调用 _part_size。
- 复现：首次布局为 16 MiB、3 片；重启/热更新后 media_part_size_bytes=32 MiB；请求原布局 part 3。
- 实际：User 与 Edge 都返回 422；原 DB 布局未改，part 1 仍按 16 MiB 签发。配置只影响合法编号判定，导致不能恢复原末片。
- 预期：对已有 UploadSession.part_size_bytes/part_count 使用冻结布局核验编号，并用已保存布局计算末片大小。新配置只用于尚未持久化布局的新传输。
- 为什么现有测试没拦截：RustFS 断点恢复测试在同一配置下完成；PG 同布局并发准备不覆盖重启后配置变化。
- 最小修复建议：只有首次创建物理对象/登记 layout 时从配置读取 part size；既有对象先用 DB layout 校验编号和大小。补 User、Edge 的配置重载/进程重启回归，验证最后一片 expected size、签名和确认可继续完成。

#### W3 — Apply 验收记录未回填最终测试 Head

- Requirement/Scenario：任务 10.3（最终 Apply 证据绑定实际代码 head）；任务 10.4 的最终 CI 回链。
- 位置：docs/verification/cloud-media-upload-transfer-apply.md 顶部及第 4 节仍记录 b2ccced... / 43605429270；PR 正文和 artifacts 已指向 ba2216b... / 43606071954。
- 触发条件：审阅者只按 Change 内 Apply 记录追踪最终代码。
- 实际：CI 43606071954 的 raw logs/artifact metadata 确认最终 head 全绿；但 Apply 记录自身不是最终 head 的报告，证据散落在 PR/Notion，任务定义的单一 Apply 回链不闭合。
- 预期：Apply 报告保留早期历史，同时追加最后代码 Head、Run 与 artifact，不覆盖原历史。
- 为什么任务/strict 没拦截：严格格式、链接与测试命令通过不验证报告中的 SHA 是否等于最终 head。
- 最小修复建议：在新授权的定向文档修复中仅追加“最终 Apply Head / Run / artifacts”更正记录；不要覆盖早期 head 或失败历史。该问题不改变 Run 43606071954 测试结果，但影响交付可追溯性。

### SUGGESTION

#### S1 — SQLite datetime adapter 弃用警告

- 证据：CI SQLite 原始输出 194 passed，但包含 SQLAlchemy/Python 3.13 对 SQLite datetime adapter 的弃用警告；不影响当前结果。
- 建议：后续维护时明确时区序列化/反序列化 adapter，避免未来 Python 版本行为变化。不是本 Change 的直接合并阻断。

#### S2 — GitHub Actions Node.js 20 弃用通知

- 证据：三个 CI job 报告 checkout@v4、setup-python@v5、upload-artifact@v4 将由 runner 切至 Node.js 24；当前 job 成功。
- 建议：按仓库兼容性策略升级 actions 版本并重跑 CI。此项是工具链维护建议。

## 42 项 Apply Tasks 核对

状态只表示独立 Verify 核验，不修改 tasks.md 中原有 42/42。

| Tasks | 独立核验结论 | 实证摘要 |
| --- | --- | --- |
| 1.1–1.5 | 有证据 | Proposal/Design 冻结 Q1–Q8；M2 W1–W4 对应共享 API、授权及真实存储测试，下节逐项列出。 |
| 2.1–2.4 | 有证据 | 0004 与模型/迁移测试覆盖 19 表、复合 scope、CHECK/唯一/RESTRICT、历史迁移保护、失败回滚及最小 PG 权限；CI PostgreSQL job 通过。 |
| 3.1–3.4 | 有证据 | StorageProvider/S3、受限 RustFS profile、编排归属与清理、真实 multipart I/O 在 Run 43606071954 的 15 个 RustFS 场景通过。V2 是 URL 签发时的物理存在性检查缺口，不否定上传传输测试。 |
| 4.1 | 有证据 | 持久 initialize 与并发唯一对象/作业；RustFS 完整传输和初始化恢复。 |
| 4.2 | 部分通过 | 基础编号/TTL/签名与 Part URL 测试通过；V3 表明已有 layout 的末片仍被新配置拒绝。 |
| 4.3–4.5 | 有证据 | provider 回执确认、完整分页/恢复、当前身份与 scope 测试；PG 真实确认并发及 RustFS 丢回执恢复通过。 |
| 5.1–5.5 | 有证据 | 同 key/manifest 终态、固定清单、异步 worker、整对象 hash/size/ffprobe、错误 Complete 与数据库提交前恢复有测试。最终 Access URL 检查另见 W1/V2。 |
| 6.1–6.4 | 有证据 | 代码遵循父 Session → Upload → Asset → Object；PG 独立 backend + monitor 观测锁等待；finalize 双向竞争、租约代际、身份失效用例通过。 |
| 7.1 | 部分通过 | 角色、范围、资产 grant 与精确 DB object reference 有覆盖；V2 的 ready 但物理版本缺失真实 RustFS 场景未执行，当前实现也未在 signer 前验证。 |
| 7.2 | 部分通过 | 有限授权期限、撤销路径与访问 URL 行为有测试；V1 的 AuthSession deadline 被永久 grant 清空。 |
| 7.3 | 有证据 | RustFS 私有读取、Range、CORS、访问到期和不暴露列表/写权限场景通过。 |
| 8.1–8.4 | 有证据 | 到期终结配对、精确 MPU/object version 清理、失败/孤儿发现、ready 引用保护和清理执行归属有 SQLite/PG/RustFS 测试。 |
| 9.1–9.4 | 有证据 | profile 默认关闭、能力门禁、worker/sweep 与 OpenAPI/文档、CI 必需场景和清理 gate 通过；生产存储仍禁用。 |
| 10.1 | 部分通过 | 固定 head 的 SQLite/PG/RustFS 全套通过，但 V1/V2/V3 边界组合未被该 CI 测试集合覆盖。 |
| 10.2 | 有证据 | Change strict、main-spec strict、OpenAPI snapshot、相对链接及 git diff --check 已通过；本报告提交后重新执行并记录。 |
| 10.3 | 部分通过 | Apply 报告保留早期历史但没有最终 head/run 补录，见 W3。 |
| 10.4 | 有证据 | 同一 PR #6 Draft、当前分支和最终 CI/artifact head 一致；PR 和 Notion 的 Apply 回链未更改属性。 |

## 29 Requirements / 96 Scenarios 双向追溯

每行列出 Requirement 的全部 Scenario 名称、实现入口、测试入口及固定 CI 结果。除明确标为 Partial/Not verified 的条目外，对应自动化场景在固定 Run 中通过；skip 分类见“固定基线与证据”。源码路径均相对仓库根目录。

### cloud-edge-registry（1 Requirement / 2 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Independent revocable edge credentials → User and node identity separation；Node credential is not a general media credential | services/cloud/src/swimplatform/media.py Edge intent；media_transfer.py Edge transfer；edge_registry.py identity validation | test_media_edge_intent.py、test_media_transfer_storage.py；User/Edge token 互换拒绝、来源 Node/Device 状态与 source 绑定；共享 CI 与 RustFS CI 通过。 |

### cloud-identity（2 Requirements / 15 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Isolated database validation → Initialization points to external database；PostgreSQL target is not owned by this run；Restricted application identity；Failure during test execution；Unapproved table is not automatically granted | scripts/test-postgresql.py；services/cloud/tests/pg_support.py；test_pg_harness_guard.py / collection guard | PostgreSQL job 真实容器、目标与受限应用身份探测；fail-safe/collection guard 和权限拒绝通过。容器 removed；cleanup-run-file absent/exit 0。 |
| PostgreSQL schema integrity → Empty database migration and round trip；Invalid cross tenant reference；Unique keys and cascading removal；Interrupted migration transaction；Approved incremental migration preserves foundation；Stepwise downgrade keeps earlier increments；Restrict blocks history loss through parents；Media transfer increment is reflected and least privileged；Safe media downgrade guard；Media migration interruption preserves M2 | 20261114_0004_cloud_media_transfer.py、models.py、migration/env；PG app grants | test_postgresql_schema.py、test_postgresql_identity.py、test_media_schema.py、test_media_migration_guards.py；PG/SQLite 迁移、约束、回滚和降级保护通过。旧六表及 0001–0003 未修改。 |

### cloud-media-asset（6 Requirements / 21 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Logical asset identity is per capture → Same content from two captures；Idempotent replay is not a new capture；Different cameras keep identities through verification | media.py 意图幂等；media_transfer.py 对象和 Asset 映射 | test_media_foundation.py、test_media_edge_intent.py、RustFS test_identical_bytes_from_two_devices_verify_as_distinct_assets；相同 SHA 不合并逻辑资产，通过。 |
| Capture time keeps raw device values → Raw values survive round trip；Unknown basis cannot carry UTC；Basis-specific fields must agree；Ordering of known instants；Valid UTC offset and IANA capture metadata | schemas.py、media.py intent/read | test_raw_device_time_is_preserved_verbatim、test_valid_capture_time_bases_round_trip_through_asset_api、非法 basis 场景；SQLite/PG shared CI 通过。 |
| Declared media metadata is not verified metadata → Intent response before any bytes；Invalid declaration is rejected early；Verified values and original declaration remain separate | schemas.py、models.py、media_transfer.py verifier/finalize | test_media_foundation.py、test_media_schema.py、RustFS 错误类型/声明与 probe 测试；完成前保留声明，ready 写入验证值，通过。 |
| Upload session terminal states pair with asset failure → Abort pairs both sides；Repeated terminal request does not rewrite history；Terminal state is final | media.py abort/GET expiry；media_transfer.py _terminalize_locked、cancel/expiry | test_media_foundation.py、RustFS abort/expiry、PG terminal races；状态和原因配对通过。 |
| No ready without whole-object verification → Every reachable status；Completion operation requires successful verification；No completion operation is exposed；Ready is bound to an immutable physical identity | media_transfer.py worker, hash/probe, _finalize_ready；migration CHECK | test_media_schema.py、RustFS successful/hash/size/probe/immutable version、PG transaction failures；ready 必须绑定 verified object。URL 前物理缺失检查是 W1，不代表 ready commit 可绕过 verifier。 |
| Existing intent replay precedes new intent state checks → Cancelled session returns original terminal pair；New key and conflicting key after cancellation；Replay cannot bypass current authorization | media.py 673–727 | test_cancelled_session_replays_original_intent_before_new_intent_checks、Edge 对应测试及撤权/过期凭据负向；SQLite/PG shared CI 通过。 |

### cloud-media-authorization（5 Requirements / 17 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Grant administration requires manager role and eligible grantee → Coach attempts to grant；Ineligible grantee；Repeatable grant write；Different manager cannot overwrite first grant audit | media_access.py、M2 grant routes media.py | test_media_authorization.py eligibility, repeated write, audit timestamp/actor；通过。 |
| Revoking one path preserves other paths → Session grant revoked, asset grant remains；Asset grant revoked, session grant remains；Creator path survives revocation；Repeat revocation；Different manager cannot overwrite first revocation audit | media_access.py grant OR predicate；grant routes | test_media_authorization.py path union, creator, repeat audit and revocation；固定 CI 通过。 |
| Transfer operations remain initiator scoped → Manager cannot take over another upload；Read-only coach requests transfer；Identity separation and source status | media_transfer.py _user_transfer / _edge_transfer；Edge auth dependency | test_media_authorization.py、test_media_edge_intent.py、test_media_transfer_storage.py role/source cases；共享/RustFS 通过。 |
| Current asset authorization governs access signing → Asset-only grant allows direct signing；Site membership alone and cross tenant access；Non-ready or missing physical object | media_access.py can_read_asset；media_transfer.py 986–1010 | test_media_authorization.py asset-only/site/cross-scope/non-ready tests通过。Missing DB reference is rejected. Missing physical version portion is W1：无精确 provider existence check；指定 RustFS 测试未运行。 |
| Signed access is short lived and explicitly revocable only for new issuance → Revocation blocks new URLs and preserves other paths；URL expiry Range and download disposition | media_transfer.py 1017–1064；storage.py 247–255 | RustFS Range/disposition/expiry 和已有 finite grant tests通过。V1 对 permanent grant + short AuthSession 失败，见 C1。 |

### cloud-media-transfer（14 Requirements / 34 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Private provider independent object storage → Object scope cannot be injected；Incomplete storage capability | storage.py protocol/S3 adapter；config/profile gates | adapter capability and scope tests；RustFS private bucket/profile tests通过。 |
| Transfer preparation is recoverable → Preparation response is lost；Existing intent exceeds transfer policy | media_transfer.py initialize job and legacy-policy path | test_media_transfer_storage.py initialization recovery；M2 legacy-size tests；PG duplicate prepare；通过。 |
| Bounded multipart layout and part credentials → Invalid part request；Bounded signing and expired identity | media_transfer.py 553–745 | User/Edge invalid number, batch, TTL, identity, size and RustFS actual part-size tests。V3 在配置 reload 后失败。 |
| Part confirmation uses provider evidence → Repeated confirmation；Claimed part does not exist | media_transfer.py 747–852 | shared API/provider cases + RustFS actual parts；PG independent concurrent confirmation；通过。 |
| Resume queries reconcile all parts → Network interruption and lost receipt；Provider part changed after confirmation | media_transfer.py 853–980 | RustFS full upload/resume/lost receipt and provider part mismatch；pagination/cursor shared API tests通过；V3 配置重载场景未覆盖。 |
| Complete accepts one immutable manifest → Accepted complete is asynchronous；Repeat complete during and after verification；Complete key conflicts with another manifest；Different key cannot create a second completion job；Incomplete or reordered manifest | media_transfer.py complete/idempotency/work queue；models.py unique constraints | shared API terminal/idempotency cases、PG duplicate-complete/concurrent workers、RustFS complete/recovery；通过。 |
| Whole object bytes determine verification → Matching object；False checksum or disguised media；Ambiguous storage completion | media_transfer.py worker assembly/hash/ffprobe | RustFS real matching upload, mismatch, disguised non-MP4, Complete-after-provider-success recovery；通过。 |
| Final verification commits both terminal states → Logout invalidates a pending completion without being blocked；Final transaction fails；Replaced or missing object | media_transfer.py 1542–1595 _finalize_ready | RustFS logout/session-expiry/role/Edge loss + DB failure/recovery and PG terminal races通过。V2 是 ready 后 URL issuance 检查，保持独立。 |
| Terminal races have one legal winner → Cancel or abort wins before final commit；Complete wins before later cancellation；Deadline is crossed during verification | media_transfer.py lock/CAS/terminal functions；media.py parent lock/cancel | PostgreSQL JUnit 证明 Cancel、Abort、Expiry 双向胜出；独立业务 backend 与 monitor 观察实际 Lock wait；通过。 |
| Crashed and duplicate workers recover safely → Crash after object assembly；Lease expires and old worker returns | media_transfer.py lease/generation/fencing | RustFS Complete-before-DB-record recovery；PG expired lease takeover and stale generation rejection；通过。 |
| Completion authority is current at publication → Authority is lost while bytes are verified；Earlier successful completion is immutable | media_transfer.py 1495–1538、_finalize_ready | RustFS original User AuthSession expiry/logout/role revocation and Edge credential/Device disabled cases；ready denied or prior success immutable；通过。 |
| Expiry and cleanup are retryable and scoped → Failed cleanup is visible；Late upload after abort | media_transfer.py 1783–1875 cleanup queue/authorization | RustFS expiry sweep/exact cleanup、late upload/error paths；PG cleanup/finalize；通过。 |
| Orphan collection cannot delete retained assets → Object is still referenced；Unknown inventory object | media_transfer.py 1783–2005 inventory/double observe/ref check | RustFS orphan discovery paginates, observes twice, preserves ready reference；PG GC-vs-finalize；通过。 |
| Transfer evidence uses real isolated backends → Concurrency evidence is genuine；Required storage integration is missing | scripts/test-postgresql.py、scripts/test-rustfs.py、CI workflow | PG artifacts prove independent PIDs and actual lock waits；RustFS artifact has pinned real container and 15 passes；collection and cleanup gates pass. V2/V3 are missing boundary cases, not missing the required storage service itself. |

### cloud-training-session（1 Requirement / 7 Scenarios）

| Requirement → 全部 Scenarios | 实际代码 | 自动测试 / 结果 |
| --- | --- | --- |
| Cancellation closes unfinished uploads → Cancel with in-flight upload intent；Repeat cancel is idempotent；Upload intent rejected after cancellation；Existing intent can be replayed after cancel；Replay does not bypass current identity or resource permission；Upload operations follow the parent-first lock order；Cancel races with verification final commit | media.py _lock_intent_session/lock_session_upload/cancel；media_transfer.py _lock_transfer、cancel_session_uploads、finalization | M2 cancellation/replay shared tests；M3 PostgreSQL 两种 lock winner（独立 backend/monitor）；SQLite state matrix；RustFS late Complete cancellation cleanup；通过。 |

**覆盖总结：** 六份 Delta 共 29 Requirements / 96 Scenarios。上表逐一列出全部 Scenario，并为每条要求给出实现入口、自动测试和结果。C1/V1、W1/V2、W2/V3 与 W3 是明确未通过或部分未证实的反例；Requirement 下其他通过用例不能抵消这些失败。

## M2 Verify W1–W4 独立复核

依据 [M2 verification.md](../archive/2026-11-14-implement-cloud-session-asset-foundation/verification.md) 和 M3 实际代码/测试：

| 原 Warning | 本次独立证据 | 结论 |
| --- | --- | --- |
| W1：取消后的既有意图重放顺序 | User test_cancelled_session_replays_original_intent_before_new_intent_checks；Edge test_edge_cancelled_session_replays_original_intent_before_device_state；当前授权仍在重放前校验 | 已由共享 API 测试确认。 |
| W2：同 SHA 独立采集身份 | User/Edge shared test 与 RustFS test_identical_bytes_from_two_devices_verify_as_distinct_assets | 已有真实传输与验证后身份独立证据。 |
| W3：授权审计首次主体/时间不被覆盖 | test_session_and_asset_grant_audit_fields_survive_other_managers 与 grant 持久字段断言 | 已确认。 |
| W4：采集时间原始值与时间基准往返 | test_raw_device_time_is_preserved_verbatim、test_valid_capture_time_bases_round_trip_through_asset_api | 已确认；服务端 received_at 与设备原始采集值分离。 |

此结论只表示 M2 Verify 的 W1–W4 已有本次代码和固定 CI 证据，不改变 M2 归档报告。

## 数据库、锁顺序、媒体完整性与清理判断

- **迁移/schema：** 0004 增量建立 media_objects、upload_parts、media_jobs、media_cleanup_candidates；升级后 19 表。六表初始迁移与 M2 0002/0003 未改。SQLite batch 与 PostgreSQL 失败事务、历史记录、CHECK/复合外键/RESTRICT、唯一性、逐步降级守卫在 migration/schema 测试覆盖。Apply 分支本身没有重写旧迁移。
- **锁：** _lock_transfer 先获取父 Session/Upload，再 Asset、Object；旧 Session cancel 由已锁 Session 后依序锁 Upload、Asset、Object；准备、确认、GET parts、complete、abort、expiry、finalize、cleanup 复用父优先次序。对象存储和 ffprobe 操作在 SQL 行锁外执行。PG artifact 的 monitor PID 观测了实际 Lock 等待与 blocker；Finalize 与 Cancel/Abort/Expiry 的双向合法胜负有两个不同业务 backend。未发现反向持锁的实证。
- **ready 和精确版本：** worker 完整读取对象计算 SHA/size，受限 ffprobe 验证类型；finalize 在短事务重查 lease/generation/identity、状态与时限，并原子写 Object verified、Upload completed、Asset ready/ref。RustFS 和故障注入覆盖对象合并后数据库记录前恢复、最终状态成对提交。未发现可绕过完整对象验证生成 ready 的证据。V2 是 ready 生成后 URL 签发时的物理对象丢失检查，不能与 finalize 前的真实完整性验证混为一谈。
- **身份与授权：** User/Edge 输入身份隔离、来源主体、Device/Node 状态以及 final commit 授权重查均有真实 RustFS 失效场景。发现 V1：访问 URL TTL 未始终受 AuthSession 剩余期限限制。现有撤权语义只阻止新 URL，不能撤回已发 bearer URL；既定有效期窗口仍为对象存储能力边界。
- **清理：** 代码按精确 object version/MPU、run scope、metadata 与完整引用核验，双次观察/宽限、tombstone/generation 和 ready ref 检查防止清理仍引用对象。RustFS 删除限固定隔离 CI 容器；证据有 run id、container id/name、image digest、bucket，结果 removed；没有生产 profile 或 Edge 原件删除。该结论仅适用于 CI 实证环境。
- **存储 profile：** RustFS 测试是私有隔离 bucket 的真实 S3-compatible I/O；并不代表生产存储选型、保留期限、监护人同意或生产删除政策获批。

## OpenSpec、契约与文档校验

- Change strict：openspec validate implement-cloud-media-upload-transfer --strict 通过；本报告加入后重新执行。
- 主规格 strict：openspec validate --specs --strict，5/5 通过；没有执行主规格同步。
- OpenAPI snapshot：43 paths / 57 operations，与 Apply 报告和 CI 快照测试一致；当前未发现实现/快照差异。
- git diff --check：Apply 基线相对 main 通过；加入本报告后重新执行。
- Markdown 相对链接/标题锚点：Apply 报告记载 279 条链接、0 断链；本报告加入后重新全检并单独记录结果。
- Tasks、原 Apply 报告、Proposal、Design、Spec Delta 均未因 Verify 被修改；只有本 verification.md 为新 Verify 产物。

## Archive 与后续最小修复要求

**Archive readiness：Not ready。** 当前有 1 个 CRITICAL、3 个 WARNING，且 V2 缺真实 RustFS 负向实证。42/42 是 Apply 的历史完成记录，不代替独立验收。PR #6 必须保持 Draft，直至项目负责人另行审阅并授权修复或其它后续阶段。

建议的最小 remediation 和复验：

1. 修复 C1 TTL 计算，不丢弃 auth deadline；补永久/有限/多条授权路径/撤销组合的 playback 与 download 测试，并在真实隔离存储验证时间到期行为。SQLite + PostgreSQL + RustFS 完整回归。
2. 为 W1 增加精确 version 的物理可用性核验；在 RustFS 中完成后删除版本，再请求 playback/download；断言 503、无 URL、ready 状态与历史引用不变，区分 not-found、权限和网络故障。
3. 修复 W2 对持久化 part layout 的续传校验；User 与 Edge 都需在 16 MiB→32 MiB 配置变化后申请末片 URL、上传/确认并继续完成，证明末片 size 使用原布局。
4. 追加 Apply 报告的最终 head/run/artifact 回链，不改写较早报告历史；再核对 10.3 追溯。
5. 对修复代码的新 head 重新运行完整 SQLite、PostgreSQL、RustFS 三个 CI job并校验 artifact head；重新运行严格和链接检查。完成后由负责人另行授权独立复验；本报告不执行 remediation。

**最终核验结论：** 固定 Apply Head 的主干实现和三类后端测试大部分有真实证据，M2 W1–W4 有独立确认；但 C1 已证明的 URL 授权期限越界构成合并阻断，W2 是可重现的续传回归，W1 缺少规格要求的真实负向证据且当前 signer 未检查物理版本。故当前不能 Archive，也不能把本 Change Verify 判为通过。PR #6 仍 Draft；未执行修复、Archive、主规格同步、PR Ready、Merge 或生产部署。
