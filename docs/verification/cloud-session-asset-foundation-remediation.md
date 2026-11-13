# Cloud Session / Asset Foundation：Apply 初审修复记录

- 日期：2026-11-13（Asia/Shanghai）
- Change：`implement-cloud-session-asset-foundation`
- 原 Apply Head：`1476f9847410c4e14526e08f2395a3f4ef6928f7`（代码）；`3a26d567ad0b0d8e1ed6beb1e404d2c59b729aee`（任务与报告回填）
- 本轮性质：**仅定向修复初审发现项**，不重新设计 Proposal，不改写原 Apply 报告与 28/28 历史。
- 未执行：独立 Verify、Archive、主规格同步、Ready for review、Merge。

## 1. 初审发现项与处理

| 编号 | 发现 | 处理 |
| --- | --- | --- |
| R1 | Cancel vs CreateIntent 竞态：创建上传意图在检查 Session 状态后没有持续锁定父 Session，取消可能在其间提交 | 创建路径改为**先锁父 Session（tenant/site/session 范围）再判定**，锁持有到意图事务提交；用户与 Edge 两条路径共用同一协议 |
| R2 | 缺受控顺序与物理连接证据 | 新增受控并发用例：创建先赢 / 取消先赢 / 过期先赢 / 中止先赢，均断言两个不同 `pg_backend_pid`；Cancel vs Abort、并发 Grant PUT 补 PID 断言 |
| R3 | 缺原子性与迁移回滚证据 | 新增「三对象任一步失败全部回滚」3 例；PostgreSQL 在回填后、索引替换前受控失败的回滚用例；SQLite 整表重建失败回滚用例；已发布迁移文件摘要防改写用例 |
| R4 | PR 正文与 Notion 仍有过期表述 | 报告与本记录更新；Notion 工程入口追加本轮证据（PR 正文受连接器权限限制，见第 6 节） |

## 2. 修复代码位置

| 文件 | 变更 |
| --- | --- |
| `services/cloud/src/swimplatform/media.py` | 新增 `_lock_intent_session()`：按 tenant/site/session 调用 `lock_session()`（PostgreSQL `SELECT … FOR UPDATE`、SQLite 条件写），锁后重查读取/管理/终态；用户路径先做无锁能力判定避免无权调用者占锁，再加锁重判；Edge 路径使用同一函数与同一 cancelled 规则 |
| `services/cloud/src/swimplatform/migrations/env.py` | SQLite 迁移改为显式事务（`isolation_level=None` + `BEGIN` 事件），使建表与整表重建失败时 DDL 可回滚；PostgreSQL 路径不变 |

未改动：`completed` 允许补传的语义、16 个操作的路径/字段/错误、既有 19+12 操作、OpenAPI 形状（仍 33 paths / 47 operations）。

### 并发协议

1. 取消（`PATCH …/training-sessions/{id}` → cancelled）与创建意图都在 `training_sessions` 的同一行上取锁，锁谓词包含 `id + tenant_id + site_id`。
2. 取锁后重新读取行，再判 `can_read_session` / `can_manage_session` / `status == 'cancelled'`。
3. 意图创建在**同一事务**内写 `VideoAsset` + `UploadSession` + `IdempotencyRecord` 后提交，提交即释放锁；因此「检查状态 → 写三对象 → 提交」与取消互斥。
4. 取消先提交时，创建方取锁后看到 `cancelled` → 409，且不产生任何 Asset / UploadSession / 幂等记录。

## 3. 新增与加强的测试

| 文件 | 用例 |
| --- | --- |
| `test_postgresql_media.py` | `test_intent_first_then_cancel_terminates_upload`（顺序 A：创建先赢，随后取消终结上传与资产）<br>`test_cancel_first_rejects_intent_without_side_effects`（顺序 B：取消先赢 → 409 且三表零新增）<br>`test_expiry_first_blocks_abort_from_rewriting_reason`、`test_abort_first_then_read_keeps_aborted_terminal`（过期 vs 中止两种受控顺序）<br>`test_concurrent_cancel_and_abort_leave_no_pending_asset`、`test_concurrent_grant_writes_keep_one_active_row` 补 `pg_backend_pid` 断言 |
| `test_media_foundation.py` | `test_intent_atomicity_rolls_back_all_three[3]`：分别在 `video_assets` / `upload_sessions` / `idempotency_records` 的 INSERT 注入失败，断言三表计数回到基线 |
| `test_media_migration_guards.py` | `test_published_migrations_are_unchanged`（0001/0002 摘要固定）<br>`test_sqlite_rebuild_failure_rolls_back_table_and_version`（冲突表导致重建失败 → 版本停在 0002、旧表无 `actor_kind`、历史行保留、修复冲突后可升级）<br>`test_postgres_interrupted_idempotency_extension_rolls_back`（同名索引导致索引替换失败 → 版本停在 0002、`actor_kind`/`edge_node_id` 不存在、五表不存在，清理后可升级） |

受控顺序实现：`ControlledRace` 用 SQLAlchemy 语句事件在第一条请求取得行锁后暂停，让第二条请求真实阻塞在同一把锁上，再由 Event 放行；两个 `pg_backend_pid` 均被记录并断言互不相同。不使用随机调度或纯线程并发冒充顺序证据。

## 4. 本地与 CI 结果

| 环境 | 结果 |
| --- | --- |
| 本机 SQLite（242 tests） | **0 failures / 0 errors / 64 skipped**（skip 全为 `postgresql` 标记） |
| CI（push）[43411561625](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43411561625) | `test` 与 `PostgreSQL 17 validation` 均 **success** |
| CI（pull_request）[43411568554](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43411568554) | 两个 job 均 **success** |

本机无 Docker daemon，PostgreSQL 用例只在 CI 执行；受控顺序与 PID 证据均由 CI 承载。

## 5. 兼容性与风险

- SQLite 迁移改为显式事务是一处行为变化：迁移期间 `PRAGMA foreign_keys` 在事务内不生效，跨表约束在迁移窗口内不被数据库强制；建表与数据复制的目标行自洽，测试覆盖了升级/降级/失败回滚三种路径。
- 既有 12 个 Registry 幂等测试与 19 个基础操作断言未修改。
- 锁粒度仍为单行 Session，不引入表锁或进程内互斥；跨机构请求在 scope 谓词上被过滤，不产生跨租户锁竞争。

## 6. 修复 head 与 CI 证据

- 修复 head：`8e5e50b5b81cb314fdbe18554be844e128bf7884`（分支 `feat/cloud-session-asset-foundation`）
- 提交链：`70e7610` 产品修复与新增测试 → `8e5e50b` 并发用例识别方式修正
- push run [43411561625](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43411561625)：`test` 与 `PostgreSQL 17 validation` 均 success
- pull_request run [43411568554](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43411568554)：两个 job 均 success
- PG 作业内实际执行了受控顺序用例（创建先赢 / 取消先赢 / 过期先赢 / 中止先赢）与 PID 断言，非仅线程并发

### CI 过程中修正的测试实现问题

首轮 CI 报「第一条请求没有取得行锁」。原因是 TestClient 把同步端点派发到 AnyIO worker 线程，`threading.local()` 在调用线程设置的标记在请求线程不可见，事件钩子无法区分请求。改为按「第几次取得同一行锁」判定先后（第一条已持锁暂停时，再发同一锁语句的必然是第二条），并把 PID 采集改为集合。该问题只影响测试识别方式，不影响产品并发协议。

## 7. 本轮未覆盖

- 未执行独立 Verify、Archive、主规格同步、Ready for review、Merge。
- 原 Apply 报告与 28/28 任务历史未修改；本文件只追加初审修复记录。
