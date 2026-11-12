# Cloud Session / Asset Foundation：Apply 实施与验证报告

- 日期：2026-11-12（Asia/Shanghai）
- Change：`implement-cloud-session-asset-foundation`
- 分支：`feat/cloud-session-asset-foundation`
- 实施 head：`8e7c7e8ce733ca2f3664c4a532b16fc2c30142a5`
- 批准基线：PR #5 审阅 head `d4b29efd756616fe6d6d5912599067ca0a79d2fd`（Proposal / Design / Spec Delta / Tasks）
- 依据：负责人 2026-11-12 正式 Apply 授权，执行 28 项任务中的实施与验证部分；Verify / Archive / 主规格同步 / Merge 均未执行。

## 1. 交付范围

| 面 | 实际交付 |
| --- | --- |
| 迁移 | 新 revision `20261112_0003`（`down_revision=20261110_0002`），创建 5 张表并扩展 `idempotency_records`；不改写 0001/0002 |
| 模型 | [models.py](../../services/cloud/src/swimplatform/models.py) 新增 `TrainingSession`/`VideoAsset`/`UploadSession`/`SessionReadGrant`/`AssetReadGrant`，`IdempotencyRecord` 改为按主体 |
| 授权 | [media_access.py](../../services/cloud/src/swimplatform/media_access.py) 统一 S-read / S-manage / A-read 谓词与游标工具 |
| 路由 | [media.py](../../services/cloud/src/swimplatform/media.py) 实现 12 paths / 16 operations，注册于 [main.py](../../services/cloud/src/swimplatform/main.py) |
| 契约 | OpenAPI 快照 33 paths / 47 operations；[媒体契约](../contracts/cloud-capture-media.md)、[RBAC 契约](../contracts/cloud-rbac.md)、[领域模型](../architecture/cloud-capture-media-domain.md) 更新 |
| 测试 | 新增 5 个测试文件；两后端批准表集合由 10 扩到 15 |

未交付（保持 M3 或后续 Change）：part-urls、complete、playback-url、分片与断点续传、整对象校验、`ready` 转换、对象存储与 MediaBlob、可重试过期清扫、孤儿对象清理、派生创建路径、Edge Runtime/离线同步、学员与教练—学员关系、RLS、生产部署。

## 2. 关键实现语义

| 要求 | 实现与证据 |
| --- | --- |
| 统一授权谓词（验收 1） | 三项能力由同一模块产出；`test_media_authorization.py::test_site_access_alone_is_not_resource_access` 等逐格验证 |
| 非管理路径逐请求校验 coach（P1-1） | 谓词读取当前 `tenant_memberships.role`；`test_downgrade_to_athlete_revokes_creator_and_grant_access` 证明降级后读取/PATCH/列表全部失效，且刻意保留 SiteMembership |
| cancelled 拒新意图、completed 允许补传（P1-2） | `_assert_intent_allowed` + `_session_for_intent`；`test_cancelled_session_rejects_intent_and_closes_unfinished_uploads`、`test_completed_session_accepts_make_up_upload_without_rollback` |
| 单事务三对象（验收 4） | `_create_intent` 内 Asset→UploadSession→IdempotencyRecord 后单次 `commit`；`test_intent_creates_asset_and_upload_session_together` 验证重放与冲突 |
| Edge 来源约束（验收 5） | 节点凭据 + 同租户/场馆 + 设备属该节点且 active；`test_media_edge_intent.py` 覆盖跨节点、停用、跨场馆 |
| 禁止裸 Asset / 虚假 ready（验收 6） | 无 Asset 创建路由；`test_no_completion_or_playback_operation_is_exposed`；库层 `ck_video_assets_ready_requires_verification` |
| grant 有效期/软撤销/首次审计/唯一性（验收 7） | `revoked_at`+`revoked_by_user_id` 成对约束、`expires_at` 判定、部分唯一索引；`test_only_one_active_grant_per_grantee`（库层）与 PG `test_concurrent_grant_writes_keep_one_active_row` |
| 先过滤后分页（验收 8） | 列表先套资源谓词再取页；`test_cursor_stays_filtered_after_revocation` + `invalid_cursor` 用例 |
| 原始时间字面值（验收 9） | `strip_whitespace=False`，`test_raw_device_time_is_preserved_verbatim`；`test_capture_metadata_rejects_inconsistent_basis` 覆盖基准矛盾 |
| M2 不做 ready/播放（验收 10） | 见「未交付」；`checksum_sha256` 在 M2 恒为空 |

## 3. 数据库与迁移

- 五张表全部使用复合唯一键 + 复合外键（一律 `RESTRICT`）+ CHECK：
  - `video_assets`：`ready` 必须同时具备 `checksum_sha256`/`received_at`/`size_bytes`/`media_type`；`failed` ⇔ `failure_reason` 非空；origin 与来源/创建者成对；派生父引用同租户/场馆/会话且禁止自引用。
  - `upload_sessions`：`asset_id` 唯一；发起主体用户/节点恰一；`expires_at > created_at`；终态与 `failure_reason` 配对；`completed` ⇔ `completed_at` 非空。
  - 两张 grant 表：`revoked_at` 与 `revoked_by_user_id` 成对；`expires_at > granted_at`；`UNIQUE (..., grantee_user_id) WHERE revoked_at IS NULL`。
  - `training_sessions`：状态与 `started_at`/`completed_at`/`cancelled_at` 组合约束。
- `idempotency_records`：新增 `actor_kind`（`NOT NULL DEFAULT 'user'` 回填）与 `edge_node_id`，`user_id` 改可空；主体配对 CHECK；`operation`/`resource_kind` 词表扩展；原唯一约束替换为 `uq_idempotency_user_scope_key` 与 `uq_idempotency_edge_scope_key` 两条部分唯一索引。
- SQLite 走整表重建（新表 → 复制 → 删旧 → 改名 → 建索引）；PostgreSQL 走 `drop/add` 约束与索引。两后端均验证 `head → 0002 → head` 往返且 User 主体幂等行与摘要不变。
- 降级守卫：五张新表任一条记录、或 `actor_kind='edge_node'`、或新 `operation`/`resource_kind` 记录存在时，`downgrade` 抛错并报告 `表名=计数`，不静默丢弃；纯 User 旧数据可正常降级。

## 4. 测试结果（绑定实施 head）

| 环境 | 命令 | 结果 |
| --- | --- | --- |
| 本机 SQLite | `python -m pytest -q --junitxml=var/tmp/sqlite-junit.xml` | **232 tests / 0 failures / 0 errors / 59 skipped**（skip 全为 `postgresql` 标记） |
| CI SQLite | 见第 6 节 | 待 CI 结果回填 |
| CI PostgreSQL 17 | 见第 6 节 | 待 CI 结果回填 |

本机无 Docker daemon，`scripts/test-postgresql.py` 无法启动专用实例，因此 PostgreSQL 专属用例（并发 PID、降级守卫、RESTRICT、部分唯一索引）只在 CI 执行；本机不声称这些场景通过。

回归口径：既有 19 个基础操作与 12 个 Registry 操作未改路径、字段与错误；`test_cloud_foundation.py` 仅把 head revision 断言更新为 `20261112_0003`，`test_edge_registry_schema.py`/`test_postgresql_schema.py`/`pg_support.py` 仅扩展批准表集合，Registry 幂等断言保持原样。

## 5. 与已批准设计的偏差（如实记录）

| 项 | 说明 |
| --- | --- |
| 响应模型命名 | 会话资源响应类实际命名为 `TrainingSessionRead`，因为 `SessionRead` 已是登录响应模型；字段与契约一致，仅组件名不同 |
| `capture_metadata` 字段 | 除设计表的字段外，额外接受可选的 `capture_started_at_utc` / `capture_ended_at_utc`（D21 已规定「只接受调用方显式提供」）；未解析原始字符串，也不推断 UTC |
| 派生父级校验 | 库层只保证同租户/场馆/会话与自引用禁止；`ready` 父级前置未实现（无派生创建路径），与 P1-3 一致 |
| 过期清扫 | 仅单资源读取/中止时懒物化；列表可能短暂显示过期未终结记录，清扫属 M3 |
| `expires_at` 参数 | 服务端常量 24 小时（上限 7 天常量），请求模型无 TTL 字段；调整参数需改代码，不改表结构 |

## 6. CI 证据

- 实施 head `8e7c7e8ce733ca2f3664c4a532b16fc2c30142a5`
- run 与 job 结果：待回填（本报告先随实施提交，CI 完成后追加）

## 7. 未验证与限制

- 本机未运行 PostgreSQL 用例；PG 结论只来自 CI。
- 未验证：真实对象存储、分片传输、整对象校验、播放 URL、真实学员数据、RLS、生产部署、浏览器端到端。
- M2 内资产可合法停留在 `pending_upload`，且不存在 `ready`；这不是缺陷，是阶段边界。
- 幂等记录不自动淘汰，容量与回收策略仍为后续门槛。
