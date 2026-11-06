# 云端基础契约 v0.1

实现状态：本地开发切片，待项目负责人验收；不是商业平台总体设计的最终冻结。

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

## 接口

| 方法 | 路径 | 行为 |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | 创建普通账号，201 |
| POST | `/api/v1/auth/login` | 返回会话 |
| POST | `/api/v1/auth/logout` | 撤销当前会话，204 |
| GET | `/api/v1/me` | 当前账号 |
| POST / GET | `/api/v1/tenants` | 创建/查询所属机构 |
| GET | `/api/v1/tenants/{tenant_id}` | 机构详情 |
| POST / GET | `/api/v1/tenants/{tenant_id}/members` | 增加/查询成员 |
| PATCH / DELETE | `/api/v1/tenants/{tenant_id}/members/{user_id}` | 调整角色/移除成员 |
| POST / GET | `/api/v1/tenants/{tenant_id}/sites` | 创建/查询授权场馆 |
| GET / PATCH | `/api/v1/tenants/{tenant_id}/sites/{site_id}` | 查询/修改场馆 |
| POST | `/api/v1/tenants/{tenant_id}/sites/{site_id}/members` | 授权已有机构成员 |
| DELETE | `/api/v1/tenants/{tenant_id}/sites/{site_id}/members/{user_id}` | 撤销场馆授权 |

健康接口 `/health` 仅表示应用运行；`/ready` 检查数据库迁移表存在，不代表完整业务/部署验收。完整 schema 可由运行服务的 `/openapi.json` 获取。
