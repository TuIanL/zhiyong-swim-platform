# Verification Report: implement-cloud-edge-device-foundation（W1–W3 修复后）

## 核验对象与方法

- Repository：`TuIanL/zhiyong-swim-platform`
- PR #4：[Cloud Edge Registry](https://github.com/TuIanL/zhiyong-swim-platform/pull/4)，核验时保持 Draft
- 固定 PR head：`a9c7f21d483ddfc292f6e8870ebfddce19b324b9`
- 修复代码 head：`f4ab838fb1a438d8f927a90fcb3746a9ce0188da`
- 初始 Apply Code Head：`5b3dcec45628697f7401d45df3da4e0d05ff79db`
- 首次 Verify 报告提交：`71c1212d7d9099e46d50938ab9da161a605a65db`
- Apply 后修复记录：[cloud-edge-device-foundation-remediation.md](../../../../docs/verification/cloud-edge-device-foundation-remediation.md)
- 本轮范围：核对现有 14 项 Apply 交付，并重点验证首次报告 W1、W2、W3 是否已修复。首次 [verification.md](verification.md) 原文保留，未覆盖。
- 核验依据：当前代码与 OpenSpec artifacts、PostgreSQL/SQLite 最终 head CI 原始日志和证据包，以及本报告列明的 strict、契约和链接检查。

## Summary

| Dimension | Status |
| --- | --- |
| Completeness | **14/14 tasks complete**；9/9 ADDED/MODIFIED requirements 均有实现证据映射，未发现仅勾选而无交付的任务。 |
| Correctness | **9/9 requirements reviewed，33/33 scenarios reviewed**；W1/W2/W3 的实现与要求一致，双后端完整 CI 成功；5 项非阻断 SUGGESTION 保留。 |
| Coherence | Proposal、Design、两份 Spec Delta、Tasks、API 契约、OpenAPI、实现和测试相互一致；D11–D13 与本次修复一致。Change strict、主规格 strict、OpenAPI 快照和链接检查通过。 |

## 核心任务与需求证据

OpenSpec `instructions apply --change implement-cloud-edge-device-foundation --json` 汇总 14 项任务、14 项完成、0 项剩余，所有任务均可从 `tasks.md` 读取。首次 Verify 的任务交付交叉表仍适用于未改动的 Apply 交付；本轮另外检查了以下修复证据。`tasks.md` 在首次 Verify 后没有变化，Apply 状态仍是 14/14。

| Delta requirement | 实现与场景证据 | 结论 |
| --- | --- | --- |
| Tenant scoped registry management | `edge_registry.py` 管理端依赖和 12 个操作；`test_edge_registry_api.py` 的角色/输入覆盖；新增真实 PostgreSQL 跨租户 Node PATCH、Credential Issue、Revoke 行锁测试。 | 实现与错误边界匹配；非管理者的全面逐端点矩阵作为 S4 建议。 |
| Immutable device provenance | 四张新增表、迁移复合外键和 RESTRICT；模型/Schema 测试；相同 serial 的独立 Device ID、camera-first/未支持 kind 回归。 | 已映射并通过双后端基线。 |
| Independent revocable edge credentials | 独立 Edge bearer 路径、用户/Edge token 不互用测试、凭据读取不返回 secret/hash。 | 已映射并覆盖。 |
| Bounded credential lifecycle | 7/30 天边界、UTC/Asia 时区、一次性明文、35 天后 401、撤销审计/重放测试；新增显式 Revoke 与 Heartbeat 竞态。 | 已映射并覆盖。 |
| Administrative node lifecycle | Node 状态/generation、原子停用撤销、独立连接停用/签发/Heartbeat 竞态和事务回滚测试。 | 已映射并覆盖。 |
| Bounded trustworthy heartbeat observations | 30/90 秒、服务端接收时间、健康输入边界和失败不改行政状态测试；新增 `observed_at_raw` 原样 round-trip。 | 已映射并覆盖。 |
| Durable request idempotency | 同键重试/异参冲突/重启重试/重新授权、秘密不重放、独立连接同键竞争测试。 | 已映射并覆盖；长期保留与软引用列为 S1/S2。 |
| Isolated database validation (MODIFIED) | `pg_support.py`、`conftest.py`、`test_pg_harness_guard.py`；实际容器/标签/端口核验、仅批准十表授权、清理失败非零传播及最终 PG run。 | 已映射并覆盖。 |
| PostgreSQL schema integrity (MODIFIED) | `test_postgresql_schema.py` 约束反射、迁移往返/回滚、跨租户复合引用、RESTRICT、初始 revision 保留。 | 已映射并覆盖。 |

两份 Spec Delta 共计 9 项 ADDED/MODIFIED requirement 和 33 个 scenarios。Spec Coverage、Requirement Implementation Mapping、Scenario Coverage 均有代码、测试或运行证据；无 REMOVED/RENAMED 项。

## W1–W3 修复验证

### W1：跨租户管理请求不会先锁定全局 Node

- **实现**：[edge_registry.py:134](../../../../services/cloud/src/swimplatform/edge_registry.py#L134) 的 `lock_manager_node` 在构造 `FOR UPDATE` 查询前同时限定 `EdgeNode.id`、`tenant_id`、`site_id`。Node PATCH、Credential Issue、Revoke 分别在 [edge_registry.py:333](../../../../services/cloud/src/swimplatform/edge_registry.py#L333)、[edge_registry.py:407](../../../../services/cloud/src/swimplatform/edge_registry.py#L407)、[edge_registry.py:451](../../../../services/cloud/src/swimplatform/edge_registry.py#L451) 调用 scoped lock，范围不匹配统一返回 `edge_node_not_found` 404。Edge Token 认证仍通过 credential 绑定的 Node 使用原 `lock_node` 路径。
- **负向测试**：[test_edge_registry_transactions.py:224](../../../../services/cloud/tests/test_edge_registry_transactions.py#L224) 建立 Tenant A 与 Tenant B 的真实 Node/Credential。独立 PG 管理连接持有 Tenant B Node 的行锁时，并发发送 A 管理员对 B 资源的 PATCH、Issue、Revoke；三项请求必须在 8 秒上限内、外部锁仍持有时完成，均断言同一 404 code。测试监听每个 Node 锁查询的实际 backend PID，并比较锁持有人 PID；Node、Credential、幂等记录做变更前后快照比较。
- **结论**：代码的锁条件在归属检查阶段即生效；CI 实际通过该负向测试。没有再发现“先按全局 ID 锁定再验机构”的管理路由。

### W2：`observed_at_raw` 保留原始字符串

- **实现**：[schemas.py:238](../../../../services/cloud/src/swimplatform/schemas.py#L238) 只对 `observed_at_raw` 使用 `strip_whitespace=False`，保留 `str | None` 类型和 128 字符上限；父类对其他普通字段的空白规范化仍保留。
- **测试**：[test_edge_registry_api.py:225](../../../../services/cloud/tests/test_edge_registry_api.py#L225) 断言 Pydantic 输入、Heartbeat API 持久化、数据库值和 NodeRead 均保留首尾空白；普通 Node 名称和 health software version 仍被规范化；非法类型和 129 字符输入被拒绝。
- **契约**：[cloud-edge-registry.md](../../../../docs/contracts/cloud-edge-registry.md) 与 Design 明确原始字段包括首尾空白且不解析/裁剪/规范化。当前 FastAPI 生成 schema 与 `docs/contracts/openapi.json` 完全相等，字段仍为 nullable string、`maxLength=128`。
- **结论**：首次报告中的 W2 已修复，未影响其他输入字段。

### W3：显式 Credential Revoke / Heartbeat 两种事务顺序

- **测试**：[test_edge_registry_transactions.py:351](../../../../services/cloud/tests/test_edge_registry_transactions.py#L351) 为 PostgreSQL 专属必需场景；应用 pool 断言至少 8。竞态 helper 为两个操作使用不同的 `pg_backend_pid()`；测试将 PID 写入 JUnit `record_property`。PG harness 在 [test-postgresql.py:460](../../../../scripts/test-postgresql.py#L460) 使用兼容 `record_property` 的 xunit1，参数有单测。
- **顺序 A**：Heartbeat `200` 后 Revoke `204`；响应和持久状态中 `last_seen_at` 等于服务端接收时间，Credential 已撤销。
- **顺序 B**：Revoke `204` 后旧 Credential Heartbeat `401`；失败请求不更新 `last_seen_at`，首次 `revoked_by_user_id`/`revoked_at` 保持。
- **重复撤销**：另一名有效管理员再次 DELETE 返回 `204`，不能覆盖首次撤销主体或时间。
- **CI 证据**：最终 PostgreSQL job 对该模块完成收集并通过，ledger `shared=122, postgresql=51`；JUnit artifact 与固定 PR head 绑定。此前 xunit2 造成的两条属性兼容警告已由 xunit1 调整消除。
- **结论**：首次报告中的 W3 验收证据缺口已补齐。记录的 PID 由测试运行时从 psycopg 后端连接取得，并经不同 PID 断言；并发池不是单连接模拟。

## 最终 head CI 与严格检查

GitHub 原始 PR run metadata 将 [Actions run #74](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951674735) 绑定到最新 PR head `a9c7f21d483ddfc292f6e8870ebfddce19b324b9`，base `main` 为 `d7f1eedb13ac0f44abb738bc6e8b4d0d38d7766d`；两个 job 均 success。

| Job | 原始 CI 结果 |
| --- | --- |
| SQLite | 123 passed、51 个 PostgreSQL 专属 skipped、0 failed、34 warnings。 |
| PostgreSQL 17 | 173 passed、1 个 SQLite 专属 skipped、0 failed、1 pytest warning；ledger `shared=122, postgresql=51`。 |

- PG 的唯一 pytest warning 是既有 Starlette/AnyIO `BlockingPortal` 弃用警告；SQLite 的 34 条为该警告与 SQLAlchemy SQLite datetime adapter 弃用警告。GitHub action 日志另有 Node.js 20、punycode、`url.parse()` runtime deprecation，列在 S5，不是测试失败。
- PG harness run id `a55536755bed7c38`：主测试结果 `passed`、清理 `removed`；CI always 清理报告 `absent`、exit code 0。
- [PostgreSQL 原始 job 日志](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951674735/job/130297169480)与 [evidence artifact 13825920148](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951674735/artifacts/13825920148)的 artifact metadata 绑定同一 PR head。Artifact SHA-256：`d958e5fcb84c227cba044453084e110ad81cb90e4276568302d556a8a0d90487`。
- OpenSpec Change strict `openspec validate implement-cloud-edge-device-foundation --strict --json`：1/1 passed，0 issues。
- 主规格 strict `openspec validate --specs --strict --json`：`cloud-identity` 1/1 passed，0 issues。
- FastAPI 当前生成 OpenAPI 与已提交快照 JSON 深比较完全相等。
- Markdown 相对链接检查（OpenSpec、`docs/contracts`、`docs/verification`）：34 份 Markdown、139 个相对链接，0 失效；既有未跟踪 `docs/workflow/` 依原要求保留且不纳入本次扫描。`git diff --check main...HEAD` 通过；报告暂未提交时另经 staged diff check。
- 当前 PR 为 Draft/open/unmerged，head 为 `a9c7f21`；base `main` 未变化。原 `verification.md` 与 14 项 Apply checkbox 均未修改。

## Issues by Priority

### CRITICAL

None.

### WARNING

None. 首轮报告中的 W1、W2、W3 现由本报告所列实现、负向/往返/并发测试及最新 head CI 证据覆盖。

### SUGGESTION

#### S1 — 幂等记录永久保留需在未来删除/隐私设计中定策略

- **证据**：[models.py:212](../../../../services/cloud/src/swimplatform/models.py#L212) 的 IdempotencyRecord 保留 tenant/site/user、资源 ID 与 hash；用户和场馆关联使用 RESTRICT，Design F5 明确不自动淘汰。
- **影响**：后续用户/场馆删除或隐私擦除可能受历史记录外键与标识保留影响。当前没有对应删除流程，本 Change 的永久去重行为符合已批准边界。
- **建议**：在后续删除/隐私 Change 中明确保留期限、清理/匿名化和外键策略，再实现删除流程；当前不削弱幂等保证。

#### S2 — `resource_id` 是显式软引用

- **证据**：[models.py:230](../../../../services/cloud/src/swimplatform/models.py#L230) 对 resource kind 做约束并建索引，但多态 `resource_id` 无法由单一外键引用 Node、Device 或 Credential。
- **影响**：未来若新增资源删除，历史幂等记录可能指向已删除资源，数据库本身不能阻止或清理该引用。
- **建议**：在未来删除/墓碑设计中规定幂等重放、目标删除与保留记录的顺序，并为准许的删除路径增加测试。

#### S3 — OpenAPI 未列出自定义错误响应

- **证据**：`docs/contracts/openapi.json` 当前新 Registry 操作的响应通常只列成功码和 422，例如列表 200/422、创建 201/422；契约另有 401/403/404/409 行为。
- **影响**：生成客户端和 API 工具无法从机器可读契约获知全部授权、状态和幂等错误。
- **建议**：在单独授权的契约更新中为适用操作补充复用错误 schema 与响应码；当前不影响已实现 runtime 行为。

#### S4 — 12 个操作的全角色负向矩阵仍不完整

- **证据**：[test_edge_registry_api.py:55](../../../../services/cloud/tests/test_edge_registry_api.py#L55) 对 Node 列表/详情代表性验证 Owner/Admin、Coach、Athlete、非成员和匿名，但当前测试未对全部 12 个操作逐一参数化覆盖 Owner/Admin、Coach、Athlete、匿名、非成员、错 Site 和跨 Tenant。新增 W1 用例专门覆盖三个敏感管理路由，不等同完整矩阵。
- **影响**：权限依赖未来可能错误接线的某一个端点时，逐端点角色回归未必发现。
- **建议**：后续增加共享参数化端点/角色矩阵与拒绝无副作用快照，不扩大本次 W1–W3 修复范围。

#### S5 — CI 与运行时仍有依赖弃用警告

- **证据**：最终 run #74 的 SQLite job 34 warnings（SQLAlchemy datetime adapter 与 AnyIO/Starlette）；PostgreSQL job 1 pytest warning（AnyIO/Starlette）；runner 原始日志还有 Node.js 20 actions、punycode 和 `url.parse()` 弃用提示。
- **影响**：这些警告未使当前 CI 失败，但升级运行时或依赖时需要处理兼容性。
- **建议**：后续单独确定 SQLite datetime adapter 策略并更新相关依赖/actions；本次不修改数据库或 CI 版本。

## Final Assessment

无 CRITICAL、无 WARNING；5 项 SUGGESTION 作为后续改进保留。适用检查均有可读 artifacts、实现或最终 head 证据，没有标为 Not verified 的检查。W1/W2/W3 定向修复通过独立 Verify；Change **Ready for archive (with noted improvements)**。本报告不执行 Archive、不修改主规格、不将 PR 标为 Ready，也不执行 Merge；这些仍等待项目负责人分别授权。
