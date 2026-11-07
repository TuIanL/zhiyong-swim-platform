# Proposal

## Why

账号、机构与场馆基线及文档已随 PR #1 合入 `main`（`4968750a321c0a9e282f80fdd823c1876ee1f2fe`），但现有 22 项历史测试只覆盖 SQLite，尚无 PostgreSQL 的迁移、权限、时区或事务运行证据。Notion 新版入口和已归档基线均将独立 PostgreSQL 验证列为下一步，需要先建立可重复、可销毁且使用非特权应用身份的验证闭环。

本提案日期为 2026-11-07（Asia/Shanghai）。用户已于 2026-11-07 明确授权 apply；独立 verify、archive/主规格同步及本 PR 合并仍分别等待后续授权，不因 apply 自动推进。

## What Changes

- 增加显式启用的 PostgreSQL 17 专用测试环境与 CI job；每次运行创建独立临时容器和数据库，迁移身份与普通应用身份分离，失败也清理本次资源，禁止接受任意外部数据库作为测试目标。镜像锁定 PostgreSQL 17 具体补丁标签与**多架构 manifest list digest**，使本机 arm64 与 CI amd64 使用同一发布物并各自记录实际平台 digest。
- 明确测试 schema 落点：每个测试库使用专用 schema `swim_cloud`（不使用 `public`），迁移角色拥有该 schema，六张表与 `alembic_version` 均创建在其中；迁移角色和应用角色都以连接级 `options=-c search_path=swim_cloud` 定位，不在池化连接上执行 `SET`。应用角色只获得 schema 的 `USAGE`、六表 DML 与 `alembic_version` 的 `SELECT`。
- 在真实 PostgreSQL 执行现有六表迁移，核对 revision、schema 落点、字段、主外键、唯一性、显式索引和级联；验证降级/重新升级及迁移中途失败回滚，不修改已发布初始 revision 来掩盖问题。`CREATE DATABASE` / `DROP DATABASE` 使用独立管理员 autocommit 连接，不进入业务连接池。
- 明确 pytest 三层标记与执行选择：无标记为共享 API 用例、`sqlite` 为 SQLite 专属、`postgresql` 为 PG 专属；默认集合仍只跑 SQLite，PG job 必须同时实际执行共享与 PG 专属用例，零收集或必需场景被 skip 即失败。
- 复用云端基础 API 用例，补齐当前 owner/admin/coach/athlete、匿名及非成员的权限组合；验证跨机构资源、授权撤销、角色降级、成员移除和连接复用，无新增角色政策。
- 验证 UTC 与 Asia/Shanghai 数据库会话下的时间瞬间、会话过期、登录锁定，以及唯一冲突回滚和并发登录行锁。时区通过**库级 `TimeZone` 默认值**隔离（每变体独立测试库），避免 `SET TIME ZONE` 在连接池中残留；朴素与 aware 时间统一归一化到 UTC，若现有锁定比较在非 UTC 会话下失败，做最小修正并保留 SQLite 回归。
- 区分连接复用与并发测试的连接池配置：`pool_size=1` 只用于顺序复用证据，并发唯一写入、五次失败登录与持锁用例使用足够数量的独立连接，禁止共用以避免把池饥饿当通过。
- 明确 RLS 本轮不启用，应用层隔离与数据库行级隔离证据分开。记录后续 RLS 的表/操作、可信上下文、连接池、缺失上下文、表 owner/BYPASSRLS 与全局身份路径评审门槛。
- 为 `cloud-identity` 增加 PostgreSQL 运行与验证保证，扩展隔离测试要求；当前 API、SQLite 本地初始化限制和启动不迁移原则保持兼容。
- 统一清理要求：可捕获异常与终止信号必须精确清理本次实例；SIGKILL/宿主崩溃提供按 run id 的恢复流程；清理失败显式报告，禁止全局 `docker prune`。CI 增加 `pg_isready` 有界等待、失败日志收集、always 清理与脱敏 JUnit/环境证据上传。
- 在同一 change、分支、PR 和既有 Notion 任务内持续记录实施证据及限制。

## Capabilities

### New Capabilities

无。验证对象属于已有账号、机构与场馆能力，不新增近义能力目录。

### Modified Capabilities

- `cloud-identity`：扩展 `Isolated database validation`，规定 PostgreSQL 测试目标的创建、schema 与 `search_path` 落点、身份、隔离和清理；新增 PostgreSQL 六表一致性、现有授权行为与时间/事务的运行保证。使用规格增量，不设置 `skip_specs`，主规格仅在后续获授权的归档流程同步。

## Impact

- apply 范围：`services/cloud/tests/`、`scripts/test-postgresql.py`、`configs/postgresql-test-image.json`、`.github/workflows/ci.yml`，以及必要的 `api.py` 时间归一化修正；现有 SQLAlchemy/psycopg 依赖已声明，不升级运行依赖。
- 现有六表和初始迁移作为验证对象；不新增业务表、不扩大 `init-db`、不改场馆 PATCH 语义，不接入旧库、生产数据库或真实账号。
- 后续文档：测试运行说明、PostgreSQL 验证报告、RBAC 覆盖映射与 RLS 决策草案；原始历史验证和已归档 change 保留原貌。
- 复用任务：[云端基础](https://www.notion.so/410f602574aa81c8bfa0e4728a58b737)、[独立运行环境与隔离测试](https://www.notion.so/410f602574aa81e8a757def927b364df)、[数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)、[RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e)。本 change 只推进这些任务的 PostgreSQL 子范围，不将总体任务标为完成。
- 排除 RLS 实施、生产数据库选型/部署、压测/SLA、审计、平台管理员、所有权转移、Pool/Lane、Web、Edge、媒体和模型。PostgreSQL 17 只是本提案的测试目标，不是生产选型结论。
- 本机 Docker daemon 在 propose 阶段不可用；apply 已具备本机实例条件，并可另用专用 CI 实例交叉取证。任一环境未运行时必须单列限制，不能跳过 PostgreSQL job 后宣称通过。
