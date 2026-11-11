# cloud-identity Specification

## Purpose
为新版游泳智能视频分析平台提供可独立运行和验证的账号、机构成员与场馆授权基础。所有资源访问必须经过服务端身份及机构归属检查，避免继承旧原型的公开媒体、任意角色和资源标识授权缺口。

## Requirements

### Requirement: Ordinary account registration
公开注册 SHALL 仅创建无机构特权的账号，拒绝用户自报的角色、机构归属与激活状态字段。

#### Scenario: Privileged registration input
- **WHEN** 公开注册请求包含 role=admin 或 tenant_id
- **THEN** 服务 MUST 拒绝请求且不创建特权账号

### Requirement: Revocable sessions
身份认证 SHALL 检查会话有效期、撤销状态与账号激活状态；数据库 MUST 不保存原始 bearer token。

#### Scenario: Logout revokes current session
- **WHEN** 用户退出当前会话后继续使用该 token
- **THEN** 服务 MUST 返回401

### Requirement: Tenant resource isolation
机构列表与详情 SHALL 仅返回当前用户拥有成员关系的机构，其他机构资源不可通过猜测ID访问。

#### Scenario: Another tenant identifier
- **WHEN** 用户请求不属于其授权范围的机构或场馆
- **THEN** 服务 MUST 拒绝访问且不返回资源内容

### Requirement: Explicit site scope
非管理角色 SHALL 仅能访问显式授权的场馆；场馆授权 MUST 同时满足用户与场馆属于同一机构。

#### Scenario: Removed institution member
- **WHEN** 所有者移除某机构成员
- **THEN** 其场馆授权 MUST 失效且不能继续访问该机构资源

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
- **THEN** 两种身份 MUST 通过连接级 `search_path` 定位专用schema，不得在连接池上依赖会话级 `SET` 残留；应用身份不得拥有超级用户、建库、建角色、表或schema所有权、临时表或绕过行级安全的权限，且不得是迁移身份的成员；正常授权业务 MUST 可用，应用身份只 SHALL 获该schema的 `USAGE`、原六张与本Change新增四张批准业务表的 `SELECT`/`INSERT`/`UPDATE`/`DELETE` 和迁移版本表的 `SELECT`，不得对未批准表授予DML，且 MUST 无法建表、临时建表、`CREATE SCHEMA`、改表、建索引、建角色、建库、`TRUNCATE`、写迁移版本表或通过 `SET ROLE` 切换为迁移身份

#### Scenario: Failure during test execution
- **WHEN** PostgreSQL 环境初始化、连接、迁移或测试失败，或运行收到可捕获的终止信号
- **THEN** 测试入口 MUST 返回失败并只清理本次实例与数据，清理结果 MUST 显式报告；主入口及 CI 清理入口仅在确认 removed 或 absent 时允许清理成功，其他状态 MUST 传播非零退出码且摘要 result/cleanup/exit_code MUST 一致；Docker daemon/权限错误 MUST NOT 当作 absent；对无法捕获的强制终止，文档 MUST 提供按运行标识逐步确认后清理的恢复流程，且 MUST NOT 建议或执行全局容器清理

#### Scenario: Unapproved table is not automatically granted
- **WHEN** 测试schema中出现未列入当前批准集合的额外表，迁移或应用权限初始化完成
- **THEN** 应用身份 MUST 无权访问该额外表，批准表的正常业务 MUST 可用，原DDL/版本表写入/角色切换拒绝及真实容器归属/清理保证 MUST 全部保留

### Requirement: PostgreSQL schema integrity
云端基础 SHALL 在专用 PostgreSQL 环境通过真实迁移建立已发布六表基线及本Change明确新增的四张表，保持各对应版本模型的字段、主键、唯一性、外键、索引与级联语义，且迁移版本表 MUST 位于测试 schema 内并与模型反射一致。数据库 MUST 拒绝无效归属或重复记录；迁移失败 MUST 不留下被误报为可用的部分基线。

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
- **WHEN** 含六表基础数据的隔离PostgreSQL库升级到本Change新revision，再降级到20261106_0001并重新升级
- **THEN** 原六表数据与19操作 MUST 保持可用；head新增表、复合归属约束、schema落点、版本标记与当前模型 MUST 一致；新增迁移失败 MUST 回滚DDL/版本推进且不遗留半成品，不得改写初始迁移或连接外部数据库

### Requirement: PostgreSQL authorization parity
PostgreSQL 环境下账号、机构、成员与场馆 API SHALL 遵守现有授权契约，覆盖匿名、非成员及 owner/admin/coach/athlete；授权变化后的新请求 MUST 使用最新成员关系。连接复用或失败回滚 MUST 不使后续用户继承前一请求的权限。验证连接复用与验证真实并发的用例 MUST 使用各自独立的连接配置：复用证据只允许在单个物理连接上按顺序发起请求，并发写入与行锁场景 MUST 使用足够数量的独立连接，不得以连接不足导致的等待或超时作为通过。本要求验证应用层授权，不声明数据库 RLS 已提供隔离。

#### Scenario: Role and operation matrix
- **WHEN** 各角色使用结构合法、目标存在的请求访问机构、成员和场馆的查询及写操作
- **THEN** 响应 MUST 符合既有角色矩阵：受保护操作匿名返回 401，指定 `tenant_id` 的资源对非机构成员返回 404，角色权限不足返回 403，owner 降级或移除返回 409；已登录账号创建新机构不要求既有成员关系，机构列表返回 200 且仅含所属机构（可为空）

#### Scenario: Explicit site access and management exception
- **WHEN** coach 或 athlete 的场馆授权被撤销，或 owner/admin 的显式场馆授权被撤销
- **THEN** 普通角色 MUST 无法继续查询该场馆，owner/admin MUST 保留当前机构级场馆管理和访问权限

#### Scenario: Membership removal and role downgrade
- **WHEN** 普通成员被移除，或 admin 降为 coach/athlete 且没有场馆授权
- **THEN** 既有登录会话后续请求 MUST 立即遵守变更后的权限，不得依赖重新登录才生效

#### Scenario: Reused connection across identities
- **WHEN** 同一物理连接按顺序先后处理机构 A 用户、机构 B 用户、无身份请求，以及一次写入失败后的有效请求
- **THEN** 各请求 MUST 仅获取自身授权资源，失败事务 MUST 不污染后续请求，交叉使用机构和场馆 ID MUST 被拒绝，且测试 MUST 证明确实只使用了该单一物理连接

### Requirement: Timezone independent authentication deadlines
身份认证 SHALL 按绝对时间瞬间判定会话过期和账号锁定，不受 PostgreSQL 会话时区影响。到达过期时间的会话 MUST 被拒绝；锁定期间正确密码 MUST 被拒绝，锁定到期且账号活跃、密码正确时 MUST 可登录。时区差异 MUST 通过各变体独立的连接配置隔离，不得依赖在同一连接上临时设置会话时区，以免该设置经连接复用影响后续请求。SQLite 的无时区日期值 MUST 按既定 UTC 约定解释，PostgreSQL 的带时区值 MUST 保留其绝对瞬间。

#### Scenario: Equivalent instants in different timezones
- **WHEN** 同一锁定截止或会话过期瞬间分别在 UTC 和非 UTC 数据库会话读取
- **THEN** 截止前、恰好截止和截止后的身份结果 MUST 一致，时间值 MUST 保持同一绝对瞬间，且后续复用连接的请求 MUST NOT 继承先前会话的时区设置

#### Scenario: SQLite compatibility
- **WHEN** 本地 SQLite 测试读取没有时区信息的既有 UTC 日期值
- **THEN** 会话和锁定行为 MUST 保持兼容，不改变现有锁定次数、时长或 token 格式

### Requirement: PostgreSQL transactional account operations
PostgreSQL 上注册、创建机构和场馆的唯一冲突 SHALL 返回既有 409 错误并完整回滚；同一账号的并发失败登录 MUST 不丢失失败计数，达到现有阈值后 MUST 生效锁定。每个请求使用独立事务，失败不得留下半完成机构或阻断后续合法操作。

#### Scenario: Concurrent unique writes
- **WHEN** 两个独立连接上的请求并发写入相同邮箱、机构标识或同机构场馆名
- **THEN** MUST 只有一个成功，另一个返回 409，数据库只保留一条有效记录；机构创建 MUST 同时具有 owner 成员关系，失败后合法写入 MUST 仍可成功

#### Scenario: Concurrent failed logins
- **WHEN** 一个活跃、失败计数为 0 且无锁定截止值的账号收到五个并发错误密码登录请求
- **THEN** 请求 MUST 全部返回 401，最终失败计数 MUST 为 5 且锁定已生效，锁定期内正确密码 MUST 仍返回 401

### Requirement: Reproducible PostgreSQL validation evidence
PostgreSQL 验证交付 SHALL 记录代码提交、数据库与驱动版本、实际运行平台架构与镜像摘要、实际应用身份权限、执行命令、用例结果及清理结果。CI 中的 PostgreSQL 验证 MUST 实际运行共享 API 用例与 PostgreSQL 专属用例；缺少环境、实例未在限定时间内就绪、连接失败、零用例或必需场景被跳过 MUST 不得产生验证通过结论，也不得回退到 SQLite 冒充通过。证据材料 MUST 脱敏，不得包含数据库凭据。

#### Scenario: Missing PostgreSQL prerequisites
- **WHEN** 显式请求 PostgreSQL 测试但专用实例无法创建、未在有界时间内就绪、连接失败或收集到的必需场景为零
- **THEN** 测试 MUST 失败并说明原因，不能回退到 SQLite 或以跳过冒充通过

#### Scenario: Evidence bound to a revision
- **WHEN** 发布本次验证结论
- **THEN** 报告 MUST 区分本机与 CI、SQLite 与 PostgreSQL、当前与历史提交，并将 RLS 及生产部署标为未验证
