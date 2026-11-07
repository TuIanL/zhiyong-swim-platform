# cloud-identity 规格增量

## MODIFIED Requirements

### Requirement: Isolated database validation
测试 SHALL 使用专用临时数据库执行新版迁移，应用启动 MUST 不自动迁移旧数据库或外部数据库。PostgreSQL 验证 SHALL 显式启用并只连接本次测试编排创建的可销毁实例；迁移与应用身份 MUST 分离，应用身份不得拥有超级用户、建库、建角色、表所有者或绕过行级安全的权限。普通测试 MUST 不读取业务连接配置作为测试目标；运行结束或失败时 MUST 清理本次实例及其数据，且不得清理其他实例。

#### Scenario: Initialization points to external database
- **WHEN** 本地开发初始化命令的目标不是新版 var 目录内的SQLite文件
- **THEN** 命令 MUST 拒绝运行且不连接或迁移该目标

#### Scenario: PostgreSQL target is not owned by this run
- **WHEN** 测试入口收到任意外部连接地址或缺少本次编排创建的实例标识
- **THEN** 入口 MUST 在数据库连接或迁移前拒绝执行，不回退到业务库

#### Scenario: Restricted application identity
- **WHEN** PostgreSQL API 测试连接数据库并执行正常业务及权限探测
- **THEN** 正常授权业务 MUST 可用，应用身份 MUST 无法建表、改表、建角色、建库或切换为迁移身份

#### Scenario: Failure during test execution
- **WHEN** PostgreSQL 环境初始化、迁移或测试失败
- **THEN** 测试入口 MUST 返回失败并清理本次实例与数据，清理失败 MUST 显式报告，不能访问其他数据库补救

## ADDED Requirements

### Requirement: PostgreSQL schema integrity
云端基础 SHALL 在专用 PostgreSQL 环境通过真实迁移建立六张业务表，保持已发布模型的字段、主键、唯一性、外键、索引与级联语义。数据库 MUST 拒绝无效归属或重复记录；迁移失败 MUST 不留下被误报为可用的部分基线。

#### Scenario: Empty database migration and round trip
- **WHEN** 空 PostgreSQL 测试库升级至云端基础版本，再降级并重新升级
- **THEN** 六表和版本标记 MUST 与模型一致，重新升级后正常注册、机构和场馆流程 MUST 可用

#### Scenario: Invalid cross tenant reference
- **WHEN** 场馆授权同时引用不同机构的场馆或机构成员
- **THEN** PostgreSQL MUST 拒绝写入，回滚后 MUST 无错误授权残留

#### Scenario: Unique keys and cascading removal
- **WHEN** 创建重复邮箱、机构标识、同机构同名场馆、成员或授权，或者删除其父记录
- **THEN** 重复写入 MUST 被拒绝，允许的父记录删除 MUST 按已声明级联关系删除子记录，不涉及该父记录的其他机构记录 MUST 保留；删除全局账号时，其跨机构成员关系亦按级联删除

#### Scenario: Interrupted migration transaction
- **WHEN** 测试在迁移事务中制造可控失败
- **THEN** 本次迁移的部分 DDL 和版本推进 MUST 回滚，测试 MUST 记录失败及清理结果

### Requirement: PostgreSQL authorization parity
PostgreSQL 环境下账号、机构、成员与场馆 API SHALL 遵守现有授权契约，覆盖匿名、非成员及 owner/admin/coach/athlete；授权变化后的新请求 MUST 使用最新成员关系。连接复用或失败回滚 MUST 不使后续用户继承前一请求的权限。本要求验证应用层授权，不声明数据库 RLS 已提供隔离。

#### Scenario: Role and operation matrix
- **WHEN** 各角色使用结构合法、目标存在的请求访问机构、成员和场馆的查询及写操作
- **THEN** 响应 MUST 符合既有角色矩阵：受保护操作匿名返回401，指定tenant_id的资源对非机构成员返回404，角色权限不足返回403，owner降级或移除返回409；已登录账号创建新机构不要求既有成员关系，机构列表返回200且仅含所属机构（可为空）

#### Scenario: Explicit site access and management exception
- **WHEN** coach或athlete的场馆授权被撤销，或owner/admin的显式场馆授权被撤销
- **THEN** 普通角色 MUST 无法继续查询该场馆，owner/admin MUST 保留当前机构级场馆管理和访问权限

#### Scenario: Membership removal and role downgrade
- **WHEN** 普通成员被移除，或admin降为coach/athlete且没有场馆授权
- **THEN** 既有登录会话后续请求 MUST 立即遵守变更后的权限，不得依赖重新登录才生效

#### Scenario: Reused connection across identities
- **WHEN** 同一物理连接先后处理机构A用户、机构B用户、无身份请求，以及一次写入失败后的有效请求
- **THEN** 各请求 MUST 仅获取自身授权资源，失败事务 MUST 不污染后续请求，交叉使用机构和场馆ID MUST 被拒绝

### Requirement: Timezone independent authentication deadlines
身份认证 SHALL 按绝对时间瞬间判定会话过期和账号锁定，不受 PostgreSQL 会话时区影响。到达过期时间的会话 MUST 被拒绝；锁定期间正确密码 MUST 被拒绝，锁定到期且账号活跃、密码正确时 MUST 可登录。

#### Scenario: Equivalent instants in different timezones
- **WHEN** 同一锁定截止或会话过期瞬间分别在UTC和非UTC数据库会话读取
- **THEN** 截止前、恰好截止和截止后的身份结果 MUST 一致，时间值 MUST 保持同一绝对瞬间

#### Scenario: SQLite compatibility
- **WHEN** 本地SQLite测试读取没有时区信息的既有UTC日期值
- **THEN** 会话和锁定行为 MUST 保持兼容，不改变现有锁定次数、时长或token格式

### Requirement: PostgreSQL transactional account operations
PostgreSQL 上注册、创建机构和场馆的唯一冲突 SHALL 返回既有409错误并完整回滚；同一账号的并发失败登录 MUST 不丢失失败计数，达到现有阈值后 MUST 生效锁定。每个请求使用独立事务，失败不得留下半完成机构或阻断后续合法操作。

#### Scenario: Concurrent unique writes
- **WHEN** 两个独立请求并发写入相同邮箱、机构标识或同机构场馆名
- **THEN** MUST 只有一个成功，另一个返回409，数据库只保留一条有效记录；机构创建 MUST 同时具有owner成员关系，失败后合法写入 MUST 仍可成功

#### Scenario: Concurrent failed logins
- **WHEN** 一个活跃、失败计数为0且无锁定截止值的账号收到五个并发错误密码登录请求
- **THEN** 请求 MUST 全部返回401，最终失败计数 MUST 为5且锁定已生效，锁定期内正确密码 MUST 仍返回401

### Requirement: Reproducible PostgreSQL validation evidence
PostgreSQL 验证交付 SHALL 记录代码提交、数据库和驱动版本、实际应用身份权限、执行命令、用例结果及清理结果。CI中的PostgreSQL验证 MUST 实际运行；缺少环境、连接失败、零用例或必需场景被跳过 MUST 不得产生验证通过结论。

#### Scenario: Missing PostgreSQL prerequisites
- **WHEN** 显式请求PostgreSQL测试但专用实例无法创建、连接或收集到必需用例
- **THEN** 测试 MUST 失败并说明原因，不能回退到SQLite或以跳过冒充通过

#### Scenario: Evidence bound to a revision
- **WHEN** 发布本次验证结论
- **THEN** 报告 MUST 区分本机与CI、SQLite与PostgreSQL、当前与历史提交，并将RLS及生产部署标为未验证
