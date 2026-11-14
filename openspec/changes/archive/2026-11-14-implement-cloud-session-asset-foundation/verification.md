# 独立 OpenSpec Verify：Cloud Session / Asset Foundation

| 项目 | 核验值 |
| --- | --- |
| Repository / PR | `TuIanL/zhiyong-swim-platform` / Draft PR #5 |
| 固定代码 Head | `650425db9838425175620fc54abb347c7b5f8657` |
| OpenSpec Change | `implement-cloud-session-asset-foundation` |
| Apply 任务记录 | 28/28（本报告不修改历史任务状态） |
| 核验日期 | 2026-11-14 |

本报告是对固定代码 Head 的独立核验。PR 后续新增的报告提交只增加本文件，不改变本次核验的代码对象。报告结论不授权 Archive、主规格同步、PR Ready 或 Merge。

## 结论摘要

- **CRITICAL：0**
- **WARNING：4**
- **SUGGESTION：1**
- OpenSpec Change strict：通过（1/1）；主规格 strict：通过（2/2）。
- 固定 Head 的 CI 全部通过：SQLite `179 passed / 64 skipped`；PostgreSQL 17 `240 passed / 3 skipped`；失败 0。
- CI 确认检出的代码 SHA 与固定 Head 相同。PostgreSQL 测试容器清理结果为 `removed`，兜底检查确认 `absent`、exit 0。
- 五张新增表、幂等表扩展、主要权限谓词、受控取消/创建并发、终态配对、迁移回滚与 M2/M3 边界均有代码和 CI 证据。
- 28 项 Apply 均能映射到交付物；但任务 2.8、2.9 的特定验收断言不完整，另有两个规格场景缺少明确回归测试，详见 WARNING。

**最终判断：没有发现 CRITICAL 或当前合并阻断问题；按 OpenSpec Verify 口径可进入 Archive（带已记录改进项）。需要对 4 项 WARNING 作定向补证或明确接受后再冻结 M3 设计；其中 WARNING-1 的取消后幂等重试语义建议在 M3 依赖它之前解决。**

## 核验范围与方法

核验读取了该 Change 的 Proposal、Design、Tasks、四份 Spec Delta、Apply 报告与 remediation 记录；对照固定 Head 下的模型、迁移、服务路由、授权谓词、Schema、测试、OpenAPI 快照及正式领域/API/RBAC 文档。CI 原始 job 日志确认 checkout SHA；没有以历史测试结果替代本轮 CI。

OpenSpec 当前 Change 含 25 项需求（23 ADDED、2 MODIFIED）、79 个场景；任务跟踪为 28/28。`openspec validate implement-cloud-session-asset-foundation --strict` 通过，`openspec validate --specs --strict` 检查主规格 2/2 通过。运行时 OpenAPI 与快照逐项一致：33 paths / 47 operations。完整 SQLite 与 PostgreSQL 17 测试由绑定固定 Head 的 CI 执行。

### 28 项 Apply 追溯

下表核对每项任务对应的代码/文档和实际验证类别。所有任务均存在可检查的实现或文档交付并被固定 Head 的 CI 覆盖；“部分补证”表示该任务文字中的一项具体验收断言缺少直接回归断言，不表示已发现实现错误。

| 任务 | 交付证据 | 独立核对 |
| --- | --- | --- |
| 1.1 | `models.py`、迁移 `20261112_0003_cloud_session_asset.py`；`test_media_schema.py`、`test_postgresql_schema.py` | 五表字段、复合约束、CHECK、索引、两后端反射 |
| 1.2 | 0003 幂等扩展；`test_media_migration_guards.py`、`test_postgresql_media.py` | 主体列、历史行/摘要保护、部分唯一索引与升级往返 |
| 1.3 | 0003 downgrade guard；migration guard / PostgreSQL media tests | 三类新记录阻止不安全降级，纯历史 User 数据可降级 |
| 1.4 | `tests/pg_support.py` 的批准表清单；`test_postgresql_identity.py`、`test_postgresql_schema.py` | 15 张业务表最小授权、未授权表拒绝及 schema 集合 |
| 1.5 | `test_media_schema.py`、`test_media_migration_guards.py` | Site/历史资源 RESTRICT、SQLite 与 PostgreSQL 中断迁移回滚 |
| 2.1 | `media_access.py`；`test_media_authorization.py` | S-read / S-manage / A-read、角色和机构/场馆范围；Coach 降级即时失权 |
| 2.2 | `media.py`；`test_media_foundation.py` | Session 创建、服务端归属、跨范围与客户端自报字段拒绝 |
| 2.3 | `media.py`；`test_media_foundation.py` | Session 状态迁移、时间组合与终态边界 |
| 2.4 | `media.py`；`test_media_foundation.py`、`test_postgresql_media.py` | 取消原子收口和 Cancel/CreateIntent 两种受控顺序 |
| 2.5 | `_create_intent()`；`test_media_foundation.py` | Asset、UploadSession、IdempotencyRecord 同事务；三表失败注入回滚；completed 补传 |
| 2.6 | Edge 意图路由；`test_media_edge_intent.py` | 凭据身份、来源设备归属、跨场馆/节点/停用设备拒绝 |
| 2.7 | 读取/中止/过期逻辑；`test_media_foundation.py`、`test_postgresql_media.py` | 服务端 TTL、懒过期、双对象终态配对和 Abort/Expiry 先后顺序 |
| 2.8 | `_upsert_grant()`、`_revoke_grant()`；`test_media_authorization.py`、`test_media_schema.py` | 软撤销、有效授权唯一性及访问路径；**grant 审计主体/时间保持断言部分补证，见 WARNING-3** |
| 2.9 | `schemas.py`；`test_media_foundation.py` | 原始采集时间空白往返和非法基准组合；**UTC 与 IANA 时区有效组合缺少正向 API 断言，见 WARNING-4** |
| 2.10 | `media_access.py` 游标编码/过滤；`test_media_authorization.py` | 先按当前授权过滤再分页、撤权后续页、跨筛选游标拒绝 |
| 2.11 | 路由错误检查次序；`test_media_authorization.py`、`test_media_foundation.py` | 401/404/403/422 和不泄露资源字段的关键路径 |
| 3.1 | `openapi.json`、运行时 `openapi()` | 33 paths / 47 operations 快照精确一致 |
| 3.2 | `docs/architecture/cloud-capture-media-domain.md` | 五表实现状态、意图与传输边界对照迁移/路由 |
| 3.3 | `docs/contracts/cloud-capture-media.md` | 已实现 16 个操作与 M3 未实现操作的边界对照 OpenAPI |
| 3.4 | `docs/contracts/cloud-rbac.md` | S-read / S-manage / A-read 与当前 Coach、场馆/资源授权边界 |
| 3.5 | Change Design、Apply 报告和 remediation 记录 | M2/M3 限制、Apply 后修订与本轮修复证据可追溯 |
| 4.1 | `test_postgresql_media.py`、`test_postgresql_transactions.py` | 独立 backend PID、并发连接与受控真实锁等待 |
| 4.2 | `test_media_schema.py`、`test_postgresql_media.py` | 部分唯一索引、跨范围引用和 RESTRICT 真实写入验证 |
| 4.3 | `test_postgresql_schema.py`、migration tests | 15 表反射、head→0002→head 及受控失败回滚 |
| 5.1 | Actions run `43531540007` | 固定 Head 的完整 SQLite 与 PostgreSQL 17 套件均成功 |
| 5.2 | `docs/verification/cloud-session-asset-foundation-apply.md` 与 remediation 记录 | 历史 Apply 结果未冒充本轮；M2 限制和迁移风险有记录 |
| 5.3 | Notion 工程入口历史记录 | Apply 阶段任务回链与状态历史存在；本轮 Verify 记录另行追加 |
| 5.4 | PR #5 与 Actions 元数据 | PR 保持 Draft；最终 CI checkout SHA 等于固定核验 Head |

### 重点技术核验

#### 数据库、迁移与权限

- `models.py` 与 0003 迁移包含五张新表、复合外键和唯一键、CHECK、部分唯一索引；新增业务外键使用 RESTRICT。`checksum_sha256` 没有全局唯一约束，因此相同内容可由不同逻辑资产表示。
- SQLite 幂等表采用 batch 重建，PostgreSQL 原生约束/索引迁移；中断迁移测试确认失败时版本不推进且旧结构/数据保留，修复冲突后可继续升级。原始 0001/0002 迁移受 SHA-256 守护，未被本 Change 改写。
- downgrade guard 对 Edge 主体及新 operation/resource_kind 记录拒绝破坏性降级。
- PostgreSQL 应用角色使用显式 15 表清单；版本表、schema usage、未授权 canary 和 DDL/TRUNCATE/SET ROLE 边界由 schema/identity 测试覆盖。
- `test_media_migration_guards.py` 在同一 SQLite Alembic 连接中，于显式迁移事务开始前、事务内和迁移完成后检查 `PRAGMA foreign_keys=1`；事务内实际外键违规写入被拒绝。未发现“迁移期间外键关闭”的问题。

#### 授权、状态机和事务

- `media_access.py` 用同一组资源谓词为列表、详情、子列表和续页授权；非管理路径逐请求校验当前 Coach 角色、场馆访问与资源创建者/grant。Coach 降为 Athlete 且保留 SiteMembership 时，Session、Asset、PATCH 均拒绝，代码和测试一致。
- Session 取消和上传意图创建通过父 Session 的 scoped 行锁串行化。用户端先做无锁能力预检，随后按 tenant/site/session 获取锁并在锁后重查授权与状态；Asset、UploadSession 与幂等记录一次事务提交。PostgreSQL 中 ControlledRace 使用第三条独立监控连接读取 `pg_stat_activity.wait_event_type`、`wait_event` 与 `pg_blocking_pids(pid)`；仅在确认为 Lock 等待且 blocker 是第一业务 backend 时继续，并在释放第一事务后验证第二请求完成。监控与两条业务连接的 PID 不同，超时有界。
- PostgreSQL 受控并发测试覆盖创建先行、取消先行、过期/中止竞争及 grant 并发，固定 CI job 通过。`test_abort_before_expiry_remains_terminal_after_clock_advance` 在有效期内先提交 Abort，再推进时钟并读取，确认 Session 与 Asset 仍是 `aborted/upload_aborted`、`failed/upload_aborted` 且更新时间未被重写；`test_expiry_first_blocks_abort_from_rewriting_reason` 单独验证过期先行。
- 发现一个尚未在原规格中消歧的边界：Session 取消后，同键同参重试既有上传意图会在幂等查找前收到 409；见 WARNING-1。

#### 上传契约、时间、游标与 M2/M3 边界

- Edge 创建意图从有效节点凭据导出来源，并校验 Device、Node 与 Session 的场馆/机构关系；用户与 Edge 身份分离。请求 schema `extra="forbid"`，归属和来源不接受客户端覆盖。
- 采集原始时间字段保留字面值，`received_at` 为服务端值；已验证 Offset 正向往返及未知/非法组合拒绝。UTC 与 IANA 有效组合的正向证据不足，见 WARNING-4。
- 授权过滤在分页之前执行；游标绑定资源种类、tenant/site、过滤条件和排序版本；撤权后续页只返回当前仍可见记录，跨筛选重放返回 `invalid_cursor`。
- 运行时没有 ready、上传分片、整对象校验、对象存储、播放或公开 derived 创建端点；UploadSession 只表示上传意图，符合 M2/M3 边界。
- PR#5 新增 16 个操作；原有 19 个基础操作及 12 个 Registry 操作保持契约兼容。运行时 OpenAPI 33 paths / 47 operations 与快照相同。

## CRITICAL

无。

## WARNING

### WARNING-1：Session 取消后幂等重试被当成新意图拒绝

- **位置：** `services/cloud/src/swimplatform/media.py:655–687`（用户路径）；`services/cloud/src/swimplatform/media.py:770–795`（Edge 路径）；对应契约 `openspec/changes/implement-cloud-session-asset-foundation/specs/cloud-media-asset/spec.md:9–21, 91–102`。
- **复现条件：** 对仍有效且有权的 Session，以 key `K` 成功创建上传意图；之后 Session 被取消；同一主体、同一 key、相同请求体重试。
- **实际行为：** 用户路径在 `_assert_intent_allowed()` 检查 cancelled 并返回 409 后才查询已有幂等记录；Edge 路径也先拒绝 cancelled，再查幂等记录。已有记录不会 replay。
- **影响：** 原响应丢失或客户端超时后，重试结果会受后续 Session 状态影响，不能按规格返回原 asset/upload pair。不会产生重复记录或越权读取，但幂等语义与“同主体同 key 同参数重试返回同一对记录”不一致。M3 续传/重试逻辑若依赖稳定重放，可能产生歧义。
- **证据：** `test_media_foundation.py:143–168` 仅覆盖 Session 活跃时的同键 replay；`test_media_foundation.py:222–242` 取消后新建请求使用未见过的 key。没有取消后同键 replay 的测试。代码顺序可直接确认上述结果；设计表中“cancelled 时 409”针对新意图，但当前顺序也覆盖了已存在意图。
- **建议：** 在保证调用者仍有权且 key 作用域正确的前提下，先识别并验证已有幂等记录；已存在且请求摘要匹配时 replay 原结果，只有不存在的 key 才按 cancelled 返回 409。增加用户与 Edge 覆盖测试，或在设计/规格中明确取消后不保证 replay 并更新验收语义。

### WARNING-2：相同内容的两次独立采集缺少直接回归测试

- **位置：** `openspec/changes/implement-cloud-session-asset-foundation/specs/cloud-media-asset/spec.md:9–21`；逻辑资产创建在 `services/cloud/src/swimplatform/media.py:597–640`；`VideoAsset` 身份/摘要约束在 `services/cloud/src/swimplatform/models.py:333–442`（不存在 checksum 唯一约束）。
- **复现条件：** 同一 Session 下，提交两个不同 Idempotency-Key 的独立意图，声明相同 SHA-256 和大小，但来源/采集元数据不同。
- **预期：** 两个不同 asset_id，各自保留来源与采集元数据；内容摘要相同不能合并逻辑采集身份。
- **影响：** 当前模型/创建路径未按摘要去重，代码结构支持预期行为；但这是核心领域规则，现有显式测试只证明同 key 重试得到同一记录，没有锁定“同摘要、不同采集”保持两个记录的回归证据。
- **证据：** Spec Delta 定义了 “Same content from two captures” 场景；`test_media_foundation.py:143–168` 检验的是同 key replay。迁移和模型没有 checksum 唯一约束。CI 全绿不能替代缺失的这一场景断言。
- **建议：** 新增 API 测试，用两个 key、同摘要/大小、不同来源元数据，断言 asset/upload IDs 不同且各自来源字段原样保存。

### WARNING-3：Grant 重复写入/撤销的审计字段保留缺少直接断言

- **位置：** 实现 `services/cloud/src/swimplatform/media.py:427–474`；任务验收 `openspec/changes/implement-cloud-session-asset-foundation/tasks.md:24`；当前 grant API 测试 `services/cloud/tests/test_media_authorization.py:140–172`。
- **复现条件：** 以不同管理员和可控时钟，对同一 Session/Asset grant 重复 PUT；随后重复 DELETE，并读取数据库审计字段。
- **预期：** 重复 PUT 保留首次 `granted_at`/`granted_by_user_id`；重复 DELETE 返回 204 但不覆盖首次 `revoked_at`/`revoked_by_user_id`。
- **影响：** 当前更新语句只更新活跃 grant 的期限/更新时间，撤销语句只更新 `revoked_at IS NULL`，实现看起来满足要求；但由于测试没有在两次请求后断言数据库审计主体与时间不变，关键授权审计历史的回归保护不足。
- **证据：** `test_media_authorization.py:140–172` 验证重复 DELETE 的响应和授权效果，不读审计字段；`test_postgresql_media.py:188–214` 验证并发写后仅一条有效 grant，也未比较首次主体/时间。当前没有针对不同执行者与时钟的持久字段断言。
- **建议：** 增加 SQLite 与 PostgreSQL 可共享的 API 测试，使用不同管理员身份和可控时钟，重复 PUT/DELETE 后读取数据库并逐字段核对首次 grant/revoke 主体及时间保持不变。

### WARNING-4：采集时间基准的有效 UTC/IANA 组合未被正向测试覆盖

- **位置：** `services/cloud/src/swimplatform/schemas.py:305–376`（CaptureMetadata 校验）；`services/cloud/tests/test_media_foundation.py:261–305`（现有有效/无效用例）。
- **复现条件：** 分别提交语义合法的 `device_time_basis="utc"` 与 `device_time_basis="iana_timezone"` 采集元数据，并读取生成的 Asset。
- **预期：** 合法基准组合被接受，原始设备时间及其基准/时区语义持久化；服务端 `received_at` 与设备时间保持区分。
- **影响：** 当前实现包含基准交叉校验，Offset 路径和负向验证覆盖；但任务 2.9 声明每种基准都有合法/非法组合，UTC 与 IANA 的有效组合没有直接正向 API 证据。CI 全绿无法证明这些正向输入可用。
- **证据：** `test_capture_metadata_rejects_inconsistent_basis` 的参数均为非法组合；`test_raw_device_time_is_preserved_verbatim` 只覆盖 Offset。`schemas.py` 负责校验，但未见 UTC/IANA 有效样例的端到端断言。
- **建议：** 增加 UTC 与 IANA 各一条有效请求及读取断言；为 IANA 覆盖有效 ZoneInfo，验证原始值和 `received_at` 分别保留。

## SUGGESTION

### SUGGESTION-1：清理 SQLite datetime adapter 与依赖弃用告警

- **位置：** 固定 Head CI run `43531540007` 的 `test` job 与 PostgreSQL 17 job。
- **证据：** SQLite job `179 passed / 64 skipped` 且有 163 条 pytest warning，其中 162 条为 Python sqlite3 默认 datetime adapter 弃用告警，另 1 条来自 Starlette/AnyIO `BlockingPortal`；PostgreSQL job有 1 条相同的 Starlette/AnyIO warning。失败与错误均为 0。
- **建议：** 后续按统一时间序列化策略显式注册 SQLite adapter/converter，并在依赖升级时处理 Starlette/AnyIO 告警；不阻塞本次 Change 的归档判断。

## CI 与验证证据

| 项目 | 固定 Head 证据 |
| --- | --- |
| GitHub Actions | [run 43531540007](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43531540007) |
| SQLite job | checkout `650425db9838425175620fc54abb347c7b5f8657`；179 passed / 64 skipped；0 failed / 0 errors |
| PostgreSQL 17 job | checkout 同一固定 SHA；240 passed / 3 skipped；0 failed / 0 errors |
| PG skips | 仅 SQLite 专属授权时限测试及 SQLite 迁移测试 |
| 容器清理 | 测试摘要 `cleanup=removed`；run-file 兜底 `status=absent`, `cleanup=absent`, `exit_code=0` |
| PostgreSQL 证据包 | [artifact 14087273349](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43531540007/artifacts/14087273349) |
| OpenSpec | Change strict 1/1；主规格 strict 2/2 |
| OpenAPI | 运行时与快照精确匹配：33 paths / 47 operations |
| 代码/文档状态 | 本报告创建前代码 HEAD 与 origin 分支一致；Verify 未改业务代码、迁移、OpenAPI、主规格或 28 项 Apply 状态 |

## 最终决定项

1. **合并阻断：** 未发现 CRITICAL；本 Verify 未作 Merge 判断或授权。WARNING-1 是应优先处理的契约边界问题。
2. **Apply 证据：** 28 项均有可追溯交付；任务 2.8、2.9 的特定审计/正向组合断言仍有测试证据缺口，另外两个规格场景缺直接回归测试，均已逐项列出。
3. **Archive：** 按 OpenSpec Verify 结果可归档（4 项 WARNING、1 项 SUGGESTION 随归档保留）；是否执行 Archive 等待负责人单独授权。
4. **定向修复：** 建议先解决/明确 WARNING-1；WARNING-2 至 4 可通过补充测试完成验收闭环。未在本轮修改实现或测试。
5. **进入 M3 前设计收口：** 条件满足。M2 的逻辑资产、授权、上传意图和事务边界已成形；但 M3 设计应先明确 cancelled Session 上既有幂等意图 replay 语义，并为捕获元数据、grant 审计补齐正向/审计证据后再把相关行为作为稳定前置。
