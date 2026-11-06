# 云端基础API契约 v0.1

登记日期：2026-11-06；事实代码基线：`7082b729785957252ff5797a057f3151c6dd25c2`。本文件发布于 `formalize-cloud-foundation-baseline` apply；实现仍为本地开发切片，未完成生产验收，不是商业平台总体设计的最终冻结。

完整授权矩阵见[RBAC契约](cloud-rbac.md)，六表归属见[领域模型](../architecture/cloud-domain-model.md)，本次验证与历史结果见[追溯记录](../verification/cloud-foundation-baseline.md)。

## 身份与会话

公开注册只接受 email、password、display_name；未知字段拒绝。邮箱规范化为小写；密码至少12字符，保留空格。账号不拥有全局管理员角色。机构角色绑定机构成员关系，用户可属于多个机构。

登录成功返回随机会话 token；数据库保存 SHA-256 摘要、用户与有效期。服务端逐次检查会话及账号状态，退出立即撤销当前会话。5次失败会锁定账号15分钟；公网入口整体限流、未知账号的分布式防滥用、邮箱验证及找回密码未实现。

密码使用 scrypt N=2^15,r=8,p=3、独立16字节盐。参数来源：[OWASP Password Storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html#scrypt)。该实现不构成部署环境已完成安全验收的结论。

## 当前权限

| 操作 | owner | admin | coach / athlete |
| --- | --- | --- | --- |
| 查询所属机构 | 本机构 | 本机构 | 本机构 |
| 查询成员 | 允许 | 允许 | 拒绝 |
| 增加/移除机构成员、调整普通角色 | 允许 | 拒绝 | 拒绝 |
| 创建/修改场馆 | 允许 | 允许 | 拒绝 |
| 查询场馆 | 本机构全部 | 本机构全部 | 仅显式授权的场馆 |
| 授予/撤销场馆权限 | 允许 | 允许 | 拒绝 |
| 移除或降级 owner | 首版不支持 | 拒绝 | 拒绝 |

创建机构时，当前已登录用户仅成为新机构 owner。此能力不授予其他机构权限，也不产生平台管理员。场馆所属机构不可从修改请求改变。场馆成员必须先是同机构成员；复合外键约束 site/tenant 与 member/tenant 的一致性。

非成员访问机构返回404；机构内权限不足返回403；非授权场馆返回404。仅允许访问身份能查询到的资源，不以客户端 tenant_id 字段作为授权依据。

## 19个HTTP操作

依据[OpenAPI快照](openapi.json)、[路由](../../services/cloud/src/swimplatform/api.py)、[应用入口](../../services/cloud/src/swimplatform/main.py)及[请求/响应schema](../../services/cloud/src/swimplatform/schemas.py)交叉核对：14个path、19个operation，其中业务17、健康2。业务路径参数tenant_id/site_id/user_id均按UUID校验；除注册、登录及两个健康接口外，均要求有效Bearer会话。

| 方法与路径 |权限/输入 | 成功响应 |
| --- | --- | --- |
| POST /api/v1/auth/register | 公开；Registration(email,password,display_name) | 201 UserRead(id,email,display_name) |
| POST /api/v1/auth/login | 公开；Credentials(email,password) | 200 SessionRead(access_token,token_type,expires_at,user) |
| GET /api/v1/me | 有效活跃账号会话 | 200 UserRead |
| POST /api/v1/auth/logout | 当前有效会话 | 204，无body；撤销当前会话 |
| POST /api/v1/tenants | 登录；TenantCreate(name,slug) | 201 TenantRead(id,name,slug,role=owner) |
| GET /api/v1/tenants | 登录；按当前user成员关系过滤 | 200 TenantRead数组 |
| GET /api/v1/tenants/{tenant_id} | 本机构成员 | 200 TenantRead |
| GET /api/v1/tenants/{tenant_id}/members | owner/admin | 200 MemberRead(user_id,display_name,role)数组 |
| POST /api/v1/tenants/{tenant_id}/members | owner；MemberCreate(user_id,role)，目标为已存在活跃账号 | 201 MemberRead |
| PATCH /api/v1/tenants/{tenant_id}/members/{user_id} | owner；MemberRole(role)，不接受owner | 200 MemberRead；禁止改owner |
| DELETE /api/v1/tenants/{tenant_id}/members/{user_id} | owner；禁止删owner | 204，无body；清理成员下的场馆授权 |
| POST /api/v1/tenants/{tenant_id}/sites | owner/admin；SiteCreate | 201 SiteRead(id,tenant_id,name,address,timezone) |
| GET /api/v1/tenants/{tenant_id}/sites | 本机构成员；非管理角色按授权过滤 | 200 SiteRead数组 |
| GET /api/v1/tenants/{tenant_id}/sites/{site_id} | tenant/site一致且具访问权 | 200 SiteRead |
| PATCH /api/v1/tenants/{tenant_id}/sites/{site_id} | owner/admin；SiteCreate | 200 SiteRead |
| POST /api/v1/tenants/{tenant_id}/sites/{site_id}/members | owner/admin；SiteGrant(user_id)，目标必须已有同机构成员关系 | 201 {user_id,site_id} |
| DELETE /api/v1/tenants/{tenant_id}/sites/{site_id}/members/{user_id} | owner/admin | 204，无body；不存在授权时也成功 |
| GET /health | 公开，不检查DB | 200 应用status/service/version |
| GET /ready | 公开，检查迁移表可查询 | 200 {status:ready}；不可查询503 |

## 请求字段

所有请求对象拒绝额外字段。下表字段来自同一提交的OpenAPI；自定义email/姓名/时区校验与密码空格规则以上文及schema源码为准。

| Schema | 字段 | 类型 | 必填 | 限制与默认值 |
| --- | --- | --- | --- | --- |
| Registration | email | string | 是 | minLength=3; maxLength=255 |
| Registration | password | string | 是 | minLength=12; maxLength=128 |
| Registration | display_name | string | 是 | minLength=1; maxLength=80 |
| Credentials | email | string | 是 | minLength=3; maxLength=255 |
| Credentials | password | string | 是 | minLength=12; maxLength=128 |
| TenantCreate | name | string | 是 | minLength=1; maxLength=120 |
| TenantCreate | slug | string | 是 | minLength=2; maxLength=64; pattern="^[a-z0-9][a-z0-9-]*[a-z0-9]$" |
| MemberCreate | user_id | uuid | 是 | 无额外声明 |
| MemberCreate | role | string | 是 | enum=["admin", "coach", "athlete"] |
| MemberRole | role | string | 是 | enum=["admin", "coach", "athlete"] |
| SiteCreate | name | string | 是 | minLength=1; maxLength=120 |
| SiteCreate | address | string | 否 | maxLength=300; default="" |
| SiteCreate | timezone | string | 否 | maxLength=64; default="Asia/Shanghai" |
| SiteGrant | user_id | uuid | 是 | 无额外声明 |

## 响应字段

| Schema | 当前字段 |
| --- | --- |
| UserRead | id, email, display_name |
| SessionRead | access_token, token_type, expires_at, user |
| TenantRead | id, name, slug, role |
| MemberRead | user_id, display_name, role |
| SiteRead | id, tenant_id, name, address, timezone |

SessionRead.user是UserRead，expires_at为date-time字符串，token_type默认bearer。列表成功响应是对应Read对象数组，未分页；注册/当前账号不返回密码摘要、账号锁定信息或会话摘要。场馆授权成功返回user_id/site_id对象，没有独立Read模型；health/ready也未声明专用响应模型，表中字段依据源码实际返回值，不伪造OpenAPI类型保证。204响应无body。

## 错误、输入与健康检查

自定义业务错误采用HTTPException的JSON结构：`{"detail":{"code":"...","message":"..."}}`，没有全局统一错误envelope。

| HTTP状态 | 当前业务code/结构 | 主要触发条件 |
| --- | --- | --- |
| 401 | unauthorized / invalid_credentials | 身份缺失或失效；登录失败、账号停用或锁定 |
| 403 | forbidden | 已是机构成员但角色不满足操作 |
| 404 | tenant_not_found / site_not_found / user_not_found | 无机构成员关系；场馆归属不符或无授权；新增成员的目标账号不存在/停用 |
| 409 | account_conflict / tenant_conflict / member_conflict / site_conflict / grant_conflict | email/slug/成员/同机构场馆名/授权冲突 |
| 409 | owner_transfer_required | 首版禁止降级或移除owner |
| 422 | 框架RequestValidationError结构，detail为错误数组 | UUID、必填/额外字段、role枚举、长度、slug、email或时区校验失败 |
| 503 | `{"status":"not_ready"}` | ready检查数据库迁移表查询失败，不使用detail对象 |

错误code目录依据当前路由，框架422与业务detail对象不同；未做统一转换。本文件不保证多个失败条件同时存在时的固定错误优先级，也不把“OpenAPI声明422”当作所有业务错误都已完整列入OpenAPI。密码12–128字符并保留空格；email规范化小写，自定义格式校验不代表邮箱归属已验证。其他Input字符串按现有配置去除首尾空格，姓名由Registration单独清理。

`/health`不访问数据库，只返回应用status/service/version；`/ready`执行对alembic_version表的查询，失败为503、成功为ready。它没有校验revision是否等于当前head，也没有逐表验证所有业务能力，不能当作完整迁移或生产就绪验收。

## 场馆PATCH与版本兼容性

场馆PATCH当前复用SiteCreate，不是任意字段的局部更新：name仍必填；调用payload.model_dump()后逐字段写入，省略address/timezone会写入空字符串和Asia/Shanghai。示例请求 `{"name":"新馆名"}` 会同时恢复这两个默认值；不能对调用方承诺只改name。请求不能改变tenant_id，额外字段会被拒绝。

业务路径前缀为`/api/v1`，应用/OpenAPI版本为`0.1.0`。这些标识不意味着已有兼容性迁移机制：当前没有分页、幂等键、业务revision/ETag或并发版本控制；重复授权返回409，撤销不存在的显式场馆授权仍返回204。没有开放机构/场馆/账号删除或所有权转移API。

后续如果调整PATCH为partial update、统一错误格式、加入分页/幂等、数据库CHECK或新增角色，需要另开行为变更并维护OpenSpec、契约与相应测试。本次只记录现状，不修改业务源码、OpenAPI快照或响应行为。
