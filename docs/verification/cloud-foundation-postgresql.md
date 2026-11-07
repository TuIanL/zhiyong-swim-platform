# PostgreSQL 云端基础验证报告

- 报告日期：2026-11-07（Asia/Shanghai）
- change：`validate-cloud-foundation-postgresql`（阶段：apply）
- 实现提交：`1bd0883`（本文件随后续文档提交一起进入同一 PR）
- 结论适用范围：**仅本文件列出的提交、环境与用例**。不代表 RLS、生产部署或全平台安全验收通过。

## 1. 本次交付

| 文件 | 作用 |
| --- | --- |
| [`scripts/test-postgresql.py`](../../scripts/test-postgresql.py) | 专用实例编排：容器、镜像锁定、回环端口、run id 校验、有界就绪等待、清理与失败日志 |
| [`configs/postgresql-test-image.json`](../../configs/postgresql-test-image.json) | PostgreSQL 17.11 多架构 manifest list digest 锁定 |
| [`services/cloud/tests/pg_support.py`](../../services/cloud/tests/pg_support.py) | 每例独立库、`swim_cloud` schema、连接级 `search_path`、最小授权、并发辅助 |
| [`services/cloud/tests/test_postgresql_schema.py`](../../services/cloud/tests/test_postgresql_schema.py) | 六表、schema 落点、约束/级联、降级往返、迁移中断回滚 |
| [`services/cloud/tests/test_postgresql_identity.py`](../../services/cloud/tests/test_postgresql_identity.py) | 应用身份属性、owner 关系、负向权限探测 |
| [`services/cloud/tests/test_postgresql_transactions.py`](../../services/cloud/tests/test_postgresql_transactions.py) | 并发唯一写入、五次并发失败登录、持锁等待 |
| [`services/cloud/tests/test_connection_reuse.py`](../../services/cloud/tests/test_connection_reuse.py) | 单物理连接顺序复用的隔离证据 |
| [`services/cloud/tests/test_authorization_matrix.py`](../../services/cloud/tests/test_authorization_matrix.py) | 17 个业务 operation 的角色矩阵（两后端共享） |
| [`services/cloud/tests/test_authentication_deadlines.py`](../../services/cloud/tests/test_authentication_deadlines.py) | 时区独立的截止时间边界 + SQLite 朴素 UTC 回归 |
| [`services/cloud/tests/test_pg_harness_guard.py`](../../services/cloud/tests/test_pg_harness_guard.py) | 编排入口的安全边界（无需 Docker） |
| [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | 保留 SQLite job，新增 PostgreSQL job |

产品代码只改一处：`services/cloud/src/swimplatform/api.py` 增加 `as_utc()` 并在锁定比较处使用（见第 5 节）。

## 2. 执行环境与命令

```bash
# 本机 SQLite
python -m pytest

# 本机 PostgreSQL（入口自行创建与销毁实例）
python scripts/test-postgresql.py
```

| 项目 | 本机实测值 |
| --- | --- |
| 平台 | macOS / Darwin，容器内 `linux/arm64` |
| 镜像 | `postgres:17.11@sha256:ff87138949ad9a46f32ff23bd6852b52ce024a13dffe9b4087be98292cdd3b4f` |
| `server_version` | `17.11 (Debian 17.11-1.pgdg13+2)` |
| 实例默认时区 | `Etc/UTC`（各用例库另行设置 UTC / Asia/Shanghai） |
| 驱动 | psycopg 3.2.3（`psycopg[binary]`），SQLAlchemy 2.0.36，Alembic 1.14.0 |
| 数据库身份 | `swim_admin`（管理员，仅建库/建 schema/授权/销毁）、`swim_migrator`（schema owner，执行迁移）、`swim_app`（非特权应用身份） |
| 运行记录 | run id `00bc4d4411ebb1d2`，`cleanup=removed`，`result=passed` |

## 3. 实际运行结果

| 后端 | 结果 | 说明 |
| --- | --- | --- |
| SQLite（本机，`python -m pytest`） | 48 passed，39 skipped | 跳过项全部是 `postgresql` 专属用例 |
| PostgreSQL（本机，入口脚本） | 86 passed，1 skipped，0 failed | 跳过项为 1 个 `sqlite` 专属用例；共收集 87 项，18.2 秒 |
| SQLite（GitHub Actions amd64） | 48 passed，39 skipped，0 failed | [PR CI 42324575127](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42324575127)，实现交付 head `4cfa39d` |
| PostgreSQL（GitHub Actions amd64） | 86 passed，1 skipped，0 failed | 同一 PR CI；共享与 PG 专属用例实际运行，清理与上传步骤成功 |

分类计数：共享 API 用例 47 项（两后端都跑）、`postgresql` 专属 39 项、`sqlite` 专属 1 项。

### 3.1 接续 apply 时补取的 CI 证据

2026-11-07，通过 GitHub 连接器查询实现交付 head `4cfa39d95f4a1b80ea28006f3153e3e6c6810950` 的 PR 工作流，读取两个 job 的步骤及实际日志，并下载核对 [PostgreSQL 证据包](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42324575127/artifacts/13554132959)。不是仅凭工作流绿灯或任务勾选作结论。

| 证据项 | 核对结果 |
| --- | --- |
| 绑定提交 | PR head `4cfa39d`；checkout 日志为 GitHub 临时合并引用 `90cb859`（将该 head 与 `main@4968750` 组合），不表示 PR 已合并 |
| SQLite job | `128256767322`，completed/success；实际 pytest 输出 `48 passed, 39 skipped` |
| PostgreSQL job | `128256767499`，completed/success；87项中86 passed、1 skipped，failures=0、errors=0；跳过项仅 `test_sqlite_naive_utc_deadlines_stay_compatible` |
| 共享场景 | PG JUnit 包含共享 API 和 PG 专属用例，不是只执行 `-m postgresql`；与本机47共享+39专属计数一致 |
| CI平台/版本 | 摘要实际值 `linux/amd64`、`17.11 (Debian 17.11-1.pgdg13+2)`、`TimeZone=Etc/UTC`；驱动安装日志确认 psycopg 3.2.3 |
| 镜像 | 与本机相同 `postgres:17.11@sha256:ff87138949ad9a46f32ff23bd6852b52ce024a13dffe9b4087be98292cdd3b4f`；摘要中的image_id/repo_digests亦返回该值，不额外推定单平台清单digest |
| 身份/退出/清理 | `swim_admin` / `swim_migrator` / `swim_app`；pytest_exit_code=0，result=passed，cleanup=removed；always清理步骤success |
| 实例运行标识 | CI `9703ff47682511cb`，与本机 `00bc4d4411ebb1d2` 分开；证据包内字段 `local_execution=true` 不用于判定运行宿主，以工作流来源和实际platform为准 |

证据包中的摘要与JUnit已读取，本地副本位于被忽略的 `var/ci-evidence/42324575127/`，不提交凭据或测试数据。Actions证据包保留期14天；本报告保存核对后的结果、提交和日志入口。接续工作只调整文档/任务状态，未重新在本机运行业务或数据库测试；收口提交的CI状态继续在PR及Notion最新交付记录中绑定实际head。

## 4. 18 个规格场景到实际证据

| # | 场景 | 用例 | 本机结果 |
| --- | --- | --- | --- |
| 1 | Initialization points to external database | `test_cloud_foundation.py::test_cli_refuses_external_or_legacy_database`（2 参数） | SQLite/PG 均通过 |
| 2 | PostgreSQL target is not owned by this run | `test_pg_harness_guard.py::test_host_port_resolution_requires_own_container_and_loopback`、`::test_entry_point_has_no_database_url_option`、`::test_environment_drops_business_dsn_and_all_libpq_variables`、`::test_run_id_and_container_name_are_validated` | 均通过 |
| 3 | Restricted application identity | `test_postgresql_identity.py`（18 项，含 `CREATE SCHEMA`/`TRUNCATE`/版本表写/`SET ROLE`） | PG 18/18 通过 |
| 4 | Failure during test execution | `test_pg_harness_guard.py::test_cleanup_only_removes_its_own_container`、`::test_cleanup_from_run_file_rejects_forged_or_mismatched_records`、`::test_unavailable_docker_fails_without_sqlite_fallback`；运行摘要 `cleanup=removed` | 均通过 |
| 5 | Empty database migration and round trip | `test_postgresql_schema.py::test_revision_and_version_table_live_in_dedicated_schema`、`::test_downgrade_and_upgrade_roundtrip` | 通过 |
| 6 | Invalid cross tenant reference | `::test_composite_foreign_keys_reject_cross_tenant_references` | 通过 |
| 7 | Unique keys and cascading removal | `::test_unique_constraints_reject_duplicates_without_residue`、`::test_cascading_removal_keeps_unrelated_tenants` | 通过 |
| 8 | Interrupted migration transaction | `::test_interrupted_migration_rolls_back_ddl_and_version` | 通过 |
| 9 | Role and operation matrix | `test_authorization_matrix.py`（10 项，覆盖 17 个 operation + health/ready） | SQLite/PG 均通过 |
| 10 | Explicit site access and management exception | `::test_site_grant_and_revoke_matrix`、`::test_admin_downgrade_and_management_exception` | SQLite/PG 均通过 |
| 11 | Membership removal and role downgrade | `::test_permission_changes_apply_to_existing_sessions`、`::test_admin_downgrade_and_management_exception` | SQLite/PG 均通过 |
| 12 | Reused connection across identities | `test_connection_reuse.py`（2 项，`pool_size=1`，`pg_backend_pid()` 唯一） | PG 通过 |
| 13 | Equivalent instants in different timezones | `test_authentication_deadlines.py::test_deadlines_are_absolute_instants_in_each_timezone[UTC|Asia/Shanghai]`、`::test_reused_connection_keeps_database_timezone_and_search_path` | PG 通过（修复后） |
| 14 | SQLite compatibility | `::test_sqlite_naive_utc_deadlines_stay_compatible`、`test_cloud_foundation.py::test_account_lockout`、`::test_expired_and_deactivated_sessions_are_rejected` | SQLite 通过 |
| 15 | Concurrent unique writes | `test_postgresql_transactions.py::test_concurrent_tenant_slug_writes_leave_one_record`、`::test_concurrent_registration_same_email`、`::test_concurrent_site_name_writes_leave_one_record` | PG 通过 |
| 16 | Concurrent failed logins | `::test_five_concurrent_failed_logins_are_all_counted`、`::test_login_waits_for_row_lock_and_continues` | PG 通过 |
| 17 | Missing PostgreSQL prerequisites | `test_pg_harness_guard.py::test_unavailable_docker_fails_without_sqlite_fallback`、`::test_image_lock_rejects_unpinned_or_non_pg17_targets`；conftest 的必需场景统计与下限校验 | 均通过 |
| 18 | Evidence bound to a revision | 本文件；运行摘要与 JUnit 绑定 run id `00bc4d4411ebb1d2` 与提交 `1bd0883` | 见下节限制 |

## 5. 关键发现

### 5.1 `api.py` 的锁定时间在非 UTC 会话下会整体偏移（已修）

原实现把数据库读出的 `locked_until` 直接 `replace(tzinfo=UTC)`。SQLite 返回朴素值，这样写恰好正确；但 PostgreSQL 在 `Asia/Shanghai` 会话返回 `+08:00` 的 aware 值，`replace` 会把同一墙钟重标为 UTC，使截止时间被推迟 8 小时。

修复前的失败证据（run id `71a795c03f22893d`，实现提交 `1bd0883` 之前的 API 代码）：

```
FAILED services/cloud/tests/test_authentication_deadlines.py::test_deadlines_are_absolute_instants_in_each_timezone[Asia/Shanghai]
E  assert 401 == 200        # 恰好到期的锁被判为仍生效
```

同一时刻的 `[UTC]` 参数通过，`[Asia/Shanghai]` 失败，证明差异只来自会话时区。

修复（`1bd0883`）：新增 `as_utc()`，aware 值用 `astimezone(UTC)` 保留绝对瞬间，朴素值按既有 UTC 约定补 `tzinfo`。修复后两个时区参数与 SQLite 回归用例全部通过，五次/十五分钟锁定策略、token 格式与 API 形状未变。

### 5.2 迁移脚本不管理对象授权

`alembic downgrade base` 后 `alembic_version` 表仍存在（Alembic 既有行为，未清空），重新 `upgrade` 会重建六表，但**不会**恢复应用角色权限——权限来自库外授权，不是迁移的一部分。验证用例在重新升级后显式调用 `grant_application()` 才能继续。

这属于待决策的运维事实：真实部署若采用 schema 重建或降级路径，需要单独的授权步骤。本轮不修改迁移脚本来掩盖它。

## 6. 清理与资源边界

- 每次运行创建唯一容器 `swim-pg-test-<16 位 run id>`，两个 label（`com.zhiyong.swim-pg-test.run`、`.owner`），数据与 socket 放 `tmpfs`，端口只绑 `127.0.0.1`。
- 结束按 run id 精确 `docker rm --force` 并复验；本次 `cleanup=removed`，运行后 `docker ps -a` 按 label 过滤为 0。
- 失败时在清理前抓取 `docker logs` 并按本次随机密码脱敏写入 `var/postgresql-instance.log`。
- 脚本与文档均禁止全局 prune；SIGKILL/宿主崩溃的恢复流程见[决策 0002 第 7 节](../decisions/0002-postgresql-validation-and-rls-boundary.md)与 README。

## 7. 未验证范围与限制

- **CI 与本机分别取证**：最初报告提交 `4cfa39d` 时未取得CI结果；接续apply已补取第3.1节的真实linux/amd64结果。本机历史运行仍绑定 `1bd0883`，不得混作接续工作中新跑的本机结果。
- **RLS 未实施、未验证**：应用身份拥有表级 DML，直接执行无过滤 SQL 仍可跨机构读取；本报告的“隔离”指应用层授权与连接复用，不是行级安全。
- **并发覆盖有限**：只覆盖三类竞态（唯一写入、失败登录计数、行锁等待）。撤销权限与同时写入、跨机构并发更新、连接池饱和等未覆盖。
- **未做性能验证**：无压测、无 SLA、无连接数上限评估。
- **生产未涉及**：未接触生产数据库、旧库、真实账号；`init-db` 仍只允许新版 `var/` 内的 SQLite。
- **矩阵不等于全平台安全**：17 个 operation 覆盖的是当前存在的接口；平台管理员、所有权转移、审计、Web/Edge/媒体均未实现。
- 本机 pytest 的临时目录固定放在 `var/pytest-pg/<run id>/`（已被 `.gitignore` 覆盖），不使用系统临时目录。


## 8. apply接续收口与下一阶段

2026-11-07，用户明确要求接续既有apply并允许提交发布到同一PR #2。本轮以交接的14/16为起点，补取第3.1节当前实现head的CI原始证据，完成5.1；四项既有Notion任务的PostgreSQL子范围、摘要、状态及文档回链已同步，PR标题与描述已从propose更新到实际实现，完成6.2。CLI任务16/16，后续收口提交仅包含本报告和任务勾选，不改实现。

[Notion当前阶段](https://www.notion.so/410f602574aa81288834cc297ae5b039)统一维护最终提交及其CI入口；[云端基础](https://www.notion.so/410f602574aa81c8bfa0e4728a58b737)、[隔离测试基线](https://www.notion.so/410f602574aa81e8a757def927b364df)保持待验收；[数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)、[RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e)仍为进行中，均保留更广未完成范围。没有把本change的实施完成当作总体项目完成。

PR #2继续保持草稿，未执行独立verify、主规格同步/archive或合并；下一步等待用户单独授权verify。原未跟踪工作流模板保留原状，旧工程和历史数据未修改。
