# Tasks

负责人已基于批准head `334f589b66e22dc55716f5e6befb44d31e003cd1` 授权Apply；本Change的14项Apply任务均已完成。完整双后端CI已通过：head `1b3863483080e0f877147d20689a81960e71a180` 对应[CI run 42823504176](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42823504176)。最终文档提交后的head CI结果以PR #4 checks及Notion交付回链为准。仅完成Apply；Verify、Archive、主规格同步与Merge分别等待后续授权。

## 0. 本片确认

- [x] 0.1 在原Edge任务/PR保留主线与D11–D13已确认记录，并取得新的明确Apply授权后再启动；核对camera一机一车、7天/30天、30秒/90秒和未审的健康/幂等细化，确认main基线、仅隔离测试/合成数据及Propose收口不等业务开始。

## 1. 增量模型与隔离验证基础

- [x] 1.1 按F1新增4表及复合归属/唯一性/RESTRICT约束、凭据生命周期审计者字段与模型说明；验证D11仅camera、多台随车camera可归同Node、Device标识通用可扩展、无Cart表/必填cart_id，跨tenant/site父引用、成员撤销、不可变归属及同serial独立Device均符合约定，不改变六表/初始revision。
- [x] 1.2 新增递增迁移及安装资源，随迁移运行base六表/head10表反射、含基础数据往返和DDL失败回滚，补降级说明；确认camera类型/通用ID、凭据UTC到期/不可恢复撤销及最近服务端心跳观测的持久化，不新增Cart/续期服务/Runtime调度表，原六表与19操作仍可用。
- [x] 1.3 扩展PG夹具/权限为明确10表集合，测试未批准canary表无DML及DDL/TRUNCATE/版本表写/SET ROLE拒绝；确认往返后授权、容器归属/连接前拒绝/清理守卫均保留，不因D11–D13新增Cart表权限、恢复特权或schema所有权。

## 2. 管理操作与幂等事务

- [x] 2.1 实施节点/设备8个用户操作并同步文档/OpenAPI，逐端点测试角色、匿名/非成员、跨机构/错场馆、空PATCH/未知字段/枚举和拒绝无副作用；D11 camera可登记、cart/未支持kind为422、无需泳池固定位置或Cart记录，多camera仍独立；父Node须active，行政状态只由管理员路径改变。
- [x] 2.2 实施F5持久幂等、规范化及资源同事务提交，测试Node/Device重启/同键同参重放、异参409、撤权、主体/operation隔离及PG独立连接并发/失败回滚；确认不按小车/serial合并camera，不缓存或重放凭据明文、自动签发或延长旧凭据，文档保留未自动淘汰的待审取舍。

## 3. 独立凭据与停用

- [x] 3.1 实施3个凭据操作/独立Edge认证并同步说明；验证D12默认7天/最长30天、服务端UTC到期、明文成功只返一次、数据库/普通读取/日志/幂等无明文、读取无hash；保留签发/撤销者和服务端时间作为有限生命周期审计，重放不覆盖首次撤销者；明确Bearer请求头，撤销幂等但不可恢复、token互用401、同键并发一份且重试409+可见ID，无自动续期/离线无限延长/自动轮换服务。
- [x] 3.2 实施行政状态/generation及停用原子撤销，测试pending/disabled拒绝、同状态重试、旧钥永久失效、新钥人工签发与显式激活；验证撤销不能清空标记复活，心跳失败/过期不自动改行政状态。PG并发停用/签发/撤销/回滚/最新角色重验须记录锁顺序及不同pg_backend_pid。

## 4. 心跳与时间观测

- [x] 4.1 实施heartbeat、NodeRead观测及请求/响应说明；HeartbeatRead包含服务端last_seen_at/online与默认30秒发送、90秒窗口策略。验证active且不足90秒才online、恰好90秒offline；自报时间/配置/未知或过大输入不能改权威字段，失败不改行政状态，成功也不续期；不把参数写成SLA。
- [x] 4.2 用可控时钟/模拟客户端验证默认30秒节奏、抖动/有限重试、90秒前/恰好/之后、服务重启及UTC/Asia截止边界；模拟35天离线后旧钥401、last_seen/行政状态不被失败请求改写、受控新签才恢复云端认证，不新增同步/离线恢复协议或Runtime发送器。PG独立连接测心跳/停用竞态，新增场景列入必需收集守卫。

## 5. 跨模块集成与交付

- [x] 5.1 完整执行SQLite及专用PG共享/专属套件，确认D11–D13新增场景非零且无必需skip；读取两job原始结果、容器归属、cleanup removed/absent与exit0和脱敏上传，绑定测试head `1b3863483080e0f877147d20689a81960e71a180` 的[CI run 42823504176](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42823504176)：SQLite 121 passed/49 PG专属skipped；PostgreSQL shared=120、PG=49，169 passed/1 SQLite专属skipped，result=passed、cleanup=removed，兜底absent/exit0；UTC及Asia/Shanghai凭据到期场景各1项通过。
- [x] 5.2 构建/独立安装wheel，验证新模块/revision、启动不自动迁移和init-db外部目标拒绝；不依赖旧工程/源码路径/GPU/队列/对象存储。核对包内没有因一机一车或30秒节奏偷偷加入Cart控制、Runtime发送器、自动续期/轮换/离线恢复服务。
- [x] 5.3 对12操作及D11–D13的模型/请求响应/状态/错误/14项任务逐项核对，确认camera随车不等固定池位、35天限制/未来待决已记录、Edge认证请求头及有限凭据审计边界明确，既有19操作兼容且余下21个未来操作未误标实现；运行strict/链接/差异检查、更新实际证据，主规格同步留后续授权。
- [x] 5.4 在原任务、工程入口及安全/Edge设计记录同步D11–D13已确认与35天恢复未来待决、实际交付/测试/提交/CI回链；只更新本片真实范围，不改变其他P0/P1状态/负责人/日期，不重复建任务或将总体任务完成，提交后等独立Verify授权。

## Requirement / task traceability

| 规格要求 | 实施与验证任务 |
| --- | --- |
| Tenant scoped registry management | 2.1、3.1、4.1、5.1 |
| Immutable device provenance | 1.1、1.2、2.1 |
| Independent revocable edge credentials | 3.1、3.2、4.2 |
| Bounded credential lifecycle | 3.1、3.2、4.2 |
| Credential lifecycle audit boundary | 3.1 |
| Administrative node lifecycle | 3.2、4.2 |
| Bounded trustworthy heartbeat observations | 4.1、4.2 |
| Durable request idempotency | 2.2、3.1、5.1 |
| Isolated database validation | 1.3、5.1、5.2 |
| PostgreSQL schema integrity | 1.1、1.2、5.1 |

0.1是人工授权门槛；5.3/5.4为跨模块与交付证据，不能替代上述随模块提供的测试/文档。

## D11–D13对全部14项任务的对应

| 任务 | 决策对应与完成条件 |
| --- | --- |
| 0.1 | 主线/D11–D13已确认；负责人已明确基于批准head授权Apply，授权门槛已完成 |
| 1.1 | D11通用camera身份/一机一车的物理边界、无Cart前置，保留未来kind扩展 |
| 1.2 | D11通用模型、D12 UTC/撤销、D13最近观测随迁移往返保留 |
| 1.3 | 继承D11–D13范围，权限集合不因Camera/恢复/发送节奏扩大 |
| 2.1 | D11输入与多camera/未知kind验收；D13行政状态仍属管理路径 |
| 2.2 | D11独立逻辑身份，D12幂等不重放明文、不自动签发/续期 |
| 3.1 | D12完整生命周期及无自动服务；D13每次心跳仍受凭据有效期约束 |
| 3.2 | D12撤销不可恢复、受控新签；D13通信失败与行政状态分离 |
| 4.1 | D13 30秒/90秒、服务端UTC、请求响应、非SLA；D12心跳不续期 |
| 4.2 | D12 35天/时区边界与D13有限重试/窗口/竞态，模拟验收不扩张Runtime |
| 5.1 | D11–D13全部新增场景纳入双后端完整回归、收集与清理证据 |
| 5.2 | D11不带Cart实现；D12不带自动服务；D13不带Runtime发送器 |
| 5.3 | 五份规划的决策/范围/参数/限制一致，历史事实不冒充实现 |
| 5.4 | 正式决策、未来问题及本片证据回链，保护其他任务属性 |

## Workflow follow-up

- Apply按14项逐项实施并维护证据；保持PR Draft。
- 独立Verify、Archive、主规格同步和GitHub Merge按项目负责人后续授权分别推进，不把它们作为本轮已执行事项。
- 不创建第二个重叠Change；后续Session/Asset、媒体、Runtime与分析路线须单独确认后再立项。
