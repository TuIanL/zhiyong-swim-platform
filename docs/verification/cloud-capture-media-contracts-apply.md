# 采集与媒体契约文档 Apply 交叉核对记录

> **Apply 集成证据；不是独立 Verify 报告。**
>
> 本记录只核对 `define-cloud-capture-media-contracts` 文档 Apply 所要求的设计一致性与范围。四实体及所有新 API 仍未实现；本记录不执行或替代独立 Verify。

- 核对日期：2026-11-09（Asia/Shanghai）
- Proposal / 设计基线：`c07f20e103155aca5de9523be670dae813638cbc`
- main 基线：`afb0e5fce4c187c8d3c3d5607d2a675375c2a04d`
- 交付：[领域模型草案](../architecture/cloud-capture-media-domain.md)、[API 契约草案](../contracts/cloud-capture-media.md)、[ADR 0003](../decisions/0003-capture-media-domain-contracts.md)、[既有领域模型接线](../architecture/cloud-domain-model.md)。

## 1. 设计编号追溯

| 决策 | 领域模型 | API 契约 | ADR | 交叉核对结论 |
| --- | --- | --- | --- | --- |
| D1 固定归属/迁场重新登记 | `2、`4、`6 | `3、`4、`8 | `3 D1 | tenant/site/session/source 只创建时确定；四文档均不允许原地迁移，历史仍引用旧 ID |
| D2 节点/设备/来源链 | `2、`3.1–3.5、`4 | `2.1、`3、`4 | `3 D2 | Edge 来源由认证节点与 Device 确认；人工来源无设备；派生来源沿父链 |
| D3 用户/Edge 与资源权限 | `4 | `2、`3、`7 | `3 D3、`3.1 | Owner/Admin 本机构范围；Coach 还需资源谓词；grant 只读；无授权表实现 |
| D4 云端 Session 权威与离线 | `5 | `5、`8 | `3 D4、`3.1 | 云端最终状态与 Edge 离线临时记录兼容；同步协议未定义 |
| D5 Asset 不可变/派生隔离 | `2、`3.4、`4、`5 | `2.2、`4–6 | `3 D5 | 派生父 Asset 同 tenant/site/session 且 ready；字节相同不共享 ACL |
| D6 分片与完整性 | `3.5、`5 | `3、`5、`7 | `2 C1、`3 D6 | 服务端整对象校验成功才 ready；客户端分片回执不能替代 |
| D7 幂等/逻辑身份/物理复用 | `2.1、`3.4、`4 | `4–6 | `2 C5、`3 D7 | 同一请求重试才复用逻辑结果；不同设备/采集同 SHA 有独立 asset_id/来源/权限；MediaBlob 延后 |
| D8 路径/权限过滤/分页/播放 | `4 | `2–7 | `3 D8、`3.1 | 全部操作有完整建议路径、主体、字段和状态；先资源过滤再分页；URL撤权有明确上限 |
| D9 四实体与父级删除 | `6 | `8–9 | `2 C3 说明、`3 D9 | 无四实体 DELETE；Site/Tenant 不得级联抹除历史或保留引用；期限和物理清理待定 |
| D10 时间/离线与本地原件 | `3.4、`5–6 | `4、`8–9 | `3 D10 | 原始采集时钟与服务端时间分离；离线临时记录不等于云端最终状态；ready 不自动删本地原件 |

## 2. 来源差异追溯 C1–C5

| 来源编号 | 来源核对及处理 | 文档位置 |
| --- | --- | --- |
| C1 分片续传 | Notion 07 `6 与分片上传任务保持分片、恢复和完整对象校验语义；未缩减成一次 PUT | 领域模型 `3.5/`5；API `3/`5；ADR `2 C1 / D6 |
| C2 Session/训练任务与离线 | 区分 TrainingSession、TrainingTask 路径和 AnalysisTask；支持离线临时记录，协议另 Change | 领域模型 `1/`5；API `8；ADR `2 C2 / D4 / D10 |
| C3 Pool/Lane | 记为组织模型依赖，不加未来 Pool/Lane 字段、实体或操作；D9 的父级保留按负责人评审要求写入 | 领域模型 `1/`6；API `8–9；ADR `2 C3 / D9 |
| C4 路径与角色 | Notion 草稿不冒充已实现角色政策；采用 Owner/Admin 机构范围与 Coach 资源级读取边界 | 领域模型 `4；API `2–3；ADR `2 C4 / D3 / D8 |
| C5 幂等 | 只对明确写请求建议幂等；SHA-256 不代替采集身份；一次性密钥不重放 | 领域模型 `3.4/`4；API `6；ADR `2 C5 / D7 |

## 3. 权限与 URL 专项场景

| 场景 | 结果约定 | 文档一致性 |
| --- | --- | --- |
| 同一 Site 的 Coach 无自己的创建关系、无 grant | Session 列表不含该行；详情/播放按不可见资源 404；不因 SiteMembership 放行 | Design D3/D8；领域模型 `4；API `2–3 |
| Coach 获得有效 Session read grant | 能读取该 Session 和授权期间其现有及未来新增的全部子 Asset；每次仍验证成员、Site 与 grant | 领域模型 `4；API `2.2；ADR `3.1 |
| Session grant 生效后才创建新 Asset | 新 Asset 自动落在该 Session 授权覆盖范围，不需另建资产级 grant | API `2.2；ADR `3.1 |
| 只有 Asset read grant | 只能通过 Asset 详情/播放读取目标 Asset；不得看父 Session、兄弟 Asset 或 Session 子列表 | Design D3/D8；领域模型 `4；API `2.2 |
| 撤销 Session grant，但存在另一合法访问路径 | 只移除被撤销路径；依创建者、Asset grant 或 Owner/Admin 当前范围另行判定 | 领域模型 `4；API `2.2；ADR `3.1 |
| 撤权后再次查详情或请求新播放 URL | 后续 API 检查/签发立即拒绝已撤销路径 | API `2.2–2.3；ADR `3.1 |
| 撤权前已经签发播放 URL | URL 持有者在 URL 到期前仍可能访问；建议 TTL ≤ 5 分钟，不声称即时撤回 | API `2.3；ADR `3 D8 / `3.1 |
| Coach 有 read grant 尝试修改 Session、上传或转授权 | 拒绝；S-read/A-read 不蕴含 S-manage | 领域模型 `4；API `2.1–2.2；ADR `3 D3 |
| Owner/Admin 访问本机构其他 Site 资源 | 本机构管理范围允许，不要求 SiteMembership；仍不能跨 tenant | API `2.1；ADR `3 D3 |

## 4. ERD、字段、状态、API 与历史交叉核对

- **ERD ↔ 复合约束：** Device 与 EdgeNode、Session 与 Site、Asset 与 Session、派生 Asset 与父记录的租户/场馆关系在 ERD/键表/字段中一致；只把 FK 可以表达的事实列为 FK，状态、互斥主体和无环另需实现逻辑。
- **字段 ↔ API：** Capture metadata 的原始采集时间统一为 `device_capture_started_at_raw` / `device_capture_ended_at_raw`，API 请求与领域字段同名；另有时间基准、时区/偏移、视频时间轴映射、NTP/PTP/GPS/manual/unknown 来源、可空偏差/精度；received_at/created_at 单列为服务端时间，API 不接受其由客户端覆盖。
- **幂等 ↔ 资产身份：** 同键同参重放复用同一请求结果；同键异参 409；并发单资源。另一设备或另一次采集即使同 SHA，也创建不同逻辑资产，不因物理复用而共享 grant/生命周期。
- **状态 ↔ API：** UploadSession.completed 与 Asset.ready 原子配对；failed/aborted/expired 和 Session cancel 先获胜均使未完成 Asset.failed；取消、complete、abort、expiry 通过事务串行化或条件更新仅允许一个结果获胜，到期终结可重试；Session 已取消时 complete 返回409。字段或枚举无效返回422，合法目标状态与当前状态机冲突返回409；Session completed 后补传不回退状态。
- **SessionPatch ↔ 错误：** 允许只改 title；status 为可选字段，提供时枚举必须有效且满足状态机；空 PATCH 返回422，合法但当前状态不允许的迁移返回409。
- **凭据与上传主体：** 用户 Bearer 与 EdgeCredential 分离；User/Edge 发起者恰一；操作上传会话须原发起者。Owner/Admin 管理资源不等于代替上传者。
- **删除 ↔ 保留：** 四实体无 DELETE；Site/Tenant 历史与仍保留的共享内容不能经父删除/级联丢失；物理清理须无其他保留引用；既有六表 CASCADE 不扩展。
- **源代码事实 ↔ 草案：** 现有六表和 19 个 operation 继续由既有契约描述；新 ERD/端点明确为未实现草案，不将自动化基线 CI、strict 或旧验证结果写成新能力测试。

## 5. 独立审阅问题定向修订

2026-11-09 的 Apply 独立审阅结论为 CRITICAL 0、WARNING 2、SUGGESTION 2；本次仅按 W1、W2、S1、S2 修订文档、任务验收描述和证据记录，D1–D10 总体方向不变，也不新增实现范围。

| 审阅项 | 修订结论 | 对应位置 |
| --- | --- | --- |
| W1 采集时间字段 | 领域模型与 API 请求统一使用 `device_capture_started_at_raw` / `device_capture_ended_at_raw`，无内部/外部别名映射 | 领域模型 `3.4`；API `4`；任务 `1.1` |
| W2 上传终态 | completed→Asset.ready；failed/aborted/expired→未完成 Asset.failed；Session cancel 先获胜则上传失败、Asset.failed、complete 返回409；终态更新同事务，竞态串行化或条件更新，到期处理可重试 | 领域模型 `5`；API `5/7`；任务 `1.2/2.2` |
| S1 SessionPatch | 仅 title 的 PATCH 合法；status 可省略但若提供须是有效且可迁移的状态；空 PATCH 为422 | API `4/7`；任务 `2.1` |
| S2 链接证据 | 实际扫描9份 Markdown、51个本地链接、0失效；检查文件清单见下方结构检查表 | 本记录 `5.1` |

## 5.1 Apply 范围与结构检查

本文件是文档间的一致性核对记录，不运行服务、数据库、迁移、API、业务测试或独立 Verify。结构检查与语义核对分开：

| 检查 | 实际命令/来源 | 结果 |
| --- | --- | --- |
| Change strict | `openspec validate define-cloud-capture-media-contracts --strict --json` | 1/1 passed、0 failed；唯一 INFO 为 .openspec.yaml 设置 skip_specs，表示本 change 无规格增量 |
| 主规格 strict | `openspec validate --specs --strict --json` | cloud-identity 1/1 passed，0 failed；主规格文件未修改 |
| Markdown 本地链接 | Python 3 临时 Markdown 链接解析器，共扫描9份 Markdown并解析本地相对路径及标题锚点：`docs/architecture/cloud-capture-media-domain.md`、`docs/architecture/cloud-domain-model.md`、`docs/contracts/cloud-capture-media.md`、`docs/decisions/0003-capture-media-domain-contracts.md`、`docs/verification/cloud-capture-media-contracts-apply.md`、`openspec/changes/define-cloud-capture-media-contracts/README.md`、`proposal.md`、`design.md`、`tasks.md` | 51 个本地链接已检查，0 个失效 |
| whitespace | `git diff --check` | 本次修订后的差异检查通过；Git 发布范围与未跟踪保护文件另在 PR/Notion 当前 head 记录 |

这些结果只证明结构、相对链接和差异格式，不验证运行中的业务行为。原有业务测试未运行；没有新表、新接口、迁移或生产/RLS 验收。发布后实际 PR head、对应 CI 状态和 Notion 保存情况由同一 PR 与工程入口/原任务的最终同步记录绑定，不能把旧 head CI 当作本次文档验证。
