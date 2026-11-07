# Design

## Context

动机见[提案](proposal.md)。本文为2026-11-07的待评审设计，基于 `main@4968750`；规范目标见[cloud-identity增量](specs/cloud-identity/spec.md)。

| 已检查的事实 | 对设计的影响 |
| --- | --- |
| `tests/conftest.py` 每例生成临时SQLite，执行真实Alembic迁移 | 保留默认SQLite路径，增加显式PostgreSQL执行入口，不读取通用DATABASE_URL |
| `database.py` 非SQLite走普通SQLAlchemy引擎；psycopg 3.2.3已声明 | 先复用依赖和工厂，无需引入生产数据库管理框架 |
| `migrate.py`显式升级，`main.py`启动不建表，`cli.py`仅接受新版var内SQLite | PostgreSQL测试编排独立负责迁移，不放宽生产/开发CLI |
| 六张业务表，UUID用String(36)，时间列声明timezone=True，无role CHECK/RLS | 检验既有DDL，不迁入旧库，不换UUID类型或暗加角色政策 |
| 登录使用行锁；锁定比较把读取时间直接replace(tzinfo=UTC) | 非UTC的aware值可能被错误重标时区；需要真实PG场景复现与最小修正 |
| API的membership/site_access按每请求查询；当前测试主要覆盖coach | 增加athlete、管理角色例外、降级及连接复用证据 |
| CI仅运行默认pytest；本机Docker daemon不可用 | CI成为可复现PG执行路径；本机未运行必须明示，不能静默skip |

Notion的[云端模型页](https://www.notion.so/410f602574aa8170b565f7fc4c5eab30)仍是早期草稿，包含场馆管理员、RLS等未来设计；本次依据已合并六表和RBAC契约，不把那份草稿当作已实施政策。[基线准入](../../../docs/baseline/cloud-foundation.md)要求先验证迁移、时间/事务和应用层隔离，再独立评审RLS。

## Goals / Non-Goals

**Goals:** 从空的、可销毁的PostgreSQL实例验证现有业务闭环；用普通应用数据库身份运行API；同一套可移植测试在SQLite与PostgreSQL执行；每项结论可追溯至场景、提交、环境和实际结果。

**Non-Goals:** 不实现RLS、生产连接管理或生产迁移入口；不承诺全数据库版本兼容、生产性能或所有并发权限竞态。本轮重点是现有身份和机构/场馆契约，完整平台安全仍由更广任务跟进。

## Decisions

### D1：独立、显式的PostgreSQL 17测试编排

计划新增 `scripts/test-postgresql.py` 作为本机与CI共同入口，使用Docker CLI创建唯一标识的临时容器（名称/label包含随机run id），仅绑定本机回环地址随机端口，数据放临时内存卷，不挂载项目、宿主业务数据或旧目录。测试镜像固定PostgreSQL 17的具体补丁标签及镜像digest；apply时解析可用镜像并提交锁定配置，记录server_version、架构与digest，不声称17是生产选型或最新大版本。

入口不提供任意数据库URL参数；忽略业务 `SWIM_CLOUD_DATABASE_URL`，内部从本次创建的container ID和inspect结果构造连接。仅内部子进程获得测试连接信息，凭据随机生成且不进命令日志、报告或Git。连接前核验本次容器ID、label与目标端口；仅数据库名有test前缀不构成安全凭据。

普通pytest仍只运行SQLite。PostgreSQL入口显式选择后，无法启动/连接、身份不符、无用例或必需用例被跳过即非零退出。共享API测试按后端运行，PG专用用例独立标记；SQLite特有初始化用例和安装回归仍保留，不拿跳过的PG用例凑通过数。

用try/finally及终止信号处理清理本次精确container ID，禁止全局prune；CI另用always清理步骤兜底。SIGKILL/宿主崩溃无法保证脚本即时清理，文档提供按本次ID确认的恢复命令；CI临时runner销毁提供最后边界，清理错误不得隐瞒。

替代：接受外部DSN更方便，但无法证明未指向业务库；长期共享PG会残留测试数据；仅SQLite或模拟PG驱动无法提供方言和锁证据，均不采用。

### D2：迁移身份与API身份彻底分离

实例管理员仅用于初始化数据库/角色与销毁实例，不执行API断言。迁移角色拥有测试schema并执行Alembic；应用角色为LOGIN、NOSUPERUSER、NOCREATEDB、NOCREATEROLE、NOBYPASSRLS，非表owner且不属于迁移角色，不允许SET ROLE到迁移角色。撤销PUBLIC对测试schema的CREATE和目标数据库的TEMPORARY，应用仅有CONNECT、USAGE、六表DML及版本表SELECT；无schema CREATE、临时建表、DDL、TRUNCATE或版本表写权限。身份探测同时验证普通表与临时表创建被拒；数据库默认TEMPORARY授权依据[官方权限文档](https://www.postgresql.org/docs/17/ddl-priv.html)。UUID为应用产生，不新增序列权限。

每个用例创建本次实例内的唯一空数据库，迁移完再给应用角色授权，API与业务断言走应用连接。fixture管理身份仅用于建库、迁移、重置和必要的catalog检查。用例结束先关闭连接池，再精确销毁其测试库；整次结束删除临时实例。身份探测必须覆盖角色属性、表owner、有效角色成员关系及实际拒绝DDL/提权操作，失败事务随后回滚。

本轮未启用RLS：具有表DML权限的应用身份直接执行无过滤SQL仍可能读到其他机构数据，必须如实记录。因此非特权身份测试证明权限分离和应用授权，不证明数据库行级隔离。

替代：全部用postgres超级用户虽简单却无法验证应用最小权限；单一拥有表的账号也不能为未来RLS提供可信基线。

### D3：现有迁移的真实验证与失败证据

保持 `20261106_0001` 不变；用迁移角色在空库upgrade，断言revision，模型与反射schema一致，另显式检查字段类型/空值、所有主键/唯一键、6条外键（含2条复合外键）、3个显式索引及CASCADE。实际目录中的外键数以迁移代码逐条映射为准，不用SQLAlchemy diff为空替代行为验证。

数据断言包括重复email/slug、同机构同名场馆拒绝而不同机构同名允许、重复成员/授权拒绝、两种错误复合外键、删除用户/机构/场馆/机构成员的相应级联及无关机构保留。直接数据库删除用于验证DDL，不新增删除业务API。

单独空库做downgrade base、确认六表移除、upgrade及基础HTTP冒烟。失败测试在测试进程中对迁移执行注入异常（例如第一张表创建后），不编辑正式revision；检查DDL与版本推进回滚，再销毁库。保留启动空库不建表、ready=503；迁移后ready=200。发现结构不兼容时先报告；需要新增迁移或改变领域约束必须更新提案，不能改写旧revision绕过失败。

替代：只比较metadata不能发现级联/事务差异；只测upgrade不能证明失败清理和回退路径。

### D4：当前角色矩阵成为可执行场景

复用 [RBAC契约](../../../docs/contracts/cloud-rbac.md) 的合法请求前提和错误优先级。测试清单必须对17个业务operation逐项标记适用身份组合，两个health/ready单列；不机械生成无意义的笛卡尔积。

| 场景组 | 最少断言 |
| --- | --- |
| 注册/登录/me/退出 | 特权字段拒绝；token仅存摘要；停用、过期、退出拒绝；公开端点与受保护端点分别处理 |
| 机构创建/列表/详情 | 创建者owner且原子提交；用户多机构列表仅所属；非成员详情404 |
| 成员列表/新增/改角色/移除 | owner可管理非owner，admin仅可列，coach/athlete拒绝；owner保护409；无身份401、外机构404 |
| 场馆创建/修改/列表/详情 | owner/admin全机构；coach和athlete分别执行已授权/未授权；普通角色写拒绝；同账号跨两机构错配site ID仍拒绝 |
| 场馆授权/撤销 | 管理角色可操作且目标必须为机构成员；重复授权409；撤销缺失授权204；普通角色拒绝 |
| 权限变化 | 普通授权撤销、成员移除即时生效；admin降级后只见明确授权；admin/owner撤销显式授权仍保留机构权限 |
| 连接复用 | 测试引擎pool_size=1/max_overflow=0，确认物理连接被复用；交替A/B/匿名与409后成功请求，结果与当前身份一致 |

越权业务写入与唯一冲突同时检查无非预期业务数据变化；失败登录按现有计数/锁定策略验证，不要求账号记录不变。读取同时检查返回ID集合及不泄露其他机构内容。涉及状态变化的组合用独立fixture，避免先前授权改变后续断言前提。当前无tenant会话变量，连接复用测试验证请求事务/身份不残留；未来RLS的SET LOCAL测试不提前伪造。

替代：只参数化coach为athlete能填一处缺口，但无法覆盖管理例外、成员管理及跨机构写入；本提案按当前契约的适用格逐项追溯。

### D5：时间瞬间、唯一冲突与并发锁

数据库会话分别设UTC和Asia/Shanghai，读取相同时间瞬间；服务时钟在测试中固定，断言过期/锁定截止前、相等、之后，不依赖sleep碰巧命中边界。PostgreSQL将带时区时间按绝对瞬间保存并按会话时区输出，依据[官方日期类型文档](https://www.postgresql.org/docs/17/datatype-datetime.html)。

现有 `locked_until.replace(tzinfo=UTC)` 对aware非UTC值是静态可见风险，尚未运行证明。本次允许的最小修正是aware值用astimezone(UTC)，SQLite返回的naive值按已有UTC约定补tzinfo；以先失败后通过的用例确认，不改变五次/十五分钟策略、token或API形状。

并发用独立连接/Session、同步屏障和有界超时；相同邮箱/slug/场馆名应一201一409，无部分owner或重复记录，失败之后另一合法请求成功。五个并发错误密码登录后失败数5且锁定生效；另用持锁连接和第二登录请求证明锁等待/释放（有界等待与事件同步），不得把超时当通过。本范围不宣称解决撤销权限与同时写入等所有竞态。

替代：串行重放和仅UTC连接会掩盖时区与丢失更新问题；大量性能压测超出本次正确性目标。

### D6：CI结果与RLS决策分开

保留原SQLite job；新增PostgreSQL job使用D1同一入口，真实创建独立实例，不依赖GitHub secrets/业务凭据，不设置continue-on-error。输出脱敏JUnit、版本、权限探测、迁移/清理摘要及场景映射；PG必需测试零收集或skip应失败。CI job成功不自动修改仓库保护规则，也不等于用户批准本PR。

本提案建议先完成PG兼容验证，RLS后续单独提案；这个范围选择仍待用户apply接受。RLS待评审候选为tenants及三个租户归属表；users/auth_sessions是全局身份路径，不能直接强塞单tenant过滤。未来必须解决创建机构、机构列表、多机构成员、可信tenant/user上下文来源、各操作USING/WITH CHECK、缺失上下文拒绝、事务局部设置和池复用、表owner/FORCE RLS及BYPASSRLS绕过，并用真实非特权角色负向验证。官方说明表owner通常可绕过RLS，超级用户及BYPASSRLS角色始终可绕过，见[PostgreSQL RLS文档](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)。

apply发布 `docs/decisions/0002-postgresql-validation-and-rls-boundary.md`，标明本轮仅验证目标与RLS后续评审清单，不冒充RLS实施设计已批准。原Notion草稿保留，通过新版入口解释阶段差异。

### D7：任务、交付与证据映射

| 要求/范围 | 后续实现位置 | Notion既有任务 | 验收证据 |
| --- | --- | --- | --- |
| Isolated database validation | scripts/test-postgresql.py、tests夹具/安全入口测试 | [隔离测试](https://www.notion.so/410f602574aa81e8a757def927b364df) | 目标拒绝、身份检查、失败清理、SQLite不回退 |
| PostgreSQL schema integrity | tests/test_postgresql_schema.py | [数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6) | 迁移反射、约束/级联、降升与故障回滚 |
| PostgreSQL authorization parity | 共享基础测试与test_authorization_matrix.py | [RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e) | operation×适用角色/机构/场馆矩阵、池复用 |
| 时间和事务两项要求 | tests/test_postgresql_transactions.py；必要的api时间修正 | [云端基础](https://www.notion.so/410f602574aa81c8bfa0e4728a58b737) | 两时区边界、并发唯一冲突、计数/行锁 |
| Reproducible PostgreSQL validation evidence | CI、README、docs/verification/cloud-foundation-postgresql.md | 上述四任务 | 当前head CI、环境版本、JUnit、清理与未验证范围 |
| RLS边界 | ADR草案、验证报告 | 数据模型与RBAC | 明确未实施/未验证，后续评审条件 |

本轮propose四任务保持原状态（云端基础/隔离测试待验收，数据模型/RBAC进行中）；追加PostgreSQL子范围“规划齐备，实施未开始”。apply后按真实进度更新，保留原SQLite交付证据；不创建同名任务或把全平台任务完成。

## Risks / Trade-offs

- [没有本地Docker daemon] → 本轮不启动；apply使用专用CI路径，记录本机未运行；若CI也不可用则保留未验证，不能勾选运行任务。
- [容器清理失效] → 精确run id、finally/信号/CI兜底及残留恢复说明；不承诺在进程不可恢复终止时瞬时清理。
- [非特权身份被误当RLS] → 明确表权限和行隔离不同，报告直接SQL可跨机构的当前限制。
- [共享测试夹具引入外部连接] → 默认SQLite独立，PG URL只能由本次编排内部生成；安全拒绝测试证明不会连接任意地址。
- [并发测试不稳定] → 独立连接、屏障、有界超时与实际数据结果；没有实现保证时报告失败，不增大超时掩盖缺陷。
- [测试矩阵过大] → 依据现有operation和有效前提枚举适用格，报告缺项，不按测试总数推断全平台安全。

## Migration Plan

1. 本轮仅规划、严格结构校验、独立分支提交、草稿PR及Notion回链；不运行数据库、不改业务代码。用户提供的未跟踪工作流模板保留原状，不混入本PR。
2. 明确apply后实施D1–D6与任务清单；真实PG只使用新测试实例。发现超出时间兼容修正的领域/权限变化，先更新范围并取得对应授权。
3. 同一PR提交实现与真实结果；仅执行测试验证，不自动启动独立verify、archive或合并。后续这些阶段分别等待用户授权；主规格同步遵循归档流程。
4. 回退测试工具/CI采用正常revert，丢弃仅本次临时实例；业务默认SQLite及旧库均不受测试迁移影响。真实PG尚未通过时不能宣称云端生产可用。
