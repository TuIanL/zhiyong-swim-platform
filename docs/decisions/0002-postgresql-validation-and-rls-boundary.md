# ADR 0002：PostgreSQL 验证目标与 RLS 边界

- 状态：已实施（仅限**测试验证**范围）；RLS 与生产部署未批准
- 日期：2026-11-07
- 关联：change `validate-cloud-foundation-postgresql`、[验证报告](../verification/cloud-foundation-postgresql.md)、[RBAC 契约](../contracts/cloud-rbac.md)、PR #2

## 背景

云端基础（账号、机构、场馆六表）此前只有 SQLite 运行证据。SQLite 通过不能外推为 PostgreSQL 行为，更不能说明数据库行级隔离。本决策记录本轮为什么这样验证、边界在哪、以及 RLS 若要推进还缺什么。

## 决策

### 1. PostgreSQL 17 只是测试目标，不是生产选型

验证镜像锁定为 `postgres:17.11` 的多架构 manifest list digest（见 [`configs/postgresql-test-image.json`](../../configs/postgresql-test-image.json)）。锁定多架构清单而不是单平台清单，是因为本机 arm64 与 CI amd64 会解析出不同的单平台 digest；锁清单才能让两端使用同一发布物，同时运行摘要各自记录实际平台 digest、镜像 ID、`server_version` 与时区。

升级补丁版本需要同时更新锁定文件与验证报告，不自动跟随 `latest`。

### 2. 专用 schema，而不是 `public`

每个测试库使用 schema `swim_cloud`：

- 数据库归管理员所有，schema 归迁移角色所有，应用角色既不是表 owner 也不是 schema owner；
- 六张业务表与 `alembic_version` 都落在该 schema 内；
- `public` 对 `PUBLIC` 全部撤销，关闭默认路径。

选择专用 schema 而不是 `public` 的原因：`public` 在 PostgreSQL 15+ 属于 `pg_database_owner` 且默认对 `PUBLIC` 开放 USAGE，授权对象与默认权限纠缠，版本表落点也无法断言。

### 3. 身份定位 schema 用连接参数，不用 `SET`

两个角色都在连接串里带 libpq `options=-c search_path=swim_cloud`（只含该 schema）。好处是随连接建立生效、连接池每次新建物理连接都自动应用、归还时无需还原，也不存在残留。

对应的验证要求：`SHOW search_path` 与 `SHOW TimeZone` 必须等于预期值，并在多次池化请求后复验。

### 4. 应用身份是最小权限

| 对象 | 授予 | 明确不授予 |
| --- | --- | --- |
| 数据库 | `CONNECT` | `CREATE`、`TEMPORARY` |
| schema `swim_cloud` | `USAGE` | `CREATE`、所有权 |
| 六张业务表 | `SELECT`/`INSERT`/`UPDATE`/`DELETE` | `TRUNCATE`、`REFERENCES`、`TRIGGER`、DDL |
| `swim_cloud.alembic_version` | `SELECT` | 任何写操作 |

角色属性为 `LOGIN`、`NOSUPERUSER`、`NOCREATEDB`、`NOCREATEROLE`、`NOREPLICATION`、`NOBYPASSRLS`，且不与迁移角色存在成员关系。负向探测覆盖：普通建表、临时建表、`CREATE SCHEMA`、`CREATE INDEX`、`ALTER TABLE`、`TRUNCATE`、`CREATE DATABASE`、`CREATE ROLE`、版本表写、`SET ROLE`/`SET SESSION AUTHORIZATION`。

### 5. 时区隔离用库级默认值

两个时区变体各建一个独立测试库，建库时执行 `ALTER DATABASE … SET TimeZone`。**不在池化连接上执行 `SET TIME ZONE`**：该设置会随连接归还留在池里，污染后续请求，且难以在每条路径上还原。

服务时间归一化策略：带 `tzinfo` 的值 `astimezone(UTC)` 保留绝对瞬间，朴素值按既有 UTC 约定 `replace(tzinfo=UTC)`。`api.py` 的锁定比较已按此修正，理由与证据见验证报告。

### 6. 连接复用与并发用不同连接池

- 顺序连接复用：`pool_size=1`、`max_overflow=0`，只允许串行请求，用 `pg_backend_pid()` 证明只有一个物理连接；
- 真实并发（唯一冲突、五次失败登录、持锁等待）：独立 `pool_size=8`、`max_overflow=0`、显式 `pool_timeout`，并反向断言至少出现两个不同后端进程。

两者不得互相替代。用单连接池跑并发会把池饥饿伪装成业务失败；用大池跑复用则证明不了“同一连接”。

### 7. 清理与失败处理

- 清理在 `try/finally` 中按本次 run id 精确执行，删除前再次核对 label，不匹配则拒绝并记 `refused:*`；
- 安装 SIGINT/SIGTERM/SIGHUP 处理把信号转成异常以进入清理路径；
- 失败时在清理**之前**抓取实例日志并按本次随机密码脱敏；
- 清理状态不是 `removed`/`absent` 时，即使测试全绿也判失败；
- **禁止** `docker system prune` 或按镜像统删；
- SIGKILL/宿主崩溃/断电无法保证即时清理，恢复流程按 run id 逐条确认后删除。

## RLS 边界（未实施，未验证）

本轮**没有**创建任何 RLS policy，也没有证明行级隔离。应用身份拥有表级 DML 权限，直接执行无过滤 SQL 仍可读到其他机构的数据；这一点必须在报告与产品沟通中如实说明。

RLS 若要推进，需另行提案并解决以下评审门槛：

| 门槛 | 必须回答的问题 |
| --- | --- |
| 保护范围 | 哪些表、哪些操作受策略约束；`tenants` 与三个租户归属表是候选；`users`/`auth_sessions` 是全局身份路径，不能直接强塞单 tenant 过滤 |
| 上下文来源 | tenant/user 上下文由谁写入、如何防伪造；创建机构、机构列表、多机构成员这些跨租户路径如何表达 |
| 事务与连接池 | 用 `SET LOCAL` 还是连接参数；连接归还时如何保证不残留；池复用下的边界 |
| 缺失上下文 | 没有上下文时是拒绝全部、还是回退应用层过滤；两者不能混用而不声明 |
| 绕过路径 | 表 owner、`BYPASSRLS`、超级用户都能绕过策略；必须以真实非特权角色做负向验证 |
| 与现有授权的关系 | RLS 与应用层检查是叠加还是替代；错误码是否仍为 404/403 |

## 后果

- 新增维护面：一个编排脚本、一个锁定配置、四个测试文件、一个 CI job。日常 `python -m pytest` 行为不变。
- 已知限制：迁移脚本不管理对象授权，`downgrade` + `upgrade` 后必须重新授权（验证用例显式调用）；这一点在真实部署时需要单独的授权步骤或迁移。
- 本决策不改变生产数据库选型，不引入生产连接管理，也不代表整体安全验收完成。
