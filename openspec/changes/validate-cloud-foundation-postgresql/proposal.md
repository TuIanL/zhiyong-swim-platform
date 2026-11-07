# Proposal

## Why

账号、机构与场馆基线及文档已随 PR #1 合入 `main`（`4968750a321c0a9e282f80fdd823c1876ee1f2fe`），但现有22项历史测试只覆盖 SQLite，尚无 PostgreSQL 的迁移、权限、时区或事务运行证据。Notion 新版入口和已归档基线均将独立 PostgreSQL 验证列为下一步，需要先建立可重复、可销毁且使用非特权应用身份的验证闭环。

本提案日期为2026-11-07（Asia/Shanghai），阶段为 propose；以下均为待评审方案，未获 apply、verify、archive 或本 PR 合并授权。

## What Changes

- 增加显式启用的 PostgreSQL 17 专用测试环境与 CI job；每次运行创建独立临时容器和数据库，迁移身份与普通应用身份分离，失败也清理本次资源，禁止接受任意外部数据库作为测试目标。
- 在真实 PostgreSQL 执行现有六表迁移，核对 revision、字段、主外键、唯一性、显式索引和级联；验证降级/重新升级及迁移失败回滚，不修改已发布初始 revision 来掩盖问题。
- 复用云端基础 API 用例，补齐当前 owner/admin/coach/athlete、匿名及非成员的权限组合；验证跨机构资源、授权撤销、角色降级、成员移除和连接复用，无新增角色政策。
- 验证 UTC 与非 UTC 数据库会话下的时间瞬间、会话过期、登录锁定，以及唯一冲突回滚和并发登录行锁。若现有锁定时间比较在 PostgreSQL 非 UTC 会话下失败，修正其时区归一化并保留 SQLite 回归，不扩展锁定策略。
- 为 `cloud-identity` 增加 PostgreSQL 运行与验证保证，扩展隔离测试要求；当前 API、SQLite 本地初始化限制和启动不迁移原则保持兼容。
- 明确 RLS 本轮不启用，应用层隔离与数据库行级隔离证据分开。记录后续 RLS 的表/操作、可信上下文、连接池、缺失上下文、表 owner/BYPASSRLS 与全局身份路径评审门槛。
- 在同一 change、分支、PR 和既有 Notion 任务内持续记录实施证据及限制；本轮仅交付规划材料。

## Capabilities

### New Capabilities

无。验证对象属于已有账号、机构与场馆能力，不新增近义能力目录。

### Modified Capabilities

- `cloud-identity`：扩展 `Isolated database validation`，规定 PostgreSQL 测试目标的创建、身份、隔离和清理；新增 PostgreSQL 六表一致性、现有授权行为与时间/事务的运行保证。使用规格增量，不设置 `skip_specs`，主规格仅在后续获授权的归档流程同步。

## Impact

- 预期 apply 范围：`services/cloud/tests/`、专用测试编排脚本/配置、`.github/workflows/ci.yml`，以及必要的 `api.py` 时间归一化修正；现有 SQLAlchemy/psycopg 依赖已声明，暂不提议升级运行依赖。
- 现有六表和初始迁移作为验证对象；不新增业务表、不扩大 `init-db`、不改场馆 PATCH 语义，不接入旧库、生产数据库或真实账号。
- 后续文档：测试运行说明、PostgreSQL 验证报告、RBAC覆盖映射与 RLS 决策草案；原始历史验证和已归档 change 保留原貌。
- 复用任务：[云端基础](https://www.notion.so/410f602574aa81c8bfa0e4728a58b737)、[独立运行环境与隔离测试](https://www.notion.so/410f602574aa81e8a757def927b364df)、[数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)、[RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e)。本 change 只推进这些任务的 PostgreSQL 子范围，不将总体任务标为完成。
- 排除 RLS 实施、生产数据库选型/部署、压测/SLA、审计、平台管理员、所有权转移、Pool/Lane、Web、Edge、媒体和模型。PostgreSQL 17 只是本提案的测试目标，不是生产选型结论。
- 本机 Docker CLI 存在，但当前 daemon 不可用；propose 不启动服务或连接数据库。apply 可使用专用 CI 实例获得真实证据，本机未运行时必须单列限制，不能跳过 PostgreSQL job 后宣称通过。
