# Design

## Context

动机与范围见[提案](proposal.md)。本文为 2026-11-07 的设计，基于 `main@4968750`；规范目标见[cloud-identity 增量](specs/cloud-identity/spec.md)。用户已于 2026-11-07 明确授权 apply；独立 verify、archive/主规格同步与 PR 合并仍分别等待后续授权。

| 已检查的事实 | 对设计的影响 |
| --- | --- |
| `tests/conftest.py` 每例生成临时 SQLite，执行真实 Alembic 迁移 | 保留默认 SQLite 路径，增加显式 PostgreSQL 执行入口，不读取通用 `DATABASE_URL` |
| `database.py` 非 SQLite 走普通 SQLAlchemy 引擎，默认 `QueuePool`（5+10）；psycopg 3.2.3 已声明 | 先复用依赖和工厂；连接复用与并发需要两套显式池配置，不能共用一个 `pool_size=1` |
| `migrate.py` 显式升级，`main.py` 启动不建表，`cli.py` 仅接受新版 `var/` 内 SQLite；`env.py` 未指定 `version_table_schema` | PostgreSQL 测试编排独立负责建库与迁移，不放宽生产/开发 CLI；schema 落点由连接级 `search_path` 决定，不改 `env.py` |
| 六张业务表，UUID 用 `String(36)`，时间列声明 `timezone=True`，无 role CHECK/RLS；迁移默认落在连接默认 schema | 检验既有 DDL，不迁入旧库，不换 UUID 类型或暗加角色政策；测试改用专用 schema 以显式隔离 |
| `main.ready` 用不带 schema 限定的 `SELECT 1 FROM alembic_version` | 应用连接必须能通过 `search_path` 定位版本表，否则 ready 语义失真 |
| 登录使用行锁；锁定比较把读取时间直接 `replace(tzinfo=UTC)` | 非 UTC 的 aware 值会被错误重标时区；需要真实 PG 场景复现与最小修正 |
| API 的 membership/site_access 按每请求查询；当前测试主要覆盖 coach | 增加 athlete、管理角色例外、降级及连接复用证据 |
| CI 仅运行默认 pytest；本机 Docker daemon 初始不可用（现已启动） | CI 成为可复现 PG 执行路径；本机未运行时必须明示，不能静默 skip |

Notion 的[云端模型页](https://www.notion.so/410f602574aa8170b565f7fc4c5eab30)仍是早期草稿，包含场馆管理员、RLS 等未来设计；本次依据已合并六表和 RBAC 契约，不把那份草稿当作已实施政策。[基线准入](../../../../docs/baseline/cloud-foundation.md)要求先验证迁移、时间/事务和应用层隔离，再独立评审 RLS。

## Goals / Non-Goals

**Goals:** 从空的、可销毁的 PostgreSQL 实例验证现有业务闭环；用普通应用数据库身份运行 API；同一套可移植测试在 SQLite 与 PostgreSQL 执行；同一结论在本机 arm64 与 CI amd64 都可复现；每项结论可追溯至场景、提交、环境和实际结果。

**Non-Goals:** 不实现 RLS、生产连接管理或生产迁移入口；不承诺全数据库版本兼容、生产性能或所有并发权限竞态。本轮重点是现有身份和机构/场馆契约，完整平台安全仍由更广任务跟进。

## Decisions

### D1：独立、显式的 PostgreSQL 17 测试编排与执行选择规则

计划新增 `scripts/test-postgresql.py` 作为本机与 CI 共同入口。入口用 Docker CLI 创建唯一标识的临时容器（容器名与 label 均含 16 位十六进制 run id），仅绑定 `127.0.0.1` 的随机端口，数据与 socket 放 `tmpfs`，不挂载项目、宿主业务数据或旧目录。

**镜像与架构。** 锁定配置 `configs/postgresql-test-image.json` 固定 `postgres` 的 PostgreSQL 17 具体补丁标签与 **manifest list（OCI image index）digest**，而不是某一平台的单清单 digest：本机 arm64 与 CI amd64 会解析出不同的单平台 digest，锁多架构清单才能让两端使用同一发布物。运行摘要必须记录实际平台（`linux/amd64` 或 `linux/arm64`）、容器镜像 ID、`server_version` 与 `SHOW TimeZone`；不因架构差异放宽为浮动 tag，也不声称 17 是生产选型或最新大版本。

**目标拒绝。** 入口不提供任何数据库地址参数；忽略业务 `SWIM_CLOUD_DATABASE_URL`，并在构造 pytest 子进程环境时剔除该变量与全部 `PG*` 变量（含 `PGSERVICE`、`PGPASSFILE`、`PGOPTIONS`），避免本机既有 libpq 配置把连接导向其他数据库。连接前用 container ID、run id label、owner label、回环绑定与目标端口交叉核验；数据库名带 `test` 前缀不构成安全凭据。凭据随机生成，不进命令行日志、JUnit、摘要或 Git。

P1复审修正：pytest子进程额外接收完整container ID、name及owner，并在conftest配置阶段调用PgEnvironment.from_environment，通过真实Docker inspect重复使用上述归属规则，比较环境端口与实际5432/tcp回环映射。校验完成前不得连接psycopg或创建测试库，已校验对象通过pytest stash交给fixture；格式合法的环境变量本身不构成证明。该保护依赖可信本机Docker daemon，不承诺抵御有Docker管理权限的恶意操作者在校验后替换运行环境。

**执行选择规则。** 三层标记与运行矩阵：

| 用例类别 | 标记 | 默认 `pytest` | `--cloud-backend=postgresql` |
| --- | --- | --- | --- |
| 共享 API 用例（六表/授权/时间/事务的可移植断言） | 无标记 | 运行 | 运行 |
| SQLite 专属（naive-UTC 兼容回归、仅 SQLite 的初始化路径） | `sqlite` | 运行 | 跳过 |
| PostgreSQL 专属（schema/权限探测/版本表/目录断言） | `postgresql` | 跳过 | 运行 |

默认集合仍只跑 SQLite，不因本 change 改变日常 `python -m pytest` 语义。PostgreSQL Job 必须同时实际执行共享 API 用例与 PostgreSQL 专属用例；只跑 `-m postgresql` 视为不合格。conftest 在 PG 后端记录全部非 `sqlite` 用例的最终结果，会话结束时若出现任何 skip/失败/错误、收集数为零或低于约定下限，直接把会话判为失败；环境缺失、连接失败或身份不符同样非零退出，不会回退 SQLite。

**有界等待与清理。** 实例就绪用 `pg_isready` 轮询加总时限（默认 120s），超时即失败，不用 `sleep` 猜。清理在 `try/finally` 中按本次 run id 精确执行，并安装 SIGINT/SIGTERM/SIGHUP 处理把信号转成异常以进入 `finally`；删除前再次核对 label，不匹配则拒绝并记 `refused:*`。文档与脚本同时写明：**不得使用 `docker system prune` 或按镜像统删**。SIGKILL、宿主崩溃或断电无法保证即时清理，文档提供按 run id 的恢复流程（按 label 列出容器 → 逐条核对 `swim-pg-test-<run id>` 名称 → `docker rm --force <容器名>`）。清理状态不是 `removed`/`absent` 时，即使测试全绿也使 job 失败。

**替代。** 接受外部 DSN 更方便，但无法证明未指向业务库；长期共享 PG 会残留测试数据；仅 SQLite 或模拟 PG 驱动无法提供方言、schema 与锁证据，均不采用。

### D2：专用 Schema、search_path 与身份分离

**Schema 位置。** 每个测试库使用专用 schema `swim_cloud`，不使用 `public`。`public` 在 PostgreSQL 15+ 属于 `pg_database_owner` 且默认对 `PUBLIC` 开放 USAGE，容易与未来默认授权混淆；专用 schema 只有一个显式授权对象，便于逐项授予、撤销与断言。

- 管理员持有数据库并执行 `CREATE DATABASE`；schema `swim_cloud` 以 `AUTHORIZATION` 归迁移角色所有。管理员只做建库、建 schema、授权、销毁与 catalog 检查，不执行 API 断言。
- 迁移角色在 `swim_cloud` 内建表并执行 Alembic；应用角色不是表 owner，也不属于迁移角色。
- `public` schema 对 `PUBLIC` 全部撤销，避免应用身份借默认路径访问非预期对象。

**如何分别定位该 Schema。** 两个角色都用**连接级**参数定位，不在池化连接上执行 `SET`：

- 连接串携带 libpq `options=-c search_path=swim_cloud`（只含该 schema，不含 `public`），随连接建立生效；连接池每次新建物理连接都会自动应用，不存在残留，也不需要归还前还原。
- 迁移角色因此把六张业务表与 `alembic_version` 都创建在 `swim_cloud`；`env.py` 不指定 `version_table_schema`，不做产品代码改动。
- 应用角色同样以该 `search_path` 连接，故 `SELECT 1 FROM alembic_version`（`main.ready` 的原始写法）解析到 `swim_cloud.alembic_version`；测试断言版本表确实位于该 schema，而非偶然落在 `public`。

**应用角色权限（显式清单）。**

| 对象 | 授予 | 明确不授予 |
| --- | --- | --- |
| 数据库 | `CONNECT` | `CREATE`、`TEMPORARY`（`REVOKE ALL … FROM PUBLIC` 后仅补 `CONNECT`） |
| schema `swim_cloud` | `USAGE` | `CREATE`、schema 所有权 |
| 六张业务表 | `SELECT`、`INSERT`、`UPDATE`、`DELETE` | `TRUNCATE`、`REFERENCES`、`TRIGGER`、DDL |
| `swim_cloud.alembic_version` | `SELECT` | `INSERT`、`UPDATE`、`DELETE`、`TRUNCATE` |

角色属性为 `LOGIN`、`NOSUPERUSER`、`NOCREATEDB`、`NOCREATEROLE`、`NOREPLICATION`、`NOBYPASSRLS`，且不与迁移角色存在成员关系（因此 `SET ROLE swim_migrator` 必然失败）。

**负向探测清单（应用身份实际执行并断言被拒）。** 普通建表、临时表、`CREATE SCHEMA`、`ALTER TABLE`、`CREATE INDEX`、`CREATE DATABASE`、`CREATE ROLE`、`TRUNCATE`、`INSERT`/`UPDATE`/`DELETE alembic_version`、`SET ROLE swim_migrator`；每次失败后回滚，并确认同一连接仍可正常读取业务表。

**建库与销毁。** `CREATE DATABASE` / `DROP DATABASE` 不能运行在事务块内，因此使用**独立的管理员 autocommit 连接**（`autocommit=True`，用完显式 `close()`），与业务引擎的连接池完全分开；`DROP DATABASE … WITH (FORCE)` 在该用例所有应用连接关闭并 `engine.dispose()` 之后，由该独立连接执行。每个用例创建本次实例内的唯一空库，用例结束先关池再精确销毁该库；整次结束删除临时实例。

**本轮未启用 RLS。** 具有表 DML 权限的应用身份直接执行无过滤 SQL 仍可能读到其他机构数据，必须如实记录。因此非特权身份测试证明权限分离和应用授权，不证明数据库行级隔离。

**替代。** 全部用超级用户虽简单却无法验证应用最小权限；沿用 `public` 会让授权对象与默认权限纠缠，且版本表落点不可断言；单一拥有表的账号也不能为未来 RLS 提供可信基线。

### D3：现有迁移的真实验证与失败证据

保持 `20261106_0001` 不变；用迁移角色在空库 upgrade，断言 `alembic_version` 位于 `swim_cloud` 且值为 `20261106_0001`，模型与反射 schema 一致，另显式检查字段类型/空值、所有主键/唯一键、6 条外键（含 2 条复合外键）、3 个显式索引及 `CASCADE`。外键数以迁移代码逐条映射为准，不用 SQLAlchemy diff 为空替代行为验证。

数据断言包括重复 email/slug、同机构同名场馆拒绝而不同机构同名允许、重复成员/授权拒绝、两种错误复合外键、删除用户/机构/场馆/机构成员的相应级联及无关机构保留。直接数据库删除用于验证 DDL，不新增删除业务 API。

单独空库做 `downgrade base`、确认六表移除、`upgrade` 及基础 HTTP 冒烟。迁移中途失败用**预置冲突对象**制造真实失败（在空 schema 里先建一个同名 `sites` 对象，使 upgrade 在创建第五张表时失败），不编辑正式 revision、不 monkeypatch 生产代码；随后断言已创建的四张表与版本推进全部回滚、无版本行残留，移除冲突对象后重新 upgrade 成功。保留启动空库不建表、`ready=503`；迁移后 `ready=200`。发现结构不兼容时先报告；需要新增迁移或改变领域约束必须更新提案，不能改写旧 revision 绕过失败。

**替代：** 只比较 metadata 不能发现级联/事务差异；只测 upgrade 不能证明失败清理和回退路径；改写 revision 会污染已发布历史。

### D4：当前角色矩阵成为可执行场景

复用 [RBAC 契约](../../../../docs/contracts/cloud-rbac.md) 的合法请求前提和错误优先级。测试清单必须对 17 个业务 operation 逐项标记适用身份组合，两个 health/ready 单列；不机械生成无意义的笛卡尔积。

| 场景组 | 最少断言 |
| --- | --- |
| 注册/登录/me/退出 | 特权字段拒绝；token 仅存摘要；停用、过期、退出拒绝；公开端点与受保护端点分别处理 |
| 机构创建/列表/详情 | 创建者 owner 且原子提交；用户多机构列表仅所属；非成员详情 404 |
| 成员列表/新增/改角色/移除 | owner 可管理非 owner，admin 仅可列，coach/athlete 拒绝；owner 保护 409；无身份 401、外机构 404 |
| 场馆创建/修改/列表/详情 | owner/admin 全机构；coach 和 athlete 分别执行已授权/未授权；普通角色写拒绝；同账号跨两机构错配 site ID 仍拒绝 |
| 场馆授权/撤销 | 管理角色可操作且目标必须为机构成员；重复授权 409；撤销缺失授权 204；普通角色拒绝 |
| 权限变化 | 普通授权撤销、成员移除即时生效；admin 降级后只见明确授权；admin/owner 撤销显式授权仍保留机构权限 |
| 连接复用 | 单物理连接按顺序交替 A/B/匿名与 409 后成功请求，结果与当前身份一致 |

**连接池配置必须按用途分开（与 D5 共用）：**

| 用途 | 池配置 | 说明 |
| --- | --- | --- |
| 顺序连接复用（本表最后一行） | `pool_size=1`、`max_overflow=0` | 强制只可能有一个物理连接；用例必须**串行**发请求，任何并发都会因池饥饿报错，从而暴露误用 |
| 角色矩阵、时间边界等其余顺序用例 | 应用默认池 | 不额外收紧，避免误导为并发证据 |
| 并发唯一写入、五次失败登录、持锁等待 | 独立池 `pool_size=8`、`max_overflow=0`、显式 `pool_timeout` | **禁止**复用 `pool_size=1` 的夹具；连接不足必须以 `PoolTimeout` 失败，不得当作通过 |

复用用例通过 SQLAlchemy `checkout` 事件采集 `pg_backend_pid()`，断言全部请求落到同一物理连接；并发用例反向断言至少出现两个不同 `pg_backend_pid()`，证明真的并发而非串行重放。

越权业务写入与唯一冲突同时检查无非预期业务数据变化；失败登录按现有计数/锁定策略验证，不要求账号记录不变。读取同时检查返回 ID 集合及不泄露其他机构内容。涉及状态变化的组合用独立 fixture，避免先前授权改变后续断言前提。当前无 tenant 会话变量，连接复用测试验证请求事务/身份不残留；未来 RLS 的 `SET LOCAL` 测试不提前伪造。

**替代：** 只参数化 coach 为 athlete 能填一处缺口，但无法覆盖管理例外、成员管理及跨机构写入；用单连接池跑并发会把池饥饿伪装成业务失败。

### D5：时间瞬间、时区隔离、唯一冲突与并发锁

**时区隔离方式。** 不在池化连接上执行 `SET TIME ZONE`（该设置会随连接归还留在池里，污染后续请求）。改为**每个时区变体一个独立测试库**：建库时执行 `ALTER DATABASE … SET TimeZone`，使所有新建连接在建立时即继承该默认值；连接池无法跨库串用连接。数据库会话分别设 `UTC` 与 `Asia/Shanghai`，读取相同时间瞬间。

`search_path` 同样用连接级 `options`（见 D2）而非 `SET`，理由相同。夹具取到连接后断言 `SHOW TimeZone` 等于预期值，并在多次池化请求后再次断言，证明无跨请求残留。

**归一化策略。** 现状 `locked_until.replace(tzinfo=UTC)` 对 aware 非 UTC 值是静态可见风险：`Asia/Shanghai` 会话返回 `+08:00` 时，`replace` 会把同一墙钟重标为 UTC，使已到期锁被当成仍生效（偏差 8 小时）。统一策略：

- 带 `tzinfo` 的值（PostgreSQL 的 aware datetime）→ `astimezone(UTC)`，保留绝对瞬间；
- 无 `tzinfo` 的朴素值（SQLite 既有 UTC 约定）→ `replace(tzinfo=UTC)`，保持兼容；
- 两种都收敛到 UTC 再与 `datetime.now(UTC)` 比较。

最小修正在 `api.py` 的锁定比较处引入该归一化函数，并以“先失败后通过”的证据确认：修复前 `Asia/Shanghai` 库的到期锁用例失败，修复后两库结果一致。不改变五次/十五分钟策略、token 或 API 形状。

**并发。** 使用 D4 表中 `pool_size=8` 的独立池、独立连接/Session、同步屏障和有界超时；相同邮箱/slug/场馆名应一 201 一 409，无部分 owner 或重复记录，失败之后另一合法请求成功。五个并发错误密码登录后失败数 5 且锁定生效；另用持锁连接和第二登录请求证明锁等待/释放（有界等待与事件同步），不得把超时当通过。本范围不宣称解决撤销权限与同时写入等所有竞态。

**替代：** 串行重放和仅 UTC 连接会掩盖时区与丢失更新问题；在池化连接上 `SET TIME ZONE` 会留下跨请求污染；大量性能压测超出本次正确性目标。

### D6：CI 结果、环境证据与 RLS 决策分开

保留原 SQLite job；新增 PostgreSQL job 使用 D1 同一入口，真实创建独立实例，不依赖 GitHub secrets/业务凭据，不设置 `continue-on-error`。

- **有界等待**：由入口的 `pg_isready` 轮询与总时限保证，CI 不额外 `sleep`。
- **失败日志收集**：pytest 失败或编排异常时，在清理之前抓取 `docker logs --tail`，按本次随机密码脱敏后写入 `var/postgresql-instance.log`，随 JUnit 一并上传；日志抓取失败不得掩盖原始失败。
- **always 清理**：`if: always()` 步骤读取本次 `var/pg-test-run.json` 的 run id，再次核对 label 后精确删除；不使用 `docker system prune`。
- **证据上传**：`if: always()` 上传脱敏 JUnit、运行摘要（镜像 digest、平台架构、`server_version`、`TimeZone`、身份清单、清理状态）与实例日志。
- **失败即红**：PG 必需场景零收集、被 skip、共享 API 用例未执行或环境失败，都必须使 job 失败。

CI job 成功不自动修改仓库保护规则，也不等于用户批准本 PR。

P1复审修正：Docker.inspect仅将精确指向所查对象的“No such object”错误（大小写兼容）判为不存在；daemon、权限、畸形响应均为编排错误。主入口及cleanup-run-file共享清理成功白名单removed/已确认absent；error、refused、removed:unverified及缺少run-file均返回非零。摘要记录最终exit_code，result在清理完成后计算；不得先写failed再返回0。回归同时覆盖main返回值与实际CLI子进程退出码。

本提案建议先完成 PG 兼容验证，RLS 后续单独提案；该范围选择在 apply 中沿用。RLS 待评审候选为 tenants 及三个租户归属表；users/auth_sessions 是全局身份路径，不能直接强塞单 tenant 过滤。未来必须解决创建机构、机构列表、多机构成员、可信 tenant/user 上下文来源、各操作 USING/WITH CHECK、缺失上下文拒绝、事务局部设置和池复用、表 owner/FORCE RLS 及 BYPASSRLS 绕过，并用真实非特权角色负向验证。官方说明表 owner 通常可绕过 RLS，超级用户及 BYPASSRLS 角色始终可绕过，见[PostgreSQL RLS 文档](https://www.postgresql.org/docs/17/ddl-rowsecurity.html)。

apply 发布 `docs/decisions/0002-postgresql-validation-and-rls-boundary.md`，标明本轮仅验证目标与 RLS 后续评审清单，不冒充 RLS 实施设计已批准。原 Notion 草稿保留，通过新版入口解释阶段差异。

### D7：任务、交付与证据映射

| 要求/范围 | 后续实现位置 | Notion 既有任务 | 验收证据 |
| --- | --- | --- | --- |
| Isolated database validation | `scripts/test-postgresql.py`、`configs/postgresql-test-image.json`、conftest 选择规则 | [隔离测试](https://www.notion.so/410f602574aa81e8a757def927b364df) | 目标拒绝、镜像锁定、身份检查、失败清理、SQLite 不回退 |
| PostgreSQL schema integrity | `tests/test_postgresql_schema.py` | [数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6) | 迁移反射、schema 落点、约束/级联、降升与故障回滚 |
| PostgreSQL authorization parity | 共享基础测试与 `test_authorization_matrix.py` | [RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e) | operation×适用角色/机构/场馆矩阵、池复用与并发池分离 |
| 时间和事务两项要求 | `tests/test_postgresql_transactions.py`；`api.py` 时间归一化 | [云端基础](https://www.notion.so/410f602574aa81c8bfa0e4728a58b737) | 两时区库边界、并发唯一冲突、计数/行锁 |
| Reproducible PostgreSQL validation evidence | CI、README、`docs/verification/cloud-foundation-postgresql.md` | 上述四任务 | 当前 head CI、平台架构、版本、JUnit、清理与未验证范围 |
| RLS 边界 | ADR 草案、验证报告 | 数据模型与 RBAC | 明确未实施/未验证，后续评审条件 |

**18 个规格场景到任务的映射**（每个场景至少对应一项任务的验收证据）：

| # | 场景 | 任务 |
| --- | --- | --- |
| 1 | Initialization points to external database | 1.3（保留 SQLite 初始化限制回归） |
| 2 | PostgreSQL target is not owned by this run | 1.1 |
| 3 | Restricted application identity | 1.2 |
| 4 | Failure during test execution | 1.1 |
| 5 | Empty database migration and round trip | 2.1、2.2 |
| 6 | Invalid cross tenant reference | 2.1 |
| 7 | Unique keys and cascading removal | 2.1、2.2 |
| 8 | Interrupted migration transaction | 2.2 |
| 9 | Role and operation matrix | 3.1 |
| 10 | Explicit site access and management exception | 3.2 |
| 11 | Membership removal and role downgrade | 3.2 |
| 12 | Reused connection across identities | 3.3 |
| 13 | Equivalent instants in different timezones | 4.1 |
| 14 | SQLite compatibility | 4.1 |
| 15 | Concurrent unique writes | 4.2 |
| 16 | Concurrent failed logins | 4.3 |
| 17 | Missing PostgreSQL prerequisites | 1.1、5.1 |
| 18 | Evidence bound to a revision | 6.1、6.2 |

四任务当前状态（云端基础/隔离测试待验收，数据模型/RBAC 进行中）保持不变；本 change 只追加 PostgreSQL 子范围。apply 开始时记为进行中，完成后按真实进度更新，不创建同名任务、不把全平台任务标为完成。

## Risks / Trade-offs

- [本机 Docker daemon 可能不可用] → 入口在连接前即失败并说明原因；apply 可用专用 CI 路径取证；两处都不可用时相关运行任务保持未完成，不能勾选。
- [跨架构镜像 digest 不一致] → 锁多架构清单 digest，运行时记录实际平台单清单 digest 与镜像 ID；不把某一平台 digest 硬编码成唯一真值。
- [容器清理失效] → 精确 run id、`finally`/信号处理、CI `always` 兜底及 run_id 恢复说明；清理异常显式记 `refused:*` 并使 job 失败；禁止全局 prune。
- [非特权身份被误当 RLS] → 明确表权限和行隔离不同，报告直接 SQL 可跨机构的当前限制。
- [schema/search_path 配错导致“看起来通过”] → 断言版本表位于 `swim_cloud`，并在应用连接上断言 `SHOW search_path`；错误时用例失败而非静默落到 `public`。
- [时区设置经连接池残留] → 库级默认 + 连接级 `options`，不使用会话 `SET`；多次池化请求后复验 `SHOW TimeZone`。
- [连接池配置与场景错配] → 复用用例 `pool_size=1` 串行；并发用例独立 `pool_size=8`；用例断言 `pg_backend_pid()` 数量，池饥饿以 `PoolTimeout` 失败。
- [共享测试夹具引入外部连接] → 默认 SQLite 独立，PG 连接只能由本次编排内部生成；安全拒绝测试证明不会连接任意地址。
- [并发测试不稳定] → 独立连接、屏障、有界超时与实际数据结果；没有实现保证时报告失败，不增大超时掩盖缺陷。
- [测试矩阵过大] → 依据现有 operation 和有效前提枚举适用格，报告缺项，不按测试总数推断全平台安全。

## Migration Plan

1. 按用户 2026-11-07 的 apply 授权实施 D1–D6 与任务清单；真实 PG 只使用新测试实例。用户提供的未跟踪工作流模板 `docs/workflow/` 保留原状，不混入本 PR。
2. 规划产物先按本次澄清同步修订（schema/search_path、时区隔离、池配置分离、标记规则、清理与 CI 证据），再提交实现，保证 proposal/spec/design/tasks 一致。
3. 同一 PR 提交实现与真实结果；仅执行测试验证，不自动启动独立 verify、archive 或合并。后续这些阶段分别等待用户授权；主规格同步遵循归档流程。
4. 回退测试工具/CI 采用正常 revert，丢弃仅本次临时实例；业务默认 SQLite 及旧库均不受测试迁移影响。真实 PG 尚未通过时不能宣称云端生产可用。


## 独立核验后补强（2026-11-07）

W1：成员PATCH/DELETE及场馆授予/撤销的遗漏身份组合通过参数用例补齐，拒绝请求比较六表全部持久化状态；owner/admin分别真实授予并撤销自身显式场馆授权后保留机构权限，管理角色新增授权严格断言201。
W2：三个唯一写入用例分别在目标INSERT的before_cursor_execute处设置双连接会合屏障，双方同时持有连接并断言两个不同后端PID，避免仅在线程启动处会合而数据库仍串行。
S1：PG_LEDGER另存节点类别，除了状态及总数下限，还要求shared/postgresql两类均被收集；任何必需节点skip/失败仍失败，终端输出两类计数。12个持久回归覆盖缺类、零集合、总数不足、skip/失败/error和正常集合。--dev-select免总数下限但仍需两类，不作为完整验证证据。
S2：用户明确选择后续改进。当前只记录多架构index digest、实际架构及Docker返回image ID/RepoDigests；未来另解析平台manifest digest，当前不伪称已经具备该字段，不改变PG架构。
