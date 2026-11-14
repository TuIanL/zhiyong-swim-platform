# Spec Delta

## Purpose

定义训练会话与视频逻辑资产的资源级读取授权：S-read、S-manage、A-read 三项能力的判定、授权记录的持久化与撤销、未来资产覆盖、权限失效的即时生效，以及先过滤后分页的暴露规则。

## ADDED Requirements

### Requirement: Three resource capabilities drive every decision

每次 Session 与 Asset 的读取、管理、授权与上传意图请求 SHALL 按 S-read、S-manage、A-read 之一判定，判定 MUST 使用当前请求时刻的机构成员、角色、场馆访问与授权记录状态，不得使用登录时的权限快照或缓存结果。

#### Scenario: Creator keeps read and manage

- **WHEN** 创建该 Session 的 Coach 仍具该 Site 访问权并读取与修改该会话
- **THEN** 服务 MUST 各返回 200

#### Scenario: Site access alone is not resource access

- **WHEN** 具该 Site 访问权但既非创建者也无有效 grant 的 Coach 请求他人 Session 详情
- **THEN** 服务 MUST 返回 404 且不返回任何会话字段

#### Scenario: Read does not imply manage

- **WHEN** 仅经 Session read grant 可读该会话的 Coach 提交 PATCH
- **THEN** 服务 MUST 返回 403 且不修改记录

### Requirement: Owner and admin scope is tenant-wide

Owner 与 Admin SHALL 在本机构全部场馆管理与读取 Session 与 Asset，不依赖显式 SiteMembership，且其权限 MUST NOT 延伸到其他机构。

#### Scenario: Manager without explicit site grant

- **WHEN** 本机构 Admin 未获该 Site 的显式成员授权而读取该场馆某 Session 与其 Asset
- **THEN** 服务 MUST 返回 200

#### Scenario: Cross-tenant manager

- **WHEN** A 机构 Owner 使用 B 机构的 tenant_id 或 site_id 请求资源
- **THEN** 服务 MUST 返回 404 且不泄露该资源是否存在

### Requirement: Non-manager paths require the current coach role

非 Owner/Admin 路径 SHALL 要求调用者当前角色为 coach，且该角色 MUST 在每个请求上重新判定；角色降级后，即使仍保留 SiteMembership、即使 grant 未到期，三项能力全部不成立，授予时的角色检查 MUST NOT 替代请求时的判定。

#### Scenario: Coach baseline before downgrade

- **WHEN** 具该 Site 访问权的 Coach 创建 Session，并读取该 Session 与其下 Asset、修改该 Session
- **THEN** 服务 MUST 各返回 201 或 200，作为降级前的对照基线

#### Scenario: Downgrade revokes creator rights without touching site membership

- **WHEN** Owner 把该 Coach 降级为 athlete 且刻意保留其 SiteMembership，随后该原创建者读取 Session、读取其中 Asset、提交 PATCH
- **THEN** 读取与 PATCH MUST 全部返回 404，且数据库中该 Site 的成员关系与资源记录 MUST 保持不变

#### Scenario: Unexpired grant does not survive the downgrade

- **WHEN** 降级为 athlete 的用户持有一项未过期的 Session read grant 或 Asset read grant
- **THEN** 其读取 MUST 返回 404，grant 记录 MUST 不被自动删除但不再生效

### Requirement: Session read grant covers current and future assets

一项有效 Session read grant SHALL 覆盖该 Session 当前与之后新增的全部 Asset；覆盖 MUST 在每次读取时按父 Session 判定，不得依赖授权时刻已存在的资产清单。该 grant 只授予读取。

#### Scenario: Asset created after the grant

- **WHEN** 会话创建者或本机构管理员在该会话下新建上传意图后，已获 Session grant 的 Coach 读取这个新 Asset
- **THEN** 服务 MUST 返回 200；该 Coach 自己提交上传意图 MUST 返回 403

#### Scenario: Asset created before the grant

- **WHEN** 会话中先存在 Asset，之后才授予该 Coach Session read grant
- **THEN** 该 Coach 读取既有 Asset MUST 返回 200

#### Scenario: Grant expiry ends coverage

- **WHEN** 服务端时间越过该 grant 的 expires_at 后，该 Coach 读取该 Session 或其 Asset
- **THEN** 服务 MUST 返回 404，且 grant 记录仍保留、不因过期被删除

### Requirement: Asset read grant is limited to its asset

单 Asset read grant SHALL 只授予该 Asset 的读取，MUST NOT 开放父 Session 详情、该 Session 的资产子列表或同场馆的兄弟 Asset。

#### Scenario: Asset detail without session access

- **WHEN** 只持有某 Asset read grant 的 Coach 读取该 Asset 详情
- **THEN** 服务 MUST 返回 200

#### Scenario: Asset grant cannot open the session

- **WHEN** 同一 Coach 读取其父 Session 详情或该 Session 的资产子列表
- **THEN** 服务 MUST 各返回 404

#### Scenario: Sibling asset stays hidden

- **WHEN** 同一 Coach 读取同 Session 另一下载或采集的 Asset
- **THEN** 服务 MUST 返回 404

### Requirement: Grant administration requires manager role and eligible grantee

授予与撤销资源读取授权 SHALL 仅由本机构 Owner 或 Admin 执行；受授人 MUST 为同机构成员、角色为 coach 且具目标 Site 访问权；Coach MUST NOT 授予、撤销或转授任何资源授权。

#### Scenario: Coach attempts to grant

- **WHEN** Coach 对自己可读的 Session 调用授权写入
- **THEN** 服务 MUST 返回 403 且不写入授权记录

#### Scenario: Ineligible grantee

- **WHEN** 受授人是其他机构成员或不存在，或虽是本机构成员但角色不是 coach、或缺少该 Site 访问权
- **THEN** 前两者 MUST 返回 404，后者 MUST 返回 422 `grantee_not_eligible`，且三种情形均不写入授权记录

#### Scenario: Repeatable grant write

- **WHEN** Owner 对同一 Session 与同一 Coach 重复提交授权写入
- **THEN** 服务 MUST 返回 204，且只保留一条有效授权记录，重复写入不产生第二条有效路径

### Requirement: Revoking one path preserves other paths

撤销一条授权 SHALL 只移除该授权路径；创建者身份、另一项有效授权与 Owner/Admin 本机构范围 MUST 继续按剩余路径生效，撤销 MUST NOT 删除资源、资产或他人的授权记录。

#### Scenario: Session grant revoked, asset grant remains

- **WHEN** Coach 同时持有 Session grant 与某个 Asset 的 grant，之后仅撤销 Session grant
- **THEN** 该 Coach 读取该 Asset MUST 仍为 200，读取该 Session 详情与其子列表 MUST 变为 404

#### Scenario: Asset grant revoked, session grant remains

- **WHEN** 仅撤销该 Asset 的 grant 而 Session grant 仍有效
- **THEN** 该 Coach 读取该 Asset MUST 仍为 200

#### Scenario: Creator path survives revocation

- **WHEN** 撤销某 Coach 对自己创建的 Session 的 grant
- **THEN** 该 Coach 读取该会话 MUST 仍为 200

#### Scenario: Repeat revocation

- **WHEN** 对同一授权重复提交撤销
- **THEN** 服务 MUST 返回 204，且不覆盖首次撤销的执行者与时间

### Requirement: Access loss overrides unexpired grants

机构成员身份、角色或 Site 访问失效时 MUST 立即阻止该用户经任何授权读取，即使授权未到期且记录仍在；该失效 MUST NOT 级联删除授权记录、Session 或 Asset。

#### Scenario: Site access removed

- **WHEN** Owner 移除该 Coach 对本 Site 的访问后，该 Coach 使用未到期的 Session grant 读取会话
- **THEN** 服务 MUST 返回 404，且授权记录仍存在

#### Scenario: Membership removed

- **WHEN** 该 Coach 被移出机构后再次读取该会话或其 Asset
- **THEN** 服务 MUST 返回 404

#### Scenario: Role downgraded

- **WHEN** 该 Coach 被降级为 athlete 后读取该会话
- **THEN** 服务 MUST 返回 404，且本切片 MUST NOT 因此开放学员读取路径

### Requirement: Check order and status codes

请求 MUST 先验证身份后验证资源：身份无效 401，非机构成员或资源不在可见范围 404，已可读该资源但缺少所需能力 403，字段或枚举无效 422，状态机不允许 409；错误 MUST NOT 泄露调用者无权知晓的资源存在性。

#### Scenario: Anonymous request

- **WHEN** 未携带有效 Bearer 的请求访问任一新增操作
- **THEN** 服务 MUST 返回 401

#### Scenario: Guessing a foreign resource

- **WHEN** 本机构成员使用另一机构的 tenant_id、另一场馆的 site_id 或不属于该范围的 session_id/asset_id
- **THEN** 服务 MUST 返回 404 且响应体不包含该资源字段

#### Scenario: Invalid input versus illegal transition

- **WHEN** 请求携带非法枚举、空 PATCH 或未知字段，或携带合法状态但当前状态机不允许该迁移
- **THEN** 前者 MUST 返回 422，后者 MUST 返回 409

### Requirement: Filtered pagination precedes exposure

Session 与 Asset 列表 SHALL 先按资源谓词过滤再形成页与 next_cursor，MUST NOT 返回未授权资源的数量或由此产生的总数差异；每页 MUST 重新校验当前身份与授权，旧游标 MUST NOT 绕过撤权；游标 MUST 绑定机构、场馆、筛选条件与排序版本。

#### Scenario: Page two after revocation

- **WHEN** 调用者持第一页游标请求第二页，而其授权在两次请求之间被撤销
- **THEN** 第二页 MUST 只包含当前仍可见的资源，缺失的资源 MUST NOT 以占位或计数暴露

#### Scenario: Cursor bound to its scope

- **WHEN** 调用者把某场馆或某筛选条件的游标用于另一场馆、另一筛选或不同排序版本
- **THEN** 服务 MUST 返回 422 `invalid_cursor`

#### Scenario: Bounded page size

- **WHEN** 调用者请求 limit 超过上限或非正整数
- **THEN** 服务 MUST 返回 422；未指定 limit 时 MUST 使用既定默认值

#### Scenario: No unauthorized totals

- **WHEN** 任一列表响应返回
- **THEN** 响应 MUST NOT 包含未授权资源的 total_count 或等价总数字段
