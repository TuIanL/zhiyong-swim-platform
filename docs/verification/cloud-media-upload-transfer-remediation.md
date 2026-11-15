# Cloud Media Transfer：Verify 后定向修复记录

- 修复日期：2026-11-15（Asia/Shanghai）
- Repository：`TuIanL/zhiyong-swim-platform`
- PR：[#6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6)，保持 Draft
- OpenSpec Change：`implement-cloud-media-upload-transfer`
- 修复开始时 Verify 文档 Head：`0b65c2392078be01604a16829e5f0cc7a8a49e95`
- 独立 Verify 固定业务代码 Head：`ba2216b058ebcbf3b51d59fcd80d6f073ad36961`
- main 基线：`3352c6b17b2dd3b6921028b25606a999bb69b331`，未改动
- OpenSpec Apply 历史：42/42，`tasks.md` 未修改

本记录只处理独立 Verify 的 C1、W1、W2、W3。原 `verification.md` 保留首次 Verify 结论；不把原 Apply CI 视为 Verify 通过。无生产存储、规格、OpenAPI、主规格、任务历史或业务范围变更。

## Finding → 修复 → 回归

| Finding | 修复位置与行为 | 新增/修改测试 | 实际结果 |
| --- | --- | --- | --- |
| C1：永久 Grant 清除 AuthSession URL 期限 | `services/cloud/src/swimplatform/media_transfer.py`：授权期限集合始终包含登录会话截止；创建者/Owner/Admin 没有额外 Grant 截止；Coach 的多个有效 Grant 按 OR 语义取可用期限最长路径，但永不越过登录截止。签名后再用服务端时钟检查，必要时在有界重试中缩短 TTL；不足 1 秒拒绝。播放/下载共用 `_issue_access_url()`。 | `test_permanent_grant_never_outlives_short_auth_session`；`test_finite_grant_caps_long_auth_deadline`；`test_or_grants_choose_longest_active_path_and_ignore_revoked_path`；`test_creator_and_manager_paths_remain_capped_by_identity`；`test_expired_auth_is_rejected_before_head_or_sign`；真实 RustFS 用例中的实际 SigV4 `X-Amz-Expires` 与到期后 API 拒绝。 | SQLite/PG 共享测试通过；真实固定版 ffprobe RustFS CI 待最终 Run。 |
| W1：Ready 仅凭 DB 状态签 URL，未确认精确物理版本 | `media_transfer.py`：先完成资源授权和对象引用快照，回滚读事务后才执行 `HEAD(object_key, object_version)`；验证返回版本、大小及 owner/purpose/Tenant/Site/Session/Asset/Upload 元数据；再重新核验权限、身份与精确 DB 引用后签名。缺失版本返回 503 `media_unavailable`；权限/网络/provider 错误返回带 provider 错误码的 503 `storage_unavailable`。错误也先重新核验当前授权，避免并发撤权后暴露存储信息。不修改 ready 历史。`storage.py` 原有 S3 HEAD 使用有界 SDK timeout/retry。 | `test_missing_exact_object_version_returns_unavailable_without_mutating_ready_history`；`test_head_permission_and_network_failures_are_diagnostic_server_errors`；`test_head_must_match_exact_version_size_and_identity`；真实 RustFS 删除精确 Ready 版本后分别请求播放和下载 URL，并核对 DB 历史不变。 | SQLite/PG 共享测试通过；真实 RustFS CI 待最终 Run。HEAD 与稍后的 GET 之间仍有固有 TOCTOU 窗口；HEAD 不保证签名 URL 整个有效期内对象不会被外部删除。 |
| W2：当前配置重算既有 multipart part count | `media_transfer.py` 新增共享 `_resolve_part_layout()`，User 与 Edge 首次创建物理上传时才读取当前配置；既有物理对象以持久化 `UploadSession.part_size_bytes/part_count` 为准，校验布局完整性和数量一致性。已有物理对象缺字段、或布局与物理对象不一致时返回 409 `state_conflict`，不重建。 | `test_frozen_layout_survives_reconfiguration_for_user_and_edge`；`test_existing_physical_upload_without_layout_is_rejected`；真实 RustFS `test_rustfs_user_and_edge_resume_original_layout_after_config_reload`：40 MiB、16 MiB×3、配置重载至 32 MiB，恢复第 3 片为 8 MiB，PUT/确认/ListParts/Complete/全对象 SHA 与 Ready。 | SQLite/PG API 回归通过；RustFS 环境完成真实 40 MiB 分片上传、确认和列表，但本机 worker 无法通过固定版 ffprobe 门禁；完整 ready/SHA 结果以固定 ffprobe CI 为验收依据。 |
| W3：Apply 报告未回链最终 Apply head/CI/artifacts | 仅在 `docs/verification/cloud-media-upload-transfer-apply.md` 末尾追加第 7 节，保留旧 head/run/失败轨迹；明确 Apply Head `ba2216b…`、Run `43606071954`、三个 Job 数量及 PostgreSQL artifact `14118535563`、RustFS artifact `14117424479`；指出原 Apply CI 全绿不代表独立 Verify 通过。 | 文档与固定 Verify 报告、Apply CI artifacts 元数据对照。 | 历史原文保留，最终 Apply 证据链已补齐。 |

为使本机 Docker 29.8 返回的小写 `no such object/container` 被准确识别为已删除对象，`scripts/test-rustfs.py::inspect_exact()` 将这两个明确的不存在消息改为大小写不敏感匹配。其他 Docker 错误仍为 HarnessError，容器 ID、名称、镜像和所有权标签校验未放宽。本机本轮 RustFS harness 对本次容器的最终清理结果为 `removed`。

## 回归证据

### 本地环境

| 环境 | 结果 | 备注 |
| --- | --- | --- |
| SQLite 全量 | **210 passed / 92 skipped / 0 failed**；203 warnings | 仓库 `.venv` Python 3.13；skip 为 PostgreSQL 专属及独立 RustFS 标记；warnings 为 SQLite datetime adapter 与 Starlette/AnyIO 弃用。初次系统 Python 运行因独立安装检查缺少包失败，不计为通过；仓库安装环境的最终全量结果如左。 |
| PostgreSQL 17 全量 | **281 passed / 21 skipped / 0 failed**；收集 ledger `shared=205`、`postgresql=76` | `scripts/test-postgresql.py`；PG 17.11 Debian 17.11-1.pgdg13+2，linux/arm64；Harness `run_id=a6ae1d1d09f48ba1`；`result=passed`、exit 0、精确容器 cleanup=`removed`。21 skip 为 SQLite 专属与独立 RustFS 标记；76 个 PG 专属场景必需 ledger 全部通过。 |
| RustFS 隔离存储 | **本机 profile 未能完整通过 worker 完成阶段** | 固定 RustFS 1.0.5 linux/amd64、固定镜像 digest；本机 `ffprobe` 为 8.1.2，而应用只接受 6.1.1。Junit 16 个测试中 6 passed / 10 failed；失败路径在 worker 的媒体探测前置门禁后保持 `completing`，未将其冒充为媒体验证通过。W2 User 路径已完成精确 40 MiB/3 片 PUT、确认和 ListParts；完整 Finalize/SHA/Ready 与短 TTL 到期由同一最终代码 Head 的固定版 RustFS CI 作为必要门槛。Harness cleanup=`removed`。 |

固定 ffprobe 环境（CI Ubuntu 24.04、ffmpeg/ffprobe 6.1.1）的最终 RustFS Run 与对应 artifacts 尚待 push 后回填。不得用历史 Apply Run 代替本轮结果。

### 静态与契约检查

- OpenSpec Change strict：通过，1/1。
- 主规格 strict：通过，5/5；未修改主规格。
- OpenAPI 运行时快照：通过，43 paths / 57 operations。
- `git diff --check`、Python compile：待最终提交前复跑。
- Markdown 相对链接和标题锚点：待包含本记录的最终文档检查。

## 历史与范围

- `openspec/changes/implement-cloud-media-upload-transfer/verification.md` 保留原独立审计结论，不被本记录覆盖。
- `openspec/changes/implement-cloud-media-upload-transfer/tasks.md` 保持原 42/42 Apply，不计本轮修复为新 Apply 任务。
- S1（SQLite datetime adapter）与 S2（GitHub Actions Node.js 升级）保留为后续维护项。
- 最终修复代码 Head、最终 CI Run/artifacts、SQLite/RustFS 计数、PR/Notion 同步结果将在全部后端对最新 Head 完成后补记。
