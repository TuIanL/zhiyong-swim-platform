# Verification Report: define-cloud-capture-media-contracts

- 核验日期：2026-11-10（Asia/Shanghai）。
- **固定核验对象：[f029864b3d716306f3147faf80655cf4851f8bc8](https://github.com/TuIanL/zhiyong-swim-platform/commit/f029864b3d716306f3147faf80655cf4851f8bc8)**。本报告是其后的独立记录，不属于被核验交付，不随报告提交改变核验对象。
- main事实基线：`afb0e5fce4c187c8d3c3d5607d2a675375c2a04d`；交付入口：[Draft PR #3](https://github.com/TuIanL/zhiyong-swim-platform/pull/3)。
- 本轮只执行Verify并发布报告/回链，没有修改交付文档、任务勾选、业务代码、数据库、迁移、OpenAPI、主规格或CI配置；不执行Apply、Archive、主规格同步或Merge。

## 最终结论

**CRITICAL 0 / WARNING 0 / SUGGESTION 0。11/11文档任务实际交付成立；D1–D10、C1–C5及专项契约检查通过。**

六类标准检查中，3项适用并完整执行，3项因纯文档 `skip_specs: true` 为 **Not applicable**；**Not verified 0**。并未将有意跳过的规格当作缺失，也未把新实体尚无实现当成本change遗漏。

**All applicable checks passed. Ready for archive.** 这是文档change的建议性核验结论，不是归档授权、PR合并批准或总体平台验收。本轮停在独立Verify完成，等待项目负责人下一步授权。

## Summary scorecard

| 维度 | 结果 |
| --- | --- |
| Completeness | CLI11/11与实际文档逐项对应；Spec Coverage为Not applicable（本change有意无delta specs） |
| Correctness | 文档字段/状态/权限/错误/并发约定专项核对通过；Requirement Implementation Mapping和Scenario Coverage为Not applicable（无行为规格增量） |
| Coherence | D1–D10、C1–C5与领域/API/ADR一致；文档命名、目录、草案标识、接线和禁改范围一致 |

| 标准检查 | 处理 |
| --- | --- |
| Task Completion | 通过；apply上下文taskTrackingConfigured=true，11 complete/0 remaining，无不可读tracking文件 |
| Spec Coverage | Not applicable；CLI报告specs skipped，.openspec.yaml声明skip_specs=true，无新增/修改/删除/重命名规格 |
| Requirement Implementation Mapping | Not applicable；同上，不杜撰产品行为要求或以旧cloud-identity当新交付 |
| Scenario Coverage | Not applicable；同上；本报告仍独立核对文档中的关键正负场景，不冒充运行测试 |
| Design Adherence | 通过；10项设计与5项来源处理逐项追溯，见下表 |
| Code Pattern Consistency | 通过；本change实施物是文档，已核对文档目录/命名/草案边界/接线模式；无业务代码变更，不外推为业务代码或运行安全审查 |

## 证据索引与固定范围

下列行号全部取自f029864；本轮直接阅读文件和对应Git对象，而不是沿用任务勾选、Apply自检或上轮审阅结论。

| 简称 | 文件 |
| --- | --- |
| M | [领域模型](../../../docs/architecture/cloud-capture-media-domain.md) |
| A | [API契约](../../../docs/contracts/cloud-capture-media.md) |
| R | [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) |
| E | [Apply交叉核对记录](../../../docs/verification/cloud-capture-media-contracts-apply.md)，作为被核对交付，不代替本报告 |
| B | [既有领域模型接线](../../../docs/architecture/cloud-domain-model.md) |
| P / D / T | [proposal](proposal.md) / [design](design.md) / [tasks](tasks.md) |

源页面重新读取：Notion [07数据模型/API草稿](https://www.notion.so/410f602574aa81cda7bff8c3ed483f4d)、[03云端SaaS草稿](https://www.notion.so/410f602574aa8170b565f7fc4c5eab30)、[数据模型原任务](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)、[架构/API原任务](https://www.notion.so/410f602574aa816582ccc14817ce4601)及设计列出的媒体授权/Edge注册/分片上传/组织模型依赖任务。两项总体任务仍进行中，依赖任务仍为未开始/待确认，没有把文档子范围当全平台完成。

## Completeness：11项任务实际证据

| 任务 | 独立核对的交付与位置 | 结果 |
| --- | --- | --- |
| 0.1 评审结论与范围 | R:3–16记录真实设计基线、2026-11-09评审/文档Apply边界；R:22–43列C1–C5及D1–D10采纳/延后、理由和替代；R:52–67分列业务实施门槛；与Notion历史记录、P:48–50对应 | 通过 |
| 1.1 模型/字段/约束 | M:18–74为ERD、基数、复合键/外键/索引建议；M:78–157为四实体及支持概念字段、可空性、来源/默认；M:121–148含统一采集原始字段、基准、clock source、可空偏差/精度、received_at/created_at；M:159–167资源身份与grant语义 | 通过 |
| 1.2 状态与历史 | M:169–191枚举实体/上传状态及终态资产映射，取消/完成/中止/到期的原子性、失败重试、新ID、搬迁历史、父级保留和离线边界；与A:131–147一致 | 通过 |
| 2.1 API/权限 | A:17–48定义S-read/S-manage/A-read、Owner/Admin/Coach、grant范围与撤销；A:54–88完整展开33个建议HTTP操作；A:96–111列请求，SessionPatch在104；实际OpenAPI仍为既有14 paths/19 operations | 通过 |
| 2.2 上传/幂等/错误 | A:131–177覆盖分片恢复/服务端校验、202查询、终态事务、身份分层幂等、一次性凭据例外及401/403/404/409/422；不同设备同SHA保留独立asset_id和来源 | 通过 |
| 2.3 版本与边界 | A:3–15草案标识及不改既有接口；A:44–48短期URL和撤权限制；A:113稳定游标/重验；A:179–190离线及实施前置；未知参数不伪装成已批准实现 | 通过 |
| 3.1 ADR | R:1–67完整记录C1–C5、D1–D10、特别授权语义、未决存储/MediaBlob/保留/离线门槛，区分设计方向批准与业务实施授权 | 通过 |
| 3.2 既有文档接线 | B:108–122及Git差异只改未来实体表两行和相邻说明，指向已存在草案/ADR并保留未实现；既有六表字段/约束和历史事实未改 | 通过 |
| 4.1 跨文档核对 | E:12–71存在设计/来源/权限/字段/状态/历史和W1/W2/S1/S2核对记录；本轮重新逐项比对M/A/R及D/T，专项结果见后文，不以E自检替代独立结论 | 通过 |
| 4.2 结构/链接/回链 | 本轮change strict、主规格strict均1/1通过；复核原9份Markdown的51处本地链接及全部32份跟踪Markdown的114处本地链接（含1锚点），0失效；Git diff检查通过；PR/Notion绑定f029864与实际CI | 通过 |
| 4.3 范围/发布 | main..f029864恰为10个规划/文档/证据文件；services、scripts、configs、.github、主规格、OpenAPI、README与依赖均未改；CI原始证据独立读取；用户模板/agent记忆未入PR，本轮另保存4份保护文件哈希 | 通过 |

P:42–46、52–67的0/11为明确标注的Propose历史，T及本轮CLI为当前11/11；没有把历史阶段当当前进度。纯文档交付中的“未实现”指四实体业务能力，不否定三份文档已交付。

## Coherence：D1–D10与C1–C5

| 决策 | 核对重点与交付证据 | 结果 |
| --- | --- | --- |
| D1 固定归属 | M:39–62、159–163；A:94–107；R:34：复合归属、创建后不可变，搬迁重新登记保留旧来源，不直接复制旧CASCADE | 一致 |
| D2 来源链 | M:45–60、125–130；A:21、106–108；R:35：Edge来源匹配认证节点/设备，manual为空，derived保留父来源 | 一致 |
| D3 身份与资源权限 | M:166–167；A:17–48、54–88；R:36、47–49：场馆访问不是全场视频权限，读不等于管理/上传/转授权，不接管他人上传 | 一致 |
| D4 云端最终权威 | M:106–119、175、183；A:147、181；R:37、50：Session不绑单节点，云端权威兼容Edge离线临时记录，协议另Change | 一致 |
| D5 不可变/派生 | M:125–130、159–165；A:157–163；R:38：派生同tenant/site/session、父ready、父引用固定；自引用/环及origin配对不冒充纯FK保证 | 一致 |
| D6 上传完整性 | M:155、177–181；A:131–145；R:39：分片恢复、可信整对象校验、202查询、终态/Asset原子配对及重试，不以客户端回执置ready | 一致 |
| D7 三层身份 | M:164–165；A:149–163；R:40：请求幂等与asset_id、SHA物理比较分开；同hash不同来源独立，MediaBlob不建表 | 一致 |
| D8 路径/分页/错误 | A:50–129、165–177；R:41：33个建议操作覆盖设计操作面，资源先过滤、cursor重查、5分钟URL限制，旧19操作不变 | 一致 |
| D9 删除与保留 | M:185–191；A:179–183；R:42：四实体无DELETE，Site/Tenant不得级联抹历史，共享内容无其他保留引用才可清理 | 一致 |
| D10 采集时间/本地原件 | M:132–148、183–190；A:108、120、129、181–189；R:43：原始时间、设备基准/来源、不确定性及服务端时间分开；ready不自动删除本地原件 | 一致 |

| 来源比较 | 独立核对 | 结果 |
| --- | --- | --- |
| C1 | Notion07 §6及上传任务确有分片/续传/SHA-256/确认；M上传支持概念、A§5、R:22承接，没有降为单次PUT | 一致 |
| C2 | 07实体表是TrainingSession/AnalysisTask，/training-tasks出现在API域；D/R区分训练计划、实际Session、分析任务，离线协议未擅自实现 | 一致 |
| C3 | 03/组织任务包含Pool/Lane，R:24明确延后；M/A未增加其字段、表或API | 一致 |
| C4 | 03/07为草稿角色/路径建议；R:25及A§2–3落实四角色及更窄Coach资源权限，不把草稿平台角色写成已实现 | 一致 |
| C5 | 07幂等建议被A§6及R:26精确承接，未写成既有接口已有幂等，也未用checksum替代采集身份 | 一致 |

## Correctness：专项边界与此前审阅项

| 项目/场景 | 本轮核验的约定与证据 | 结果 |
| --- | --- | --- |
| W1 采集命名 | M:133、A:108/120、T:11均使用device_capture_started_at_raw / device_capture_ended_at_raw；独立查找无旧裸名别名，UTC派生/原始/接收时间职责分开 | 已关闭且复核通过 |
| W2 上传终态 | M:177–181与A:135–147一致：completed→ready；failed/aborted/expired→未完成Asset.failed；Asset与UploadSession同事务提交，取消先赢则失败并409，完成先赢不回退ready，到期终结可重试 | 已关闭且复核通过 |
| 并发/提交失败 | cancel/complete/abort/expiry需串行化或当前状态条件更新；提交失败不允许只写一侧，重复请求读取唯一已提交结果；这些是明确文档契约，不是已运行数据库测试 | 文档约定通过 |
| S1 SessionPatch与错误 | A:104、145、174–177：title-only合法；status可省略但提供时须非空有效枚举；空PATCH/无效字段/枚举422，合法目标的状态机冲突409 | 已关闭且复核通过 |
| S2 链接证据 | 独立扫描清单和计数与E:81一致，原9份/51链接/0失效；本轮扩大到目标提交全部32份/114链接/1锚点，仍0失效 | 已关闭且复核通过 |
| Coach/Owner/Admin | A:23–42：Owner/Admin仅本机构；Coach需当前成员+Site+创建者/grant。Session grant涵盖授权期间当前/未来子资产，单Asset grant不开放父Session/兄弟资产，读grant不授予S-manage | 通过 |
| 撤权与多路径 | A:37–48、113：每请求/续页重查；撤销一条路径不消除其他合法路径；失去角色/Site/成员资格仍阻断。新URL不再签发，已签URL可在5分钟上限内继续有效 | 通过 |
| 上传主体与凭据 | A:21、33、78–90、153–155：User/Edge主体分开且上传限原发起者；幂等不绕过授权；凭据明文不缓存/重放 | 通过 |
| 来源/派生/相同内容 | M:45–62、159–165及A:157–163：跨归属/跨Session派生不允许；不同采集同SHA保留独立来源/ACL/身份；物理复用不是授权或删除依据 | 通过 |
| 历史与离线 | M:183–191、A:179–190：云端最终状态不否定本地临时采集，后续接纳协议未定义；父级删除不得毁历史/共享保留引用，原件不因ready自动删 | 通过 |

## 本轮实际命令、链接范围与Git证据

- 在CLI解析的正式根目录运行 `openspec status --change define-cloud-capture-media-contracts --json` 和 `openspec instructions apply --change define-cloud-capture-media-contracts --json`；后者仅作读取上下文，未实施任务。返回11/11、无剩余或不可读文件，全部产物done或skipped。
- `openspec validate define-cloud-capture-media-contracts --strict --json`：1/1 passed，唯一INFO为skip_specs，不是缺陷；`openspec validate --specs --strict --json`：cloud-identity 1/1 passed。
- `git diff --check afb0e5f..f029864`通过；逐路径确认业务源码/迁移、脚本、配置、CI、主规格、OpenAPI、README与依赖未改。现有OpenAPI仍14 paths/19 operations；新API文档独立枚举33个建议operation，无重复方法/路径。
- 目标9份链接扫描清单：M、B、A、R、E及本change的README.md/proposal.md/design.md/tasks.md。实际51个本地路径链接、0锚点、0失效；全目标32份跟踪Markdown为114个本地链接、含1锚点、0失效。报告新增后的自身链接单独检查，不把它计入f029864的上述数量。
- 不运行本机业务测试、不连接数据库、不执行迁移；静态文档核对与已有CI基线证据分列。用户模板及agent记忆4份文件与本轮起点哈希一致，原交付70个跟踪文件保持原字节；仅新增本verification.md。

## 固定目标CI的独立取证

[Actions run 42604774371](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42604774371) 的head与f029864一致，两个job及清理/上传均success。本轮重新读取两job日志，并下载[原始artifact 13667362000](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42604774371/artifacts/13667362000)核对，不仅采用PR上的绿灯或历史摘要。

| 证据 | 实际结果 |
| --- | --- |
| SQLite job 129117822538 | 112 passed / 39 PG专属skipped，1项既有弃用警告；无失败 |
| PostgreSQL job 129117822991 | 150 passed / 1 SQLite专属skipped，shared111/postgresql39，1项既有弃用警告；无失败 |
| 原始PG JUnit | tests=151、failures=0、errors=0、skipped=1 |
| 原始摘要 | run_id=83cb7bf9561bdf83，linux/amd64，result=passed、cleanup=removed、pytest_exit_code=0、exit_code=0 |
| CI兜底清理 | inspect确认absent，result=passed、exit_code=0；上传success |
| artifact ZIP SHA-256 | c085da782c424672d12e99052377c0bb5c1d8cfaa59b5498dd54e0e8b3098988，与GitHubartifact digest相同 |
| GitHub临时merge ref | fded8af是f029864与main afb0e5f的测试组合，不是实际PR合并 |

证据副本位于忽略目录 `var/verify-f029-evidence/`，不提交。CI只回归当前六表基础，不证明未来资源级授权、上传事务、存储或离线同步已实现；本报告验证的是这些契约作为文档交付的一致性。报告提交触发的新CI与本固定目标CI分开，最终发布记录绑定在PR/Notion，不改变被核验SHA。

## Issues by Priority

### CRITICAL：0

未发现未完成的文档任务或缺失的必需交付；没有通过补业务代码、修改数据库或扩大范围消除问题。

### WARNING：0

本轮未发现新的适用范围内设计/契约偏离。既有W1/W2均由目标内容重新核对，未依赖“已关闭”标签推断通过。

### SUGGESTION：0

未发现需要单列的显著文档模式改进项。MediaBlob、存储/保留期限、实际授权表、离线协议、业务权限/并发测试、RLS及生产原本属于后续范围，不将它们发明为本change的遗留缺陷。

## 停止边界

本报告给出文档change独立Verify结论；现有任务11/11不变。Draft PR #3未合并、change未归档、主规格未同步。两项Notion总体任务保持进行中。等待负责人下一步授权；不会因“Ready for archive”自行执行Archive或Merge。
