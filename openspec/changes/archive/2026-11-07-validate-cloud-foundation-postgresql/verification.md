# Verification Report: validate-cloud-foundation-postgresql

核验日期：2026-11-07（Asia/Shanghai）。Schema：spec-driven。
核验对象：`1736b40f957ecd96d92161838a7d27dde86e687a`，基线main为`4968750`；报告是后续独立核验记录，不属于被核验实现。评审入口：[Draft PR #2](https://github.com/TuIanL/zhiyong-swim-platform/pull/2)。

> 本节至Final Assessment为对1736b40的历史核验；当前修复复核见末尾“W1/W2/S1修复复核”。

## Summary Scorecard

| 维度 | 核验结果 |
| --- | --- |
| Completeness | CLI为16/16、无不可读tracking文件；逐项查实际产物，3.1/4.2有证据缺口（W1/W2），不能仅据勾选宣称完整验收；6项ADDED/MODIFIED要求均找到实现 |
| Correctness | 6/6要求完成实现映射；18个场景均逐项检查处理路径与测试，矩阵及并发证明存在W1/W2；两个P1修复通过定向核验 |
| Coherence | D1–D7逐项复核；主体遵守设计，矩阵/并发证据见W1/W2；工程目录、命名和隔离测试模式一致，S1/S2为建议 |

CRITICAL **0**、WARNING **2**、SUGGESTION **2**。适用检查6项均执行；Not verified **0**，Not applicable **0**。此处“检查已执行”不等于没有缺陷，W1/W2是已发现的覆盖/证据问题。

规格增量：MODIFIED 1、ADDED 5；REMOVED 0、RENAMED 0。没有skip_specs；不能使用上一个纯文档change的Not applicable结论。

## 核验输入与方法

- 根据CLI解析的root、schema、artifactPaths、apply.contextFiles、taskTrackingConfigured、tasks和progress读取proposal、design、tasks及规格增量。all_done只作为输入，不作为核验结论。
- 识别与main相比的22个实现/规划/文档文件，读取编排、测试夹具、六表模型/迁移、API时间修正、角色/时区/连接复用/事务测试、CI和交付文档；未修改实现或任务勾选。
- 直接复查PR对象、绑定核验head的CI及其原始JUnit/摘要，读取Notion四任务的当前摘要/回链/总体状态。
- 本轮实际运行47项编排安全用例及只读ledger探针；重跑change strict、主规格strict和链接/范围检查。没有重新执行全套本机数据库测试，完整后端结果引用核验head的CI，不冒充本轮本机新结果。

## Completeness：16项任务的实际证据

所有源码行号指核验提交1736b40。下表检查任务交付，后文另检查规格和场景。

| 任务 | 实际交付/证据 | 结果 |
| --- | --- | --- |
| 1.1 | scripts/test-postgresql.py：镜像锁、Docker inspect、resolve_host_port、cleanup_container/execute；47项guard回归及CI真实清理 | 主体确认；平台单清单摘要表达见S2 |
| 1.2 | pg_support.py:119–187、245–338；conftest.py:47–59；identity测试18项 | 真实容器校验先于数据库连接；schema/身份权限确认 |
| 1.3 | conftest.py:30–118；默认SQLite、PG共享/专属选择、ledger失败处理；README | 当前集合与失败处理确认；分类防退化见S1 |
| 2.1 | test_postgresql_schema.py:50–188；模型/迁移一致、类型/空值、键/索引/复合外键实际断言 | 确认 |
| 2.2 | test_postgresql_schema.py:245–406；级联、降升、预置冲突DDL回滚、ready语义 | 确认，重建后重新授权已如实记录 |
| 2.3 | docs/verification/cloud-foundation-postgresql.md；六表、版本、运行、失败及限制分列 | 确认 |
| 3.1 | test_authorization_matrix.py；docs/contracts/cloud-rbac.md:93–115 | 17种操作均有用例，但表内部分适用身份格未覆盖：W1 |
| 3.2 | test_authorization_matrix.py:178–240；既有撤销/移除测试 | 普通角色撤销、admin降级/移除与管理例外有证据；owner显式撤销组合缺口并入W1 |
| 3.3 | test_connection_reuse.py:24–100；单连接池、checkout PID唯一、A/B/匿名、409后恢复 | 确认 |
| 4.1 | api.py:26–36、114–124；test_authentication_deadlines.py:59–141 | UTC/Asia/Shanghai及naive UTC，截止前/等于/之后确认 |
| 4.2 | test_postgresql_transactions.py:38–99；run_concurrently屏障/独立池 | 唯一冲突结果有证据；三个用例未各自断言不同PID，见W2 |
| 4.3 | test_postgresql_transactions.py:102–175 | 五次失败计数、不同PID、真实等待锁/释放确认 |
| 5.1 | .github/workflows/ci.yml；核验head CI42327405540、JUnit/摘要/清理步骤 | 双后端真实执行，removed与兜底absent/0确认 |
| 5.2 | docs/decisions/0002-postgresql-validation-and-rls-boundary.md | 测试目标与RLS未实施边界明确，未伪造生产批准 |
| 6.1 | apply报告第4、9节；6要求/18场景追溯、本轮strict/链接检查 | 材料齐备；原“全部完成”须结合本报告缺口理解 |
| 6.2 | 同一PR/分支；四项Notion任务实际回链，状态分别待验收/进行中 | 确认，无总体完成或继承PR #1批准 |

## Correctness：要求实现映射

| 增量要求 | 实现证据 | 判断 |
| --- | --- | --- |
| MODIFIED Isolated database validation | 编排resolve_host_port/cleanup；pg_support.from_environment/verify_container；conftest.pytest_configure；临时库/最小权限fixture | 实现存在且P1修复符合意图；初始化核验真实ID/name/run/owner/回环映射，不凭环境格式放行；清理错误不冒充absent |
| ADDED PostgreSQL schema integrity | 原迁移20261106_0001、pg_support.create_database；schema/约束/级联/回滚测试 | 真实六表及版本表落点，失败回滚和重授权限路径符合要求 |
| ADDED PostgreSQL authorization parity | api.membership/manager/site_access及每请求Session；矩阵/连接复用测试 | 服务端现有授权路径符合意图；测试矩阵并非每格穷举（W1） |
| ADDED Timezone independent authentication deadlines | api.as_utc、login、identity；独立时区库与固定服务时钟 | aware转换保留瞬间、naive按UTC；截止时间比较正确 |
| ADDED PostgreSQL transactional account operations | 唯一键、IntegrityError回滚、login.with_for_update；并发/等待锁测试 | 实现与结果符合意图；唯一写入的物理并发证明不足（W2） |
| ADDED Reproducible PostgreSQL validation evidence | 锁定镜像、summary/JUnit、CI job、apply报告；核验head原始artifact | 平台/版本/结果/清理可追溯且脱敏；建议显式校验用例类别和改善平台摘要（S1/S2） |

### 18个场景逐项检查

| # | 场景 | 实际处理及测试证据 | 结论 |
| --- | --- | --- | --- |
| 1 | Initialization points to external database | cli.init-db路径限制；test_cli_refuses_external_or_legacy_database两参数 | 有覆盖 |
| 2 | PostgreSQL target is not owned by this run | Docker inspect/resolve_host_port、PgEnvironment初始化；伪造完整环境/ID/name/run/owner/端口/daemon负向，connect spy为0 | 有覆盖，P1-2确认 |
| 3 | Restricted application identity | role属性、非owner/无成员关系、实际DDL/提权拒绝及回滚后可读测试 | 有覆盖 |
| 4 | Failure during test execution | inspect精确分类、rm/daemon/label/删除未确认5类错误；main与CLI退出码、cleanup-run-file | 有覆盖，P1-1确认 |
| 5 | Empty database migration and round trip | schema版本表断言、downgrade/upgrade与HTTP注册/机构/场馆冒烟 | 有覆盖 |
| 6 | Invalid cross tenant reference | 两条复合外键拒绝跨机构引用、回滚无残留 | 有覆盖 |
| 7 | Unique keys and cascading removal | 重复邮箱/slug/场馆/成员/授权，删除用户/机构/场馆/成员及无关记录保留 | 有覆盖 |
| 8 | Interrupted migration transaction | 预置同名sites对象触发失败，前序DDL/版本回滚，清除冲突后upgrade | 有覆盖，不改旧revision |
| 9 | Role and operation matrix | 17操作/角色检查链存在；test_member_management_matrix及场馆授权用例 | 部分身份格未有独立测试，W1 |
| 10 | Explicit site access and management exception | athlete/coach撤销拒绝、admin显式授权撤销后可访问 | owner自身显式授权撤销组合未实测，W1 |
| 11 | Membership removal and role downgrade | 现有token被撤销/移除后拒绝；admin降为athlete后无授权不可见 | 有覆盖 |
| 12 | Reused connection across identities | pool_size=1，checkout PID唯一，A/B/匿名及409后请求 | 有覆盖 |
| 13 | Equivalent instants in different timezones | UTC/Asia/Shanghai独立库，锁与会话截止前/等于/后及连接配置复验 | 有覆盖 |
| 14 | SQLite compatibility | SQLite专属naive UTC、既有lockout/expiry回归 | 有覆盖 |
| 15 | Concurrent unique writes | 三类并发请求，201/409、单记录、owner原子性；不同PID断言缺失 | 有结果覆盖，物理并发证据W2 |
| 16 | Concurrent failed logins | 五个请求401、最终计数5、锁定生效、至少2个PID及持锁等待 | 有覆盖 |
| 17 | Missing PostgreSQL prerequisites | 无Docker/daemon失败；ledger零集合/不足/skip非零；本轮独立探针复查 | 有覆盖；分类显式检查建议S1 |
| 18 | Evidence bound to a revision | 当前PR head、CI原始摘要/JUnit、apply报告第9节与Notion | 当前head绑定确认，旧结果没有外推 |

## Coherence：设计与项目模式

- D1：专用实例、锁镜像、回环端口、run id校验与精确清理遵守；P1追加的子进程独立核验和清理非零传播已实现。类别/平台证据建议见S1/S2。
- D2：swim_cloud、连接级search_path、迁移/应用身份分离、管理员autocommit和最小权限遵守。
- D3：原迁移不改，真实升级/降级/故障回滚与schema断言遵守。
- D4：现有角色政策和单连接复用遵守；逐格覆盖描述与实际测试差距见W1。
- D5：库级时区、aware/naive归一化、独立并发池与行锁遵守；三个唯一写入场景的PID证据见W2。
- D6：CI两后端、always清理、原始证据上传及RLS未实施边界遵守。
- D7：四项Notion任务复用，范围/状态和证据回链实际存在，没有把局部结果标为全平台完成。

代码模式已执行检查：新增内容在scripts/configs/services/cloud/tests/docs及本change中，沿用pytest、SQLAlchemy、显式设置及隔离fixture；产品改动仅api.as_utc，与既有模块一致。pg_support按路径导入编排模块与guard测试的现有路径加载模式一致；未发现需单列的显著命名/目录偏离。

## 实际检查与证据边界

| 检查 | 本轮结果/来源 |
| --- | --- |
| 编排安全测试 | 本轮运行 `pytest services/cloud/tests/test_pg_harness_guard.py --junitxml=var/verify-pg-guard-junit.xml`，47 passed、1项既有弃用警告；未连接数据库 |
| ledger只读探针 | var/verify-ledger-probe.json：zero=1、below_minimum=1、skipped=1、all_pass=0；构造80个仅PG且均passed条目仍返回0，支持S1的防退化建议，不表示当前39项PG集合单跑已绕过80下限 |
| OpenSpec strict | 本轮change strict、主规格strict各1/1通过；strict不代替行为核验 |
| 核验head完整CI | [42327405540](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42327405540)，head1736b40；GitHub临时merge ref323dce0（与main4968750组合），不是实际合并 |
| CI实际结果 | SQLite80 passed/39 PG专属skipped；PG118 passed/1 SQLite专属skipped、0 failures/errors；两个job、always清理/上传success |
| CI原始artifact | [13556096452](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42327405540/artifacts/13556096452)重新下载读取，var/verify-head1736-evidence/；run id032ee6a58a253a25、linux/amd64、PG17.11、result=passed/cleanup=removed/exit_code=0；兜底确认absent/0 |
| 历史本机完整结果 | apply报告中SQLite80/PG118通过，arm64 run01ef97a491cddb93；本轮没有重跑完整数据库测试，不把历史结果当新运行 |
| Notion四任务 | 本轮直接读取，云端基础/隔离基线待验收，模型/RBAC进行中；PG子范围与总体范围分开 |

本轮不访问旧库、真实账号或生产数据。RLS、生产、性能及更广竞态原本就在非目标内，不因此发明本change的缺失要求，也不算本报告跳过的适用检查。核验报告提交的新CI另在PR/Notion绑定，不拿被核验head的CI冒充报告提交已通过。

## Issues by Priority

### CRITICAL：0

没有发现缺失的要求实现或CLI列出的未完成任务；不把覆盖证据缺口直接推断为已发生越权或数据库并发缺陷。

### WARNING：2

**W1：角色矩阵的完成描述超出实际用例格。** `test_authorization_matrix.py:145–154` 对成员PATCH/DELETE只断言admin、owner及owner保护，没有该操作的coach、athlete、非成员、匿名格；`:197–202` 撤销场馆授权只覆盖coach拒绝/admin成功，且`:222–240` 只撤销admin的显式授权，owner只是读取。RBAC文档`:93–115`列出这些操作的所有角色格，任务3.1及场景9/10的覆盖描述因此不能视作全部实测。建议在同一合法目标/输入前提下补齐上述格，给被拒写入加持久化无变化断言，并让admin授予用例明确断言201（`:189–191`目前允许201或409）；同步准确覆盖标签。现有API的owner/manager检查已找到，不据此声称实现缺失。

**W2：并发唯一写入没有逐场景证明独立物理连接。** 任务4.2和D4明确要求至少两个不同`pg_backend_pid()`；`test_postgresql_transactions.py:38–99`三个唯一写入测试只检查201/409和行数，没有调用`record_backend_pids`。目前只有`:106–113`五次失败登录用例做该断言，不能外推其他测试。建议三个唯一写入用例各自采集并断言不同PID，必要时用同步点确保请求同时持有连接，再验证冲突回滚后的合法写入；不把线程屏障本身当作不同数据库连接的证据。

### SUGGESTION：2

**S1：显式检查共享与PG类别，减少依赖总数阈值。** `conftest.py:66–118`的ledger不保存类别，只看非sqlite总数和状态。当前仅PG39项会被80下限拒绝，但未来PG专属达到80后，缺少共享API的集合可通过本轮探针所示检查。建议单独记录两类收集/运行数并要求均非零，为zero/skip/不足和只跑一种类别添加持久回归测试；这不否认当前CI已经实际运行两类用例。

**S2：对齐“实际平台digest”与摘要真实字段。** 任务1.1/设计风险项提到单平台digest，但`scripts/test-postgresql.py:540–546`只存Docker image inspect返回的Id/RepoDigests；当前artifact两个字段均为锁定的多架构index digest。报告已如实披露，没有伪造平台摘要。建议明确区分index digest、平台manifest digest与image ID；需要单平台证据时从index按os/architecture解析并记录，否则将任务/文档描述收敛到实际承诺，不能将现有值改名冒充单平台digest。

## Final Assessment

**未发现CRITICAL；有2项WARNING、2项SUGGESTION。全部适用检查已执行，没有Not verified项。** 按技能的建议性门槛为 **Ready for archive (with noted improvements)**，其中W1/W2应由负责人先决定补齐或如何处理；此建议不等于接受例外、产品验收或归档授权。

两个P1定向修复通过本轮核验，但不能把它等同于整个change的所有覆盖描述无缺口。本轮未修实现、改任务勾选、同步主规格、Archive或Merge；PR保持Draft。下一步由负责人评审本报告，并授权回到apply处理问题或继续独立归档流程。


## W1/W2/S1修复复核（2026-11-07，当前结论）

用户要求先修复再归档，S2只留后续改进。复核原报告W1/W2/S1对应源码与持久回归：

| 项目 | 修复证据 | 结果 |
| --- | --- | --- |
| W1 | test_authorization_matrix.py 的DENIED_WRITES18格、六表前后snapshot、owner/admin各自自身授权撤销与严格201/重复409；两后端完整运行 | 已解决，未接受永久遗留 |
| W2 | test_postgresql_transactions.py 的distinct_write_connections，三个唯一INSERT各自会合并断言2个不同PID；原冲突/原子性断言保留 | 已解决，不以其他用例外推 |
| S1 | conftest.PG_CATEGORIES、类别非空及逐节点状态检查；test_pg_collection_guard.py12个持久回归含单一类别满80仍拒绝 | 已解决 |
| S2 | 用户明确留后续改进；index/platform/image字段边界如实保留 | 唯一剩余SUGGESTION，不扩张本轮范围 |

本机完整重跑SQLite112通过/39专属跳过、PG150通过/1专属跳过，真实removed/exit0；共有151项，无failure/error。报告/设计/任务中的W1/W2验收描述与新增断言已逐项核对；规格要求/18场景保持原业务行为。当前适用检查仍6项，Not verified0，Not applicable0；W1/W2不再作为开放WARNING。最终代码提交与CI证据需在后续交付记录绑定。

当前结论：CRITICAL0、WARNING0、SUGGESTION1（S2，负责人明确延后）。Ready for archive (with noted improvements)，不表示自动合并PR或整个平台完成；归档仍须按技能处理delta sync选择。

修复交付提交 `4e3153098eefec9ae0fca1dee0a909d65caa1927` 的 [PR CI 42330560453](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42330560453) 已completed/success；日志确认SQLite112 passed/39 skipped，PG150 passed/1 skipped，类别shared111/postgresql39，真实cleanup=removed，兜底确认absent/exit0（run id e777d69376896dcf）。GitHub临时合并引用be37a43不是实际合并。此前待取得CI的描述已由本记录收口，CLI16/16；W1/W2/S1已解决，S2按用户选择留后续。
