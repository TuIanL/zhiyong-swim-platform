# Tasks

本轮仅 Propose，以下 **42 项实施任务均未执行**。规划产物done、strict或历史CI通过不算Apply完成。引用 [Design](design.md) D22–D31与Q1–Q8，以及[规格增量](specs/)；每组包含自身需要的测试与文档，不把缺失的单项验证推到最终集成。

## 1. 审阅输入与 M2 WARNING 收口

- [ ] 1.1 在收到明确Apply授权后核对最新main/本Change/原任务，记录Q1开发与真实集成profile、Q3容量/分片候选和Q4格式/失权策略的负责人结论；未确认不得按候选实施。证据：Change内决策记录能逐项关联负责人原文与参数，生产产品/区域/隐私保留仍明确未冻结，Notion属性不擅改。
- [ ] 1.2 修复W1：User/Edge意图在当前身份/资源能力核验后、cancelled新建检查前查主体域幂等；同参重放原终态、异参409幂等冲突、新键cancelled409。证据：两后端共享API测试覆盖取消前后响应丢失/重试、两个ID与原因/首次时间不变、撤权/过期token拒绝，契约补录检查次序。
- [ ] 1.3 补W2相同SHA独立采集回归：两合法Device/不同键/同大小摘要，各保留不同asset/upload ID、来源与采集时间；独立人工导入也不合并。证据：两后端共享API断言，后续5.3验证后仍独立；领域文档明确请求幂等与物理内容不同。
- [ ] 1.4 补W3两类grant审计回归：Owner@T1 PUT、Admin@T2 PUT、Owner@T3 DELETE、Admin@T4 DELETE。证据：两后端读取持久字段逐项断言首次granted_at/by、revoked_at/by不变，仅期限可更新，仍一条有效授权；RBAC契约记录该保证。
- [ ] 1.5 补W4合法utc/offset/iana_timezone正向意图与Asset GET往返，保留unknown/非法组合负向。证据：共享测试核对有效ZoneInfo、原始带空白字符串、UTC瞬间/时区/偏移/clock source，received_at不冒充采集时间；采集时间契约同步。

## 2. 数据模型、迁移与最小权限

- [ ] 2.1 按D24新增四支持表与全部复合归属键、RESTRICT、唯一性/部分字段配对、分片state、作业租约和候选精确身份；扩Upload布局/清单、Asset验证/存储引用、幂等upload.complete词表。证据：两后端模型/反射与真实跨scope/重复/非法状态写入测试；领域字段表与图一一对应，15→19表。
- [ ] 2.2 新增0004并保护0001–0003，既有M2行布局/验证保持空、不改ID/来源/采集原文/声明/过期时间/幂等摘要；异常既有ready预检拒绝。证据：带历史数据升级前后逐字段相等，两后端显式迁移事务；更新迁移说明。
- [ ] 2.3 实现安全downgrade guard与中断回滚：有支持记录/验证引用/complete幂等即拒绝并列分类；纯历史0003→head→0003→head。证据：SQLite重建中与PG新表创建后失败注入，DDL/数据/版本回滚、原FK生效；拒绝场景不删物理对象。
- [ ] 2.4 把pg_support与schema/identity显式集合扩为19表，保留swim_cloud、迁移/app分离、canary拒绝与DDL/TRUNCATE/SET ROLE/版本表写拒绝。证据：完整PG权限探测与表集合断言，文档不声称RLS已实现。

## 3. Storage Provider Adapter 与隔离集成设施

- [ ] 3.1 实现统一协议及首个经批准profile适配器，封装SDK、分页、错误归一与必要capabilities；路由不依赖厂商SDK。证据：Adapter契约测试和包安装测试，锁定依赖/许可与真实服务版本/镜像digest，文档说明已测与未测产品。
- [ ] 3.2 实现服务端对象命名、私有ACL/精确版本绑定、归属元数据与Secret配置门禁；不得接受客户端key/endpoint/桶。证据：注入路径/跨scope/缺失版本能力拒绝、签名日志脱敏测试与配置说明；无静态公开旁路。
- [ ] 3.3 建立可销毁真实存储测试编排，核验本次实例ID/名称/owner+run labels/回环端口、专用bucket/namespace，忽略外部媒体配置，成功失败均精确清理。证据：归属伪造在连接前拒绝、启动超时非零、删除失败/daemon错误非零、无全局prune；恢复runbook与编排实测一致。
- [ ] 3.4 在真实服务验证create/list全分页/sign/complete/HEAD/read/abort/delete，覆盖200内嵌错误、NoSuchUpload歧义和网络/权限错误。证据：真实I/O结果与故障注入分开记录，明确fake只用于受控故障，不能替代传输集成验收。

## 4. 分片、确认与恢复接口

- [ ] 4.1 实现首次part-urls的唯一保留/布局登记与initialize持久工作、202准备/200签名响应，外部SDK在记录提交后运行。证据：重复/并发准备及“MPU创建后DB保存前”崩溃恢复，唯一逻辑pair、精确清理多余句柄；API契约记录202轮询。
- [ ] 4.2 实现User/Edge part-urls，参数与现有声明计算1..N/末片大小，签名仅UploadPart且先持久保存写窗口。证据：编号重复/零/负/越界/批次上限、TTL/身份/意图上限、乱序上传与实际大小约束测试；文档不虚称浏览器可强制所有Content-Length。
- [ ] 4.3 实现User/Edge PUT parts确认，核对provider真实编号/大小/ETag与当前状态/代际；相同确认自然幂等，不同回执409。证据：共享API与真实分片测试证明唯一行、首次确认时间、虚假回执不确认；确认字段/错误目录同步。
- [ ] 4.4 实现User/Edge GET parts分页和丢回执恢复，provider完整分页对账，修改旧确认标stale保留历史，cursor绑定scope/upload/generation。证据：多页、无本地回执、缺片续传、旧ETag、过期cursor、事务外I/O快照失效测试，恢复示例同步。
- [ ] 4.5 增量扩既有UploadSessionRead的布局/transfer_status/confirmed_parts，终态只返历史；所有新入口复用现身份/范围链。证据：User/Edge token互用、跨节点/机构/场馆、设备停用、owner/admin接管、只读grant负向矩阵，原M2 GET字段保留。

## 5. Complete、验证与 ready 原子提交

- [ ] 5.1 实现User/Edge complete的主体域Idempotency-Key、固定有序manifest、作业/幂等/completing同事务，202/200与Location/Retry-After。证据：结构非法422、证据不足409、同key异参409、同key/不同key同清单唯一工作、另一清单拒绝，OpenAPI/契约对应。
- [ ] 5.2 实现独立持久worker、领取/续租/重试/代际条件提交，所有长I/O在SQL事务外。证据：重启、重复投递、租约过期旧worker、IO/DB超时与重试耗尽用例，文档区分业务一次与物理副作用至少一次。
- [ ] 5.3 实现完整对象流式SHA-256与实际字节数、同对象受限媒体探测与声明比对，保留声明和验证值。证据：真实合成媒体的合法/伪装/损坏/错hash/错size/空或泛类型声明测试，探测器无网络与资源上限测试；两个相同内容采集验证后仍独立。
- [ ] 5.4 实现最终短事务重查当前scope/权限/接受凭据/设备/Session/期限/代际/精确对象/清理标记后同提交completed+ready+验证引用。证据：三处写入/提交失败注入无单侧终态，已验证对象替换或失权不ready；Asset响应实际值与原Upload声明分别可读。
- [ ] 5.5 实现歧义完成恢复：合并前复核最新parts，合并超时/NoSuchUpload/对象已存在均按精确版本重验；确定校验失败与传输失败正确配对并登记清理。证据：合并后提交前崩溃、HEAD缺失/权限错误、200内错误与迟到响应测试；故障恢复runbook同步。

## 6. 状态机与真实 PostgreSQL 并发

- [ ] 6.1 统一cancel/abort/expiry/读时物化/complete最终提交的Session→Upload→Asset→Object锁顺序；completing也可中止/过期，首次终态不可改。证据：共享状态矩阵含恰好expires_at与completed后中止/取消，原M2终态回归仍通过；状态机文档更新。
- [ ] 6.2 用两个业务连接与独立监控连接受控运行Cancel vs finalize、Abort vs finalize、Expiry vs finalize各两方向。证据：JUnit含互异PID、实际wait_event_type=Lock/pg_blocking_pids、有界等待，胜方终态/原因/时间与两侧原子性断言，不以单连接/随机sleep作证。
- [ ] 6.3 验证重复complete/分片确认、并发准备/租约接管/旧worker提交与GC vs finalize的合法单赢家。证据：真实PG独立PID、锁或CAS代际/rowcount、唯一记录与无死锁断言；SQL锁不跨外部长I/O的并发取消用例。
- [ ] 6.4 覆盖当前授权变化与存储I/O期间Node/Device停用、用户角色/场馆移除、接受凭据过期/撤销。证据：最终提交按已批准Q4失败配对或保留已先完成结果，后续身份请求拒绝，不能由已排队工作或旧幂等键越权。

## 7. 播放与下载访问

- [ ] 7.1 实现User playback-url/download-url，复用_scope+当前A-read和精确ready对象身份，不另建ACL。证据：Owner/Admin/Coach/athlete/非成员/匿名/Edge、Asset-only grant、兄弟与父Session隔离、跨scope/未ready/缺对象矩阵；契约10新增操作清单一致。
- [ ] 7.2 实现TTL=min配置/300秒/身份授权签名凭据剩余期，签发no-store、日志/幂等记录不存完整URL；撤一条路径按剩余路径判定。证据：撤grant/Site/成员/降级后新签发拒绝、已有URL到期窗口与到期新请求、保留其他grant，文档不承诺即时回收或强停已开始传输。
- [ ] 7.3 在真实存储验证合法Range/206/416、短时GET与attachment文件名、批准CORS与公开ACL拒绝。证据：新签URL只能读精确版本，无法列桶/读兄弟/写对象，无静态目录绕过；浏览器容器/codec限制与转码非目标明示。

## 8. 过期、残留与孤儿回收

- [ ] 8.1 实现有界过期sweep，不靠GET也能终结uploading/completing并配对failed，cancel/abort/验证失败共用清理登记。证据：重复批次/进程重启/处理后崩溃无重复终态、expires_at不延期；清扫命令与错误返回说明同步。
- [ ] 8.2 实现精确MPU abort、对象版本删除及删除后核验，等待最大已签写窗口/迟到宽限，失败重试与按ID redrive。证据：晚到part/对象、abort/delete失败、明确not-found与权限/网络错误区分，未确认删除CLI非零，首次业务失败原因不重写。
- [ ] 8.3 实现孤儿完整分页发现、持久候选/两次观察/宽限与归属标记验证，删除前查全部逻辑引用并用tombstone/generation阻止新发布。证据：活动上传/校验、ready引用、另一保留引用、未知tenant/metadata、GC-vs-finalize竞态均不误删，dry-run与实际清单可审计。
- [ ] 8.4 实现本流程监控、失败告警与操作审计，ready不按年龄删除、不发本地原件删除指令。证据：作业耗尽/孤儿积压/授权拒绝有安全ID和结果，URL/token/原始内容不入日志；runbook明确技术残留与隐私保留政策的区别。

## 9. 配置、部署和契约交付

- [ ] 9.1 提供默认关闭的媒体profile配置、参数校验与Secret引用、能力门禁和安全开发示例；生产缺决策记录拒绝启用。证据：非法容量/分片/TTL/CORS/私有存储能力负向测试、关闭时M2元数据仍可用，README/部署配置说明可执行，不连接生产。
- [ ] 9.2 提供独立worker/sweep启动、健康检查、暂停/排空/恢复与临时磁盘配额说明，固定探测器和存储集成镜像。证据：干净环境安装/启动/重启和有界清理演练，数据库/桶不会在应用启动时自动迁移创建，文档无真实Secret。
- [ ] 9.3 增量更新领域/媒体/RBAC契约与ADR/README当前事实，消除本次涉及的过期“无表”段落并保留历史；生成OpenAPI。证据：原M3五项+补充五项共10新操作，总43 paths/57 operations；原47项兼容差异仅限本提案明示，字段/错误/状态逐项核对。
- [ ] 9.4 把真实存储集成接入CI并保留现SQLite/PG完整job和精确清理，新增必需场景收集/skip守卫与脱敏证据。证据：缺前置/伪造目标/零收集/清理失败均CI非零，新存储服务不误连生产桶，PG/存储证据均绑定实际head。

## 10. 跨模块集成与 Apply 交付

- [ ] 10.1 执行完整SQLite和PostgreSQL套件及真实存储集成，含User/Edge从意图到分片中断恢复、complete/校验/ready、授权Range读取的完整链路。证据：当前代码SHA的命令、JUnit、版本/digest、收集计数与清理结果；必需场景无假跳过，无RLS/生产完成宣称。
- [ ] 10.2 运行Change/main strict、全跟踪Markdown链接、git diff --check与OpenAPI对照；按G1–G6/W1–W4/D22–D31逐项交叉检查实际交付。证据：同一head检查结果、声明/验证分离与终态配对无缺项，不能用strict代替业务测试。
- [ ] 10.3 在本Change内产出Apply证据记录，区分历史/本机/CI、SQLite/PG/真实存储、故障注入/真实传输，并列出未验证的生产/隐私/M4限制。证据：W1–W4有真实测试落点才标关闭，S1若未处理继续保留，不改M2历史报告/28任务。
- [ ] 10.4 提交到同一工作分支与Draft PR，确认最终CI绑定最新head，向工程入口/分片原任务及相关原任务追加真实交付回链。证据：无重复任务、无无关属性变更，PR仍Draft，等待单独Verify授权，未自动归档/同步主规格/合并。

## Workflow follow-up

- 本轮仅Propose：0/42，发布Draft PR并记录实际结构/链接检查，不执行上述实施任务。
- Q1/Q3/Q4等待负责人审阅；收到新的明确Apply授权后，按确认范围推进同一Change，不能把参数答复本身当Apply。
- 独立Verify、Archive、主规格同步、PR Ready与Merge分别遵循后续授权；没有任何一项由本清单完成自动触发。
- Q2生产政策、Q8后续模块与M4完整同步系统不并入本Change，不创建重叠Change或重复Notion任务。
