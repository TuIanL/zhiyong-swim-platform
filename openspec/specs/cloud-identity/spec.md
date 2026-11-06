# cloud-identity Specification

## Purpose
为新版游泳智能视频分析平台提供可独立运行和验证的账号、机构成员与场馆授权基础。所有资源访问必须经过服务端身份及机构归属检查，避免继承旧原型的公开媒体、任意角色和资源标识授权缺口。

## Requirements

### Requirement: Ordinary account registration
公开注册 SHALL 仅创建无机构特权的账号，拒绝用户自报的角色、机构归属与激活状态字段。

#### Scenario: Privileged registration input
- **WHEN** 公开注册请求包含 role=admin 或 tenant_id
- **THEN** 服务 MUST 拒绝请求且不创建特权账号

### Requirement: Revocable sessions
身份认证 SHALL 检查会话有效期、撤销状态与账号激活状态；数据库 MUST 不保存原始 bearer token。

#### Scenario: Logout revokes current session
- **WHEN** 用户退出当前会话后继续使用该 token
- **THEN** 服务 MUST 返回401

### Requirement: Tenant resource isolation
机构列表与详情 SHALL 仅返回当前用户拥有成员关系的机构，其他机构资源不可通过猜测ID访问。

#### Scenario: Another tenant identifier
- **WHEN** 用户请求不属于其授权范围的机构或场馆
- **THEN** 服务 MUST 拒绝访问且不返回资源内容

### Requirement: Explicit site scope
非管理角色 SHALL 仅能访问显式授权的场馆；场馆授权 MUST 同时满足用户与场馆属于同一机构。

#### Scenario: Removed institution member
- **WHEN** 所有者移除某机构成员
- **THEN** 其场馆授权 MUST 失效且不能继续访问该机构资源

### Requirement: Isolated database validation
测试 SHALL 使用专用临时数据库执行新版迁移，应用启动 MUST 不自动迁移旧数据库或外部数据库。

#### Scenario: Initialization points to external database
- **WHEN** 本地开发初始化命令的目标不是新版 var 目录内的SQLite文件
- **THEN** 命令 MUST 拒绝运行且不连接或迁移该目标
