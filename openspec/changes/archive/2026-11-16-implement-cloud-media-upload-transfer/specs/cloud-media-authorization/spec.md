# Spec Delta

## MODIFIED Requirements

### Requirement: Grant administration requires manager role and eligible grantee

授予与撤销资源读取授权 SHALL 仅由本机构 Owner 或 Admin 执行；受授人 MUST 为同机构成员、角色为 coach 且具目标 Site 访问权；Coach MUST NOT 授予、撤销或转授任何资源授权。重复 PUT SHALL 保留首次 granted_at 与 granted_by_user_id，只允许修改期限和最近更新时间。

#### Scenario: Coach attempts to grant

- **WHEN** Coach 对自己可读的 Session 调用授权写入
- **THEN** 服务 MUST 返回 403 且不写入授权记录

#### Scenario: Ineligible grantee

- **WHEN** 受授人是其他机构成员或不存在，或虽是本机构成员但角色不是 coach、或缺少该 Site 访问权
- **THEN** 前两者 MUST 返回 404，后者 MUST 返回 422 `grantee_not_eligible`，且三种情形均不写入授权记录

#### Scenario: Repeatable grant write

- **WHEN** Owner 对同一 Session 与同一 Coach 重复提交授权写入
- **THEN** 服务 MUST 返回 204，且只保留一条有效授权记录，重复写入不产生第二条有效路径

#### Scenario: Different manager cannot overwrite first grant audit
- **WHEN** Owner 在时刻 T1 授予 Session 或 Asset grant，另一 Admin 在 T2 重复 PUT
- **THEN** MUST 仍仅一条未撤销授权，granted_at/granted_by_user_id 保持 T1/Owner，期限可更新；两种资源均需持久字段断言


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

#### Scenario: Different manager cannot overwrite first revocation audit
- **WHEN** Owner 在 T1 撤销 Session 或 Asset grant，另一 Admin 在 T2 重复 DELETE
- **THEN** 两次 MUST 均返回 204，revoked_at/revoked_by_user_id 保持 T1/Owner，授权和资源历史不得丢失


## ADDED Requirements

### Requirement: Transfer operations remain initiator scoped

用户分片、恢复与 complete SHALL 要求当前 S-manage 且为原发起用户；Owner/Admin 也不能接管他人的上传。Edge SHALL 使用独立有效凭据，仅操作原发起节点且同 tenant/site 的上传，新的传输/确认/complete 还 MUST 要求来源 Device active 且仍属该节点。读取 grant MUST NOT 授予上传或完成能力，User 与 Edge token MUST NOT 互用。

#### Scenario: Manager cannot take over another upload
- **WHEN** 本机构 Admin 对其他用户或 Edge 发起的上传申请分片、确认、恢复或 complete
- **THEN** 服务 MUST 返回 404 upload_session_not_found，不签名、不传输、不从幂等记录泄露结果

#### Scenario: Read-only coach requests transfer
- **WHEN** Coach 只有 Session 或 Asset read grant 而非原发起主体且无 S-manage
- **THEN** 服务 MUST 拒绝所有传输操作，但其当前 A-read 可用于已经 ready 的授权播放/下载

#### Scenario: Identity separation and source status
- **WHEN** User token 调用 Edge 传输、Edge token 调用用户媒体接口，或来源设备已停用后请求新分片/确认/complete
- **THEN** 身份互用 MUST 为 401，设备停用 MUST 为 409 state_conflict，均不得改变历史来源或签发新写入能力

### Requirement: Current asset authorization governs access signing

播放与下载 URL 签发 SHALL 复用 M2 当前成员、Site 和 A-read 判定，不得只检查 Site 访问或另设平行 ACL。仅 ready 且精确已验证对象可用时才可签发；不存在/不可见 MUST 返回 404，可见但非 ready MUST 返回 409。Owner/Admin 保持本 Tenant 范围，Coach 需有效资源路径，Athlete 和 Edge 不新增媒体读取路径。

#### Scenario: Asset-only grant allows direct signing
- **WHEN** Coach 只有某 ready Asset 的有效 read grant 而无父 Session 读取权
- **THEN** 该 Asset 的直接播放/下载签发 MUST 成功，父 Session 详情、列表及兄弟 Asset MUST 仍返回 404

#### Scenario: Site membership alone and cross tenant access
- **WHEN** 同场馆无该 Asset 权限的 Coach、其他机构管理员、匿名或 Edge 请求播放/下载签发
- **THEN** 前两者 MUST 返回 404，身份无效者 MUST 返回 401；签发不得暴露对象位置或资源字段

#### Scenario: Non-ready or missing physical object
- **WHEN** 可见 Asset 尚非 ready，或 ready 的绑定版本无法确认存在
- **THEN** 前者 MUST 返回 409 asset_not_ready，后者 MUST 返回可诊断的 503 media_unavailable 且不返回 URL，不得改签同 key 的最新对象

### Requirement: Signed access is short lived and explicitly revocable only for new issuance

播放/下载 URL SHALL 仅授权精确已验证对象的读取，签名 TTL MUST 大于零且不超过 300 秒及用于签发的身份/授权路径剩余期限。新签发 MUST 每次重查当前权限；URL MUST 不持久保存或写入普通日志/幂等缓存。撤权后不得新签发，但不得承诺已发 URL、已下载副本或已开始传输即时失效。

#### Scenario: Revocation blocks new URLs and preserves other paths
- **WHEN** grant、Site、成员或角色被撤销/降级后再次申请 URL
- **THEN** 服务 MUST 按剩余当前合法路径判定，无路径时拒绝；既有 URL 最多在其有效期内接受新的存储请求，不能把这一窗口描述成即时撤权或传输持续时间上限

#### Scenario: URL expiry Range and download disposition
- **WHEN** 有权调用者分别申请播放与下载 URL，并发起 Range/续传或过期后新的读取请求
- **THEN** URL MUST 具明确 expires_at，播放允许合规 Range、下载使用安全 attachment 文件名；过期新请求 MUST 被拒绝，响应 MUST 使用 private/no-store 签发缓存策略且不返回永久公开路径
