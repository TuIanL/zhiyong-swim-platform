# Cloud Edge Registry Verify 定向修复记录

> 这是 Apply 后对首次独立 Verify 发现项 W1、W2、W3 的定向修复和回归证据记录，不是第二轮独立 Verify、Archive、主规格同步或 Merge 结论。首次 Verify 原文保留在 [verification.md](../../openspec/changes/archive/2026-11-11-implement-cloud-edge-device-foundation/verification.md)，未覆盖或改写。

## 基线与提交

- Repository：`TuIanL/zhiyong-swim-platform`
- Draft PR：[PR #4](https://github.com/TuIanL/zhiyong-swim-platform/pull/4)，base `main`
- 原始 Apply Code Head：`5b3dcec45628697f7401d45df3da4e0d05ff79db`
- 首轮 Verify 报告提交：`71c1212d7d9099e46d50938ab9da161a605a65db`
- 首次定向实现提交：`fbaab25d1817064986f4650f1e9b0459bd8a9512`
- PostgreSQL JUnit PID 证据提交：`664a7eb9447435de792b54da0330d4cf5a0e1964`
- 修复代码 head：`f4ab838fb1a438d8f927a90fcb3746a9ce0188da`
- 验证时 `main`：`d7f1eedb13ac0f44abb738bc6e8b4d0d38d7766d`；未修改。
- Apply 任务仍为 14/14；没有变更 `tasks.md` 或历史 Apply 状态。

## W1：管理端按 Tenant/Site 范围加锁

在 [edge_registry.py](../../services/cloud/src/swimplatform/edge_registry.py) 新增 `lock_manager_node`：PostgreSQL `SELECT ... FOR UPDATE` 执行前同时限定 Node ID、Tenant ID 和 Site ID。Node PATCH、Credential Issue、Credential Revoke 改用 scoped 查询；范围内不存在时仍返回统一 `edge_node_not_found` 404。Edge Token 路径保留凭据绑定 Node 的 `lock_node` 行为，未改变角色、合法请求和状态迁移语义。

PostgreSQL 专属测试 `test_foreign_manager_node_requests_do_not_wait_on_or_mutate_foreign_scope` 在独立管理连接持有 Tenant B Node 行锁期间，用 Tenant A 管理员对真实 Tenant B Node/Credential 发起 PATCH、Issue、Revoke。三个请求须在 8 秒受控窗口内、外部锁仍被持有时全部返回 404；SQL 监听器捕获每条请求实际执行的 Node 锁查询 PID，并断言不同于持锁连接 PID；随后对 Node、Credential、幂等记录做前后快照比较，确认无变更。测试也断言应用连接池大小至少为 8。

## W2：保留 Heartbeat 原始观测值

在 [schemas.py](../../services/cloud/src/swimplatform/schemas.py) 仅为 `HeartbeatRequest.observed_at_raw` 设置字段级 `strip_whitespace=False`，保留原有 `str | None` 类型及 128 字符上限。其他普通输入仍使用 `Input` 的空白清理。

共享 API 回归 `test_heartbeat_preserves_raw_observation_and_normalizes_other_strings` 覆盖 Pydantic 输入、Heartbeat 存储、NodeRead 返回的首尾空白保真，以及普通字段的空白清理、非法类型和超长值拒绝。[正式 API 契约](../contracts/cloud-edge-registry.md)和 Change Design 同步说明原始值语义。运行时生成的 OpenAPI 与已提交快照完整相等；该字段仍为可空字符串且 `maxLength=128`。

## W3：显式 Revoke 与 Heartbeat 事务竞态

PostgreSQL 专属测试 `test_manual_credential_revoke_and_heartbeat_have_both_serial_orders` 使用连接池大小至少 8 的应用引擎和受控 Node 行锁顺序；每对操作均记录并断言不同 `pg_backend_pid()`：

| 顺序 | 结果与持久状态 |
| --- | --- |
| Heartbeat → Revoke | Heartbeat `200`，随后 Revoke `204`；`last_seen_at` 保留本次服务端接收时间，Credential 最终撤销。 |
| Revoke → Heartbeat | Revoke `204`，旧 Credential Heartbeat `401`；失败请求不更新 `last_seen_at`，首次 `revoked_by_user_id`/`revoked_at` 保留。 |
| 重复 Revoke | 另一位有效管理员再次 DELETE 仍返回 `204`，但不覆盖首次撤销主体和时间。 |

两个新增测试均标记为 PostgreSQL 必需场景并纳入 ledger。JUnit 使用 `record_property` 保存 pool size、外部持锁 PID、每个操作 PID 和两种顺序的操作 PID。CI harness 显式设置 `junit_family=xunit1`，避免 xunit2 对这些属性发出兼容警告并确保机器可读证据进入上传 XML；对应 harness 参数有单元测试。

## 完整回归和证据

### 本地 SQLite

命令：`.venv/bin/python -m pytest -o addopts='' services/cloud/tests -q`

结果：**123 passed、51 skipped、0 failed、34 warnings**。51 个跳过项依赖专用 PostgreSQL 后端。34 条为现有 AnyIO/Starlette 与 SQLite datetime adapter 弃用警告；没有新增 `record_property` 警告。

本机 PostgreSQL harness 曾明确因 Docker daemon 不可用而拒绝启动，不回退 SQLite。PostgreSQL 结果只采用以下真实 GitHub Actions PostgreSQL 17 job，不将本地或旧 head 结果冒充为本次验证。

### GitHub Actions：修复代码 head

[Run #72](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951103778)的 PR run metadata 记录 `head_sha=f4ab838fb1a438d8f927a90fcb3746a9ce0188da`、base `main=d7f1eedb13ac0f44abb738bc6e8b4d0d38d7766d`；SQLite 与 PostgreSQL 17 job 均 `success`。

| Job | 最终结果 |
| --- | --- |
| SQLite | **123 passed、51 skipped、0 failed、34 warnings**；与本地全量结果一致。 |
| PostgreSQL 17 | **173 passed、1 SQLite 专属 skipped、0 failed、1 warning**；ledger 为 `shared=122, postgresql=51`。唯一警告为既有 AnyIO/Starlette `BlockingPortal` 弃用警告；本次新增的 JUnit 属性警告已消除。 |

- PostgreSQL harness run id：`c612041148906b9a`；主执行 `result=passed`、`cleanup=removed`。
- CI `always` 清理再次检查同一容器：`status=absent`、`cleanup=absent`、`result=passed`、`exit_code=0`。
- PostgreSQL job 原始日志：[job 130295342230](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951103778/job/130295342230)。JUnit、验证摘要和脱敏实例日志位于 [artifact 13825470202](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42951103778/artifacts/13825470202)，SHA-256：`294c672d073e977acb667333c0e16f6a6488145a76c3f8fc6ce12b30cd47c7ea`，artifact metadata 的 `head_sha` 与修复代码 head 一致。
- run #71（head `664a7eb`）在完整双后端套件通过后暴露了两条 JUnit xunit2 属性兼容警告；已针对性改为 xunit1，并由 run #72 重跑完整两种后端。run #71 不作为最终证据。

### 静态与契约检查

| 检查 | 结果 |
| --- | --- |
| OpenSpec Change strict：`openspec validate implement-cloud-edge-device-foundation --strict --json` | 1/1 passed，0 issues。 |
| 主规格 strict：`openspec validate --specs --strict --json` | `cloud-identity` 1/1 passed，0 issues；未修改主规格。 |
| OpenAPI 与实现 | FastAPI 当前生成的 OpenAPI JSON 与 `docs/contracts/openapi.json` 完全相等。 |
| Markdown 相对链接 | 扫描 OpenSpec、`docs/contracts`、`docs/verification` 下 33 份 Markdown 和 124 个相对链接，0 个失效。保留既有未跟踪 `docs/workflow/`，不将其作为本次变更范围。 |
| Git whitespace | `git diff --check` 通过。 |
| Apply 任务状态 | `tasks.md` 保持 14/14；未将本次修复记作新的 Apply 任务。 |
| PR/base 边界 | PR #4 保持 Draft；`main` 未改动。 |

## Notion 与停止边界

Notion 原 P1 Edge Node 任务及新版工程入口追加 W1/W2/W3 修复说明、修复代码 head、完整双后端 CI 与容器清理结果；其他 P0/P1 任务属性和状态不变。S1–S5 继续记录为后续建议，未纳入实现。

这份记录只交付定向修复和 Apply 后回归。首次 `verification.md` 的 WARNING 仍是历史独立审阅结果；本记录不自行关闭 WARNING，也不构成新一轮 Verify。PR 保持 Draft，等待负责人再次授权独立 Verify；未执行 Archive、主规格同步、Merge 或下一项业务 Change。
