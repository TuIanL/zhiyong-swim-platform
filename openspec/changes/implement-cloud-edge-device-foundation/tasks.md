# Tasks

当前仅Propose，**0/14**。以下任务是收到新的明确Apply授权之后的实施清单；本轮路线审计、写提案和Draft PR不计作这些任务完成。参数已经在design给出候选选择，需负责人审阅同意后实施，不把PR3批准当作本Change授权。

## 0. 本片确认

- [ ] 0.1 在Notion原Edge任务/PR中保存负责人对本片路线、12操作、7天/30天凭据、90秒在线窗口、有界健康和持久幂等取舍的审阅及本次明确Apply授权；核对main与规划是否移动，确认只使用隔离测试/合成数据，不等待所有P0完成。

## 1. 增量模型与隔离验证基础

- [ ] 1.1 按F1新增4表及复合归属/唯一性/RESTRICT约束、模型字段说明；验证跨tenant/site父引用、成员移除不被新FK阻塞、不可变归属和同serial独立Device，不改变原六表模型/初始revision语义。
- [ ] 1.2 新增递增迁移及安装资源，随迁移提供并运行base六表快照/head10表反射、含基础数据往返、受控DDL失败回滚测试，补迁移/降级说明；验证原六表数据与注册/机构/场馆仍可用，不在外部库运行。
- [ ] 1.3 扩展PG夹具/权限为明确10表集合，增加未批准canary表无DML及现有DDL/TRUNCATE/版本表写/SET ROLE拒绝测试；确认roundtrip后重新授权、实际容器归属/连接前拒绝与清理守卫保留，文档说明应用身份不获schema所有权。

## 2. 管理操作与幂等事务

- [ ] 2.1 实施节点/设备8个用户操作（F2中不含3个凭据与heartbeat），同时更新API字段/错误/权限文档及OpenAPI对应部分，逐端点测试Owner/Admin、Coach/Athlete、匿名/非成员、跨机构/错场馆、未知/空PATCH/状态枚举和拒绝写入无副作用；Device创建/重新启用仅对active父节点。
- [ ] 2.2 实施F5持久幂等、参数规范化及资源同事务提交；随代码提供Node/Device同键同参顺序与重启重放、异参409、撤权重放拒绝、不同主体/operation隔离及PG独立物理连接并发/提交失败回滚测试；文档写清无自动淘汰和不保存完整请求/明文。

## 3. 独立凭据与停用

- [ ] 3.1 实施3个凭据操作和独立Edge认证，更新相应API/密钥保管说明；验证只签发响应一次含secret、普通读取/日志/幂等无secret/hash、7天默认/30天上限、撤销幂等、User/Edge token互用401、凭据同键并发只一份且重试409+可见ID。
- [ ] 3.2 实施行政Node状态、generation及停用原子撤销/新凭据恢复规则；提供pending/disabled拒绝、同状态重试、旧key永久失效、disabled可先签新key但不能heartbeat、PG并发停用/签发/撤销/提交失败与最新角色重验测试；记录实际锁顺序与两个不同pg_backend_pid，不用单连接等待冒充并发。

## 4. 心跳与时间观测

- [ ] 4.1 实施heartbeat、NodeRead在线/版本健康摘要及有界输入，补请求/响应/90秒边界说明；测试本节点更新、客户端时间/高自报revision不能改desired版本/身份/行政status、未知/过大输入422且不更新last_seen、从未心跳及90秒恰好offline。
- [ ] 4.2 增加并实跑共享重启持久性、凭据UTC/Asia/Shanghai截止前/恰好/之后及连接复用测试；PG独立连接验证heartbeat/停用竞态，严格按事务先后判定。将这些用例加入对应专属/共享必需收集守卫，不因PG环境缺失跳过或回退SQLite。

## 5. 跨模块集成与交付

- [ ] 5.1 完整执行默认SQLite及专用PG共享/专属套件，确认新场景非零且无必需skip；读CI两job原始结果、实际容器归属、cleanup removed/absent及exit0、脱敏证据上传，结果绑定最新head，不把旧112/150或只跑新增用例当本片全量通过。
- [ ] 5.2 构建/独立安装wheel，验证新模块/新revision可用，已安装应用正常启动且不自动迁移、init-db外部路径拒绝继续成立；验证不依赖旧工程、源码路径或新增GPU/队列/对象存储服务。
- [ ] 5.3 对本片实际12操作集合、字段/状态/错误/规范逐项集成核对，确认既有19操作兼容且剩余21个PR3未来操作未被误标已实现；运行change/main strict、本地链接和Git差异检查，更新实际测试结果与限制，主规格同步留后续授权阶段。
- [ ] 5.4 在原Notion任务和同一PR发布实际交付/测试/提交/CI回链及任务完成证据，只更新本片真实范围；总体领域/RBAC/架构任务不自动完成，提交后等待独立Verify授权。

## Requirement / task traceability

| 规格要求 | 实施与验证任务 |
| --- | --- |
| Tenant scoped registry management | 2.1、3.1、4.1、5.1 |
| Immutable device provenance | 1.1、1.2、2.1 |
| Independent revocable edge credentials | 3.1、3.2、4.2 |
| Administrative node lifecycle | 3.2、4.2 |
| Bounded trustworthy heartbeat observations | 4.1、4.2 |
| Durable request idempotency | 2.2、3.1、5.1 |
| Isolated database validation | 1.3、5.1、5.2 |
| PostgreSQL schema integrity | 1.1、1.2、5.1 |

0.1是人工授权门槛；5.3/5.4为跨模块与交付证据，不能替代上述随模块提供的测试/文档。

## Workflow follow-up

- 本轮只发布Propose与路线审计，保持Draft；14项均不勾选。
- 明确Apply后才实施；独立Verify、Archive、主规格同步和GitHub Merge按项目负责人后续授权分别推进，不将它们写成提前可完成的实施任务。
- 不创建第二个重叠Change；后续Session/Asset、媒体、Runtime与分析路线须单独确认后再立项。
