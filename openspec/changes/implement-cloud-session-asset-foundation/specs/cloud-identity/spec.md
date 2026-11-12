# Spec Delta

## MODIFIED Requirements

### Requirement: Isolated database validation
测试 SHALL 使用专用临时数据库执行新版迁移，应用启动 MUST 不自动迁移旧库或外部数据库。PostgreSQL 验证 SHALL 只连接本次编排创建的可销毁实例；业务表与迁移版本表 MUST 位于专用schema（默认 `swim_cloud`）。迁移身份与应用身份 MUST 分离，普通测试 MUST 不把业务连接配置作为测试目标；成功或失败时均 MUST 只清理本次实例并显式报告。

#### Scenario: Initialization points to external database

- **WHEN** 本地开发初始化命令的目标不是新版 var 目录内的 SQLite 文件
- **THEN** 命令 MUST 拒绝运行且不连接或迁移该目标

#### Scenario: PostgreSQL target is not owned by this run

- **WHEN** 测试入口收到任意外部连接地址、缺少本次编排创建的实例标识，或实例的归属校验（容器标识、运行标识、回环端口）不一致
- **THEN** 编排入口与 PostgreSQL 测试环境初始化 MUST 各自在数据库连接或迁移前拒绝执行；即使环境变量格式完整合法，初始化仍 MUST 核验 Docker 实际容器 ID、名称、运行/owner 标签及 5432/tcp 回环端口映射，不回退到业务库，也不因数据库名带测试前缀而放行

#### Scenario: Restricted application identity

- **WHEN** PostgreSQL API测试连接迁移身份和应用身份并执行正常业务及权限探测
- **THEN** 两种身份 MUST 通过连接级 `search_path` 定位专用schema，不得在连接池上依赖会话级 `SET` 残留；应用身份不得拥有超级用户、建库、建角色、表或schema所有权、临时表或绕过行级安全的权限，且不得是迁移身份的成员；正常授权业务 MUST 可用，应用身份只 SHALL 获该schema的 `USAGE`、已批准15张业务表的 `SELECT`/`INSERT`/`UPDATE`/`DELETE` 和迁移版本表的 `SELECT`，不得对未批准表授予DML，且 MUST 无法建表、临时建表、`CREATE SCHEMA`、改表、建索引、建角色、建库、`TRUNCATE`、写迁移版本表或通过 `SET ROLE` 切换为迁移身份；已批准15张业务表指原六表 `users`/`auth_sessions`/`tenants`/`tenant_memberships`/`sites`/`site_memberships`、Cloud Edge Registry 四表 `edge_nodes`/`devices`/`edge_credentials`/`idempotency_records` 与 `training_sessions`/`video_assets`/`upload_sessions`/`session_read_grants`/`asset_read_grants`

#### Scenario: Failure during test execution

- **WHEN** PostgreSQL 环境初始化、连接、迁移或测试失败，或运行收到可捕获的终止信号
- **THEN** 测试入口 MUST 返回失败并只清理本次实例与数据，清理结果 MUST 显式报告；主入口及 CI 清理入口仅在确认 removed 或 absent 时允许清理成功，其他状态 MUST 传播非零退出码且摘要 result/cleanup/exit_code MUST 一致；Docker daemon/权限错误 MUST NOT 当作 absent；对无法捕获的强制终止，文档 MUST 提供按运行标识逐步确认后清理的恢复流程，且 MUST NOT 建议或执行全局容器清理

#### Scenario: Unapproved table is not automatically granted

- **WHEN** 测试schema中出现未列入当前批准集合的额外表，迁移或应用权限初始化完成
- **THEN** 应用身份 MUST 无权访问该额外表，批准表的正常业务 MUST 可用，原DDL/版本表写入/角色切换拒绝及真实容器归属/清理保证 MUST 全部保留

### Requirement: PostgreSQL schema integrity
云端基础 SHALL 在专用 PostgreSQL 环境通过真实迁移建立已发布六表基线、Cloud Edge Registry 四表与本次采集业务五表，保持各对应版本模型的字段、主键、唯一性、外键、索引与级联语义，且迁移版本表 MUST 位于测试 schema 内并与模型反射一致。数据库 MUST 拒绝无效归属或重复记录；迁移失败 MUST 不留下被误报为可用的部分基线。

#### Scenario: Empty database migration and round trip

- **WHEN** 空 PostgreSQL 测试库升级至已发布六表基础版本20261106_0001，再降级并重新升级该基础版本
- **THEN** 六表、版本标记与版本表所在 schema MUST 与模型一致，重新升级后正常注册、机构和场馆流程 MUST 可用

#### Scenario: Invalid cross tenant reference

- **WHEN** 场馆授权同时引用不同机构的场馆或机构成员
- **THEN** PostgreSQL MUST 拒绝写入，回滚后 MUST 无错误授权残留

#### Scenario: Unique keys and cascading removal

- **WHEN** 创建重复邮箱、机构标识、同机构同名场馆、成员或授权，或者删除其父记录
- **THEN** 重复写入 MUST 被拒绝，允许的父记录删除 MUST 按已声明级联关系删除子记录，不涉及该父记录的其他机构记录 MUST 保留；删除全局账号时，其跨机构成员关系亦按级联删除

#### Scenario: Interrupted migration transaction

- **WHEN** 测试在迁移事务中制造可控失败
- **THEN** 本次迁移的部分 DDL 和版本推进 MUST 回滚，测试 MUST 记录失败及清理结果，且 MUST NOT 通过修改已发布迁移脚本来制造或规避该失败

#### Scenario: Approved incremental migration preserves foundation

- **WHEN** 含六表基础数据的隔离PostgreSQL库依次升级到 Cloud Edge Registry revision 与本次新 revision，再降级到20261106_0001并重新升级
- **THEN** 原六表数据与既有31个操作 MUST 保持可用；head的15张表、复合归属约束、schema落点、版本标记与当前模型 MUST 一致；新增迁移失败 MUST 回滚DDL/版本推进且不遗留半成品，不得改写初始或已发布迁移或连接外部数据库

#### Scenario: Stepwise downgrade keeps earlier increments

- **WHEN** 从本次 head 降级到 Cloud Edge Registry revision
- **THEN** 本次新增的五张表 MUST 被移除，其前已发布的十张表、数据与版本标记 MUST 保持可用，重新升级后五张表 MUST 按当前模型重建

#### Scenario: Restrict blocks history loss through parents

- **WHEN** 已存在 Session 或 Asset 的场馆或机构被请求删除
- **THEN** 数据库 MUST 以受限外键拒绝该删除，且 MUST NOT 级联清除历史 Session、Asset 或授权记录
