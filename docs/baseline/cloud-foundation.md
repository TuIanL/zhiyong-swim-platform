# 云端账号、机构与场馆基线

登记及文档实施日期：2026-11-06。本文件是事后登记，描述既有实现；不回写此前审批日期或生产验收结论。

| 项目 | 记录 |
| --- | --- |
| 事实代码基线 | [`7082b729785957252ff5797a057f3151c6dd25c2`](https://github.com/TuIanL/zhiyong-swim-platform/commit/7082b729785957252ff5797a057f3151c6dd25c2)，2026-11-06 13:35:08 UTC |
| 对应源码树 | `b3d9d10be242ed319e931d0d8bf0b081c4f1f8c6` |
| 变更 | [formalize-cloud-foundation-baseline](../../openspec/changes/formalize-cloud-foundation-baseline/proposal.md)，纯文档，`skip_specs: true` |
| 规划提交 | `1db39527db6b2565bcdcad0230f90eb117b7ec73`；已建立proposal/design/tasks |
| 草案确认 | 用户已在本次对话确认草案无异议，并明确授权apply；不等于总体商业范围或生产部署获批 |
| 当前交付 | 独立工程的本地开发切片及正式位置文档；实现验证、最终文档验收与归档状态见[本变更记录](../verification/cloud-foundation-baseline.md) |
| Git评审 | [PR #1](https://github.com/TuIanL/zhiyong-swim-platform/pull/1)，沿用同一文档分支；未因apply自动合并 |
| 项目状态来源 | [Notion新版入口](https://www.notion.so/410f602574aa81288834cc297ae5b039)，总体任务状态不由本文单独决定 |

## 独立工程边界

- 业务源码、依赖、配置、数据库与测试位于新工程，遵守[开发约定](../../AGENTS.md)。不导入旧应用内部模块，不读取旧`.env`或沿用旧数据库。
- 当前栈为FastAPI/Pydantic/SQLAlchemy；SQLite仅用于当前本地开发和隔离测试。启动不建表、不自动迁移；开发初始化命令只允许本工程`var/`下的SQLite文件。
- 全局账号不自带机构特权；机构角色来自`TenantMembership`。场馆必须属于机构，普通成员的访问还需要显式`SiteMembership`。
- 旧算法、报告、解析器与界面只能按[历史资产取舍清单](../reference/legacy-assets.md)选择性评估后引入；不继承旧规格/任务勾选，不迁入历史视频、账号或标注数据。
- 已确认的公开姿态模型配置仍为RTMO-l Large、COCO17、官方Body7；[配置](../../configs/public_pose_baseline.json)存在不代表推理服务已经接入。

## 交付文档入口

| 文档 | 用途 |
| --- | --- |
| [数据模型与扩展边界](../architecture/cloud-domain-model.md) | 六表ERD、数据库约束、权威关系与未实现实体 |
| [RBAC契约](../contracts/cloud-rbac.md) | 角色/资源/动作矩阵、服务端检查及测试缺口 |
| [API契约](../contracts/cloud-foundation.md) | 14个path、19个HTTP操作、输入输出、错误和兼容性 |
| [本变更验证与追溯](../verification/cloud-foundation-baseline.md) | 五项主规格到代码/测试/CI的证据映射与当前验证状态 |
| [原始本地验证记录](../verification.md) | 保留首版实现时的运行结果，不倒写为本变更新测试 |

## 历史运行证据

代码基线已有22项测试通过、独立venv与wheel安装、`pip check`及本机health/ready/OpenAPI检查的记录，详见[原始验证](../verification.md)。[首版CI 42226710642](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42226710642)的`head_sha`为`7082b72`，状态completed、结论success；本次已通过GitHub连接器复查。

规划提交`1db3952`另有[PR CI 42237575940](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42237575940)通过记录，不能代替当前apply提交的验证。每个结果都绑定其提交；当前文档检查与后续CI以[本变更记录](../verification/cloud-foundation-baseline.md)及PR为准。

测试总数不表示完整权限覆盖；SQLite通过不证明PostgreSQL/RLS、并发事务或生产隔离通过。

## 未验收范围与已知限制

- 当前只有User、AuthSession、Tenant、TenantMembership、Site、SiteMembership六张业务表；Pool/Lane、设备、学员档案、训练、视频、分析、结果、报告与同步尚未实现。
- 平台管理员、所有权转移、邮件验证、密码找回、全部设备退出、审计日志、公网/分布式限流和完整权限组合尚未验收。
- 数据库没有role CHECK或“每机构恰有一个owner”的独立约束；现有owner保护在API层。没有实现RLS。
- 场馆PATCH复用创建请求：name必填，省略address/timezone会写入默认值。列表没有分页，写操作没有幂等键或并发版本控制。
- coach/athlete共享授权分支，但测试主要构造coach；管理角色的机构级场馆权限不依赖显式授权，撤销其场馆授权不能取消该权限。
- 网页应用、Edge、采集、模型推理和生产部署尚未接入或验收。后续能力应分别提案，不借本次补录顺带实现。

## 后续PostgreSQL验证的提案准入

本节是后续提案的范围与前置条件，不是新实现提案或执行授权。本次没有创建PostgreSQL change、连接数据库、执行迁移或实施RLS；也没有放开现有SQLite初始化命令的目标限制。

| 前置项 | 后续独立提案必须明确的内容 |
| --- | --- |
| 实例与身份 | 专用可销毁测试实例、数据库版本、连接配置注入方式和清理边界；不使用业务库/旧库；迁移身份与非特权应用/测试身份分开，凭据不入库 |
| 六表迁移 | 在空测试库执行现有revision，核对schema版本、字段、类型/空值、主键、唯一性、复合外键、索引和CASCADE；定义失败清理/回滚证据，不把SQLite结果外推 |
| 时间与事务 | timezone-aware写入/读取、会话过期边界、唯一冲突回滚、锁与并发事务的验证方法；明确SQLite与PostgreSQL差异 |
| 应用层租户过滤 | 用同/跨机构、多成员、多场馆和完整角色组合验证读取/写入/撤销；测试连接复用及事务结束后的上下文残留 |
| RLS策略评审 | 先决定是否引入以及保护哪些表/操作；评审tenant上下文来源、事务/连接池设置与清理、缺少上下文时的行为、表owner/BYPASSRLS等绕过路径；不能用特权测试身份证明普通应用身份隔离 |
| 交付与门槛 | 独立proposal/design/tasks、针对当前行为的规格影响判断、可复现验证、失败记录和评审入口；不借此扩展旧库迁移、完整生产部署或未来领域表 |

只有完成本change文档实施和适当验证/评审后，才应推进该独立提案。RLS策略、数据库产品决策和生产操作仍需按各自范围确认，本节不将它们写成已批准或已完成。
