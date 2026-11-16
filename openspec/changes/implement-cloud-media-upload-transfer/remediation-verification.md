# Independent OpenSpec Re-Verify — Cloud Media Transfer Remediation

- 核验日期：2026-11-16（Asia/Shanghai）
- Repository：TuIanL/zhiyong-swim-platform
- PR：[#6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6)，核验时保持 Draft
- Branch：`feat/cloud-media-upload-transfer`
- Change：`implement-cloud-media-upload-transfer`
- main 基线：`3352c6b17b2dd3b6921028b25606a999bb69b331`
- Remediation 业务代码 Head：`48d5df50aafefab9483eb178625efc9460cd7fe1`
- 当前 PR / 文档 Head：`3ed9b25a679299b340ed4b7f0c8eea67c0bee9a6`
- 原始 Apply Head：`ba2216b058ebcbf3b51d59fcd80d6f073ad36961`
- Apply Tasks：原记录保持 42/42；本报告不改写其历史。

## 结论

| 类别 | 数量 | 结论 |
| --- | ---: | --- |
| CRITICAL | 0 | 首轮 C1 已由实现和实际存储测试关闭。 |
| WARNING | 0 | 首轮 W1、W2、W3 均已关闭。 |
| SUGGESTION | 3 | 保留 SQLite 弃用警告、GitHub Actions Node.js 20 弃用提示；补充签名 URL 到期时间精度建议。 |

**独立复核结论：Ready for archive（附 3 项建议）。** 本报告只作 Verify，不执行 Archive、主规格同步、PR Ready、Merge 或生产部署。生产存储厂商、区域、隐私同意、保留、备份与删除政策仍未冻结。

## 固定基线与证据来源

PR 元数据确认 PR #6 open、Draft、base 为 main，head 为 `3ed9b25a679299b340ed4b7f0c8eea67c0bee9a6`。本地 Git 中 `origin/main` 仍为批准基线。`48d5df5..3ed9b25` 的唯一文件差异是 `docs/verification/cloud-media-upload-transfer-remediation.md`；没有业务代码差异。故 48d5 是被复核的修复代码 Head，3ed9 是当前 PR 文档 Head。

原始 [首次 Verify 报告](verification.md) 与 [Apply 报告](../../../docs/verification/cloud-media-upload-transfer-apply.md) 均保留。Apply Run `43606071954` 仅作为原始 Apply 证据，不作为 Remediation 回归证据。

### 固定 Remediation CI

| Run / Head | Job | 原始结果 | 独立核对 |
| --- | --- | --- | --- |
| [43669491942](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43669491942) / `48d5df5` | SQLite | 210 passed / 92 skipped / 0 failed | Job 成功。 |
| 同上 | PostgreSQL 17 | 281 passed / 21 skipped / 0 failed | 独立 PG artifact metadata 绑定 `48d5df5`；PG 17.11，清理 removed。 |
| 同上 | 隔离 RustFS | 16 passed / 0 skipped / 0 failed | 独立 RustFS artifact metadata 绑定 `48d5df5`；清理 removed。 |
| [43670023324](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43670023324) / `3ed9b25` | SQLite | 210 passed / 92 skipped / 0 failed | 原始 Job log 与 JUnit 一致。 |
| 同上 | PostgreSQL 17 | 281 passed / 21 skipped / 0 failed | ledger `shared=205, postgresql=76`；清理 removed，run-file 兜底 absent / exit 0。 |
| 同上 | 隔离 RustFS | 16 passed / 0 skipped / 0 failed | 固定 `ffprobe 6.1.1`；精确容器清理 removed。 |

Run `43670023324` 的 workflow metadata、三个 Job、原始日志及 artifact 均绑定 `3ed9b25a679299b340ed4b7f0c8eea67c0bee9a6`。PostgreSQL artifact：[14143991749](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43670023324/artifacts/14143991749)；RustFS artifact：[14143906955](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43670023324/artifacts/14143906955)。Run `43669491942` 的 PG / RustFS evidence artifacts 分别为 [14144090462](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43669491942/artifacts/14144090462) 和 [14143622228](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43669491942/artifacts/14143622228)。

Run 43670023324 的 PG JUnit 为 302 项：281 passed、21 skipped、0 failed；skip 是 5 个 SQLite 专属场景和在独立 RustFS Job 中执行的 16 个对象存储场景。SQLite 的 92 个 skip 对应 PostgreSQL 专属及独立 RustFS 标记；两类必测场景分别在其专属 Job 实际运行。CI 原始日志显示 RustFS Job 安装并检查 `ffprobe 6.1.1`，不是只运行测试发现或 mock。

本机 `ffprobe` 为 8.1.2，不满足项目固定 6.1.1 门禁；Remediation 记录的本机 RustFS 结果为 6 passed / 10 failed，失败发生在 worker 媒体探测门禁处。本机失败没有被计作通过，也未放宽版本门禁。固定版隔离 CI 可重复建立，并在两个固定 Head 上分别执行了完整 16 场景，全部通过。

## Findings 关闭复核

| Finding | 本轮状态 | 主要实现证据 | 独立测试与结果 |
| --- | --- | --- | --- |
| C1：访问 URL 越过登录身份期限 | **Closed** | `media_transfer.py:999–1080,1084–1142` | `test_media_access_url_remediation.py` 中永久 Grant / 短 AuthSession、有限 Grant、OR 授权、创建者与管理者、过期身份场景均在完整 CI 中通过；真实 RustFS 验证 SigV4 URL 到期后对象读取被拒。 |
| W1：Ready 记录未确认精确物理对象版本 | **Closed** | `media_transfer.py:1084–1117`；`storage.py:231–238` | 精确版本删除后真实 RustFS playback 与 download 均 503、无 URL、ready 历史和对象引用不变；对象不存在、权限错误、网络错误和版本/大小/元数据不匹配测试通过。 |
| W2：重载配置会破坏已冻结分片布局 | **Closed** | `media_transfer.py:286–312`；User / Edge 调用共享布局解析 | `test_rustfs_user_and_edge_resume_original_layout_after_config_reload` 在固定 RustFS Job 通过，完整恢复、确认、ListParts、Complete、SHA/大小校验及 Ready 均覆盖；User 与 Edge 各自执行。 |
| W3：Apply 报告未回链最终 Apply 证据 | **Closed** | Apply 报告第 7 节 | 最终 Apply Head `ba2216b`、Run `43606071954`、三 Job 结果和原 Apply artifact 已追加；早期记录未覆盖，并明确 Apply 全绿不等于独立 Verify 通过。 |

### C1 — 身份与授权期限

`_access_snapshot()` 始终把 `AuthSession.expires_at` 放入截止时间集合。永久 Grant 不增加 Grant 自身期限，但不会删除身份期限；有效 Grant 按 OR 语义选择最长有效授权路径，撤销和过期 Grant 在查询阶段排除。创建者、Owner、Admin 路径也仍受登录身份上限约束。TTL 受配置值、配置硬上限、300 秒和有效截止时间共同约束；不足一个整数秒时拒绝签发。远程 HEAD 前后均重新检查身份、权限和对象引用，签名后再验证绝对截止时间，必要时最多缩短重试一次；播放与下载共用 `_issue_access_url()`。

测试证据包括 `test_permanent_grant_never_outlives_short_auth_session`、`test_finite_grant_caps_long_auth_deadline`、`test_or_grants_choose_longest_active_path_and_ignore_revoked_path`、`test_creator_and_manager_paths_remain_capped_by_identity`、`test_expired_auth_is_rejected_before_head_or_sign`。固定 RustFS 测试解析真实 SigV4 的 `X-Amz-Date` 与 `X-Amz-Expires`，核实 API 截止时间不越权，并在 URL 到期后验证存储端拒绝新的对象读取请求。V1 的身份期限缺陷关闭。

### W1 — 精确对象版本可用性

授权快照先取得已验证的 `object_key/object_version` 和预期大小。数据库事务结束后才执行有界的 `HEAD(key, version_id)`；检查返回版本、大小及 owner、purpose、Tenant、Site、Session、Asset、UploadSession 元数据。随后再次检查身份、权限和数据库中的精确对象引用，任何失败均不返回 URL。不存在精确版本映射为 `503 media_unavailable`；权限和网络故障映射为带可诊断 provider 错误码的 `503 storage_unavailable`；不回退到同 key 最新版本，也不改写已提交的 ready 历史。

真实 RustFS 用例先创建并验证 Ready 视频，再只删除该对象的精确版本，分别调用 playback 和 download。两者都返回 503 且响应无可用 URL；Asset 仍为 ready，`storage_object_ref/object_key/object_version/verified` 历史保持不变。`test_missing_exact_object_version_returns_unavailable_without_mutating_ready_history`、`test_head_permission_and_network_failures_are_diagnostic_server_errors` 与 `test_head_must_match_exact_version_size_and_identity` 通过。HEAD 与稍后的 GET 仍有 TOCTOU 窗口；对象可能在 HEAD 后、URL 使用前被删除，HEAD 不构成整个 URL 生命周期的可用性保证。

### W2 — 冻结分片布局

`_resolve_part_layout()` 仅在还没有物理上传对象、尚未持久化布局时读取当前 `media_part_size_bytes`。已有对象必须从 `UploadSession.part_size_bytes/part_count` 恢复，并验证完整性和数量关系；物理对象已存在但布局字段缺失时 fail closed。User 与 Edge 路径共享该决策，末片大小由已保存布局计算。

真实 RustFS 场景以 40 MiB 文件、16 MiB 分片保存三片布局并初始化 multipart；配置重载到 32 MiB 后仍可为第 3 片签发 8 MiB 的原布局大小，之后继续 PUT、Confirm、ListParts、Complete 和 worker 校验。User 与 Edge 各走完整链路，最终 SHA-256、`verified_size_bytes` 及 `Asset.ready` 均符合原始布局。另有 `test_existing_physical_upload_without_layout_is_rejected` 验证缺布局时拒绝重建。

### W3 — Apply 证据链

[Apply 报告](../../../docs/verification/cloud-media-upload-transfer-apply.md) 的第 7 节保留早期 Apply Head、CI 和失败修复轨迹，并追加最终 Apply Head `ba2216b058ebcbf3b51d59fcd80d6f073ad36961`、Run `43606071954`、SQLite 210/92、PostgreSQL 281/21、RustFS 16/16，以及 PG/RustFS artifact 回链。该段明确指出 Apply CI 全绿不代表独立 Verify 已通过。Remediation 的新测试结果只归属于 48d5 / 3ed9 对应的后续 CI，没有回填成原 Apply 测试。

## Requirement / Scenario 双向追溯

复读 Proposal、Design、42 项 Tasks、6 份 Delta、首次 `verification.md` 的逐 Scenario 矩阵、Remediation 记录、运行代码、定向测试和两个最新 CI 的原始结果。六份 Spec Delta 的追溯规模与首次报告一致：

| Spec Delta | Requirements | Scenarios | 本轮结论 |
| --- | ---: | ---: | --- |
| cloud-edge-registry | 1 | 2 | 与原矩阵、代码和全量回归一致；未发现本次修复引入回归。 |
| cloud-identity | 2 | 15 | 与原矩阵、代码和全量回归一致；未发现本次修复引入回归。 |
| cloud-media-asset | 6 | 21 | 与原矩阵、代码和全量回归一致；未发现本次修复引入回归。 |
| cloud-media-authorization | 5 | 17 | C1/W1 已按对应边界重新实测；其余场景沿用首次 Verify 的具体映射并由全量 CI 回归。 |
| cloud-media-transfer | 14 | 34 | W2 已通过真实 User/Edge RustFS 续传实测；其余场景沿用首次 Verify 的具体映射并由全量 CI 回归。 |
| cloud-training-session | 1 | 7 | Session 取消与传输终态的既有映射由原 PostgreSQL/RustFS 并发证据和本轮全量回归覆盖。 |
| **合计** | **29** | **96** | 29/29 Requirements、96/96 Scenarios 均保留实现/测试/结果回链；本轮直接重跑了完整 SQLite、PostgreSQL、RustFS Job，未将仅有文档声明的场景当作新实测。 |

42 项 Apply Tasks 在原报告中均有交付位置。本轮没有改动 `tasks.md` 或规格来弱化要求；原来因 C1、W1、W2、W3 受影响的验收证据现分别由实际签名期限测试、精确版本 RustFS 负向测试、完整 User/Edge 配置重载续传、Apply 文档回链闭合。

### M2 W1–W4

按首次 Verify 所列的原 M2 审计项和测试重新核对，并检查固定 Remediation CI 的完整回归：

| M2 finding | 当前独立证据 | 结论 |
| --- | --- | --- |
| W1：取消后的既有意图重放顺序 | User/Edge cancelled-session replay 用例；当前身份和资源权限仍在重放前校验。 | 确认，无本轮回归。 |
| W2：相同 SHA 的独立采集身份 | 两设备来源分别保留的 RustFS 集成测试 `test_identical_bytes_from_two_devices_verify_as_distinct_assets`。 | 确认，无本轮回归。 |
| W3：授权审计首次主体/时间不被覆盖 | `test_session_and_asset_grant_audit_fields_survive_other_managers` 与完整 PG/SQLite 回归。 | 确认，无本轮回归。 |
| W4：采集时间原始值和时间基准往返 | `test_raw_device_time_is_preserved_verbatim`、`test_valid_capture_time_bases_round_trip_through_asset_api` 与完整 PG/SQLite 回归。 | 确认，无本轮回归。 |

此处是 M3 代码与本轮固定 CI 对 M2 证据的复核，不修改 M2 已归档报告。

## 其余系统约束与新增回归检查

- **数据库与并发：** 首次 Verify 的 PostgreSQL artifact 保留真实独立业务 backend PID 和 monitor PID；`pg_stat_activity.wait_event_type=Lock`、`wait_event=transactionid`、`pg_blocking_pids()` 指向 blocker。Cancel/Abort/Expiry 与 Finalize 双向胜负、状态提交及 CAS/行锁证据由原 M3 CI 测试覆盖；本轮两个后端完整回归未见失败。0004 增量迁移、19 张表、历史迁移保留、约束和安全 downgrade 仍由原映射及本轮全量迁移套件验证。
- **完整对象与终态：** RustFS 16 场景重新通过；对原上传、断点恢复、分片确认、Complete、全对象 SHA-256、大小、ffprobe 和 ready 原子提交进行全套回归。worker 失败/租约恢复和对象引用保护的专项映射保留在首次 Verify 报告及 Apply 报告中，本轮 CI 没有以 mock 替代 RustFS 集成。
- **权限和清理：** User/Edge 身份隔离、资源级权限、授权最终复核、已签 URL 的有限复用窗口、取消/过期清理及 ready 引用保护均有首次逐场景矩阵和固定 CI 回归。RustFS 与 PG harness 的本轮资源都按 run id 和精确归属清理；没有配置生产 endpoint，也没有删除 Edge 原始视频或 ready 对象以外资源。
- **OpenAPI 与静态检查：** OpenAPI 运行时快照一致，43 paths / 57 operations；OpenSpec Change strict 通过，主规格 strict 5/5。`git diff --check 48d5df5..3ed9b25` 通过；业务代码 Head 与文档 Head 之间没有未重新测试的业务变更。

## 保留建议

### S1 — SQLite datetime adapter 弃用

Run `43670023324` 的 SQLite 原始日志仍出现 Python 3.12 起默认 datetime adapter 弃用提示。当前不影响测试结果或数据一致性；后续可显式注册适配器并验证 UTC 往返。

### S2 — GitHub Actions Node.js 20 弃用提示

工作流依赖仍触发 Node.js 20 runtime 弃用提示。当前 Job 成功，不影响本轮验收；后续升级 Actions 版本并通过完整工作流验证。

### S3 — API `expires_at` 与 SigV4 整秒边界的精度

代码在签名后用高精度服务端时间加 TTL 填充 API `expires_at`，而 SigV4 `X-Amz-Date` 按整秒编码。独立用当前 boto3 signer 样例计算，`X-Amz-Expires=12` 的存储端截止比 API `expires_at` 早 0.986433 秒。此差异仍早于身份/授权截止，没有复现越权；真实 RustFS 已验证到期后拒绝读取，但现有断言验证上界而非三种时间值的精确一致。建议后续让 StorageProvider 返回有效签名截止，或在契约和测试中明确整秒舍入容差，并断言 `API expires_at` 不晚于实际签名 URL 截止。

## OpenSpec 及停止状态

- Change strict：通过；当前唯一活跃 Change 为 `implement-cloud-media-upload-transfer`，42/42 历史任务不变。
- 主规格 strict：5/5 通过；本轮未改主规格。
- 当前 PR #6 仍为 Draft，main 未变。
- 本报告是唯一由本轮新增的工作区文件；没有执行 Archive、主规格同步、PR Ready、Merge 或生产部署。

**最终判定：** C1、W1、W2、W3 全部 Closed；CRITICAL 0 / WARNING 0 / SUGGESTION 3。Change 满足进入 Archive 阶段的工程前置条件，但本轮未执行 Archive；等待项目负责人审阅并另行授权。
