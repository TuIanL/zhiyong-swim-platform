# Proposal

## Why

main已提供账号/机构/场馆和隔离PostgreSQL基线，但没有可登记、撤销和观测的Edge/Device身份。负责人已正式确认本Change为下一阶段第一项业务实施主线；依据[P0/P1路线与决策补录](../../../docs/planning/2026-11-10-p0-p1-roadmap.md)，先建设Cloud Edge Registry，为后续可信采集来源和Edge云接入提供边界，避免重建Tenant/Site或提前铺开媒体/Runtime。

## What Changes

- **当前阶段仅Propose**：第一项业务主线及D11–D13已由负责人明确确认；本轮只定向修订规划/Spec Delta和PR/Notion回链。方案仍等待最终审阅与新的明确Apply授权，实施保持0/14，不继承PR #3的Apply/合并授权。
- **D11 Camera-first（已确认）**：Device.kind第一版仅camera，Device身份属于摄像头本身；按一台摄像头固定安装于一台跟拍小车、随小车移动的物理关系设计。这不是固定在泳池位置的机位；不建立Cart Device/实体或cart_id登记前置，不实现电机/运动/自动跟拍控制和安全协议。保留通用Device标识与kind扩展点，未来控制器/底盘遥测等另行扩展领域与设备协议。
- **D12 凭据生命周期（已确认）**：默认7天、最长30天，以服务端UTC判定到期；明文只在成功签发时返回一次，数据库/普通读取/日志/幂等记录无明文。撤销不可恢复，只能重新签发；不自动续期、不无限延长离线凭据，不实现离线身份恢复协议或自动密钥轮换服务。连续离线35天后的云端认证/未来同步需受控重新签发并更新凭据，恢复流程留后续评审。
- **D13 心跳（已确认）**：默认发送间隔30秒，active且距服务端last_seen_at不足90秒才online；允许网络抖动与有界重试，失败不改变Node行政状态，客户端时间不替代接收时间。90秒是判定参数，不是可用性SLA；本片只提供云端接口与模拟客户端验收，不新增Edge Runtime发送器。
- 拟增加EdgeNode、Device、EdgeCredential及最小持久化幂等记录；Node/Device复合归属、创建后归属不可变、停用保留历史，不增加四实体DELETE。
- 拟实施12个既定操作：Owner/Admin的节点/设备登记、列表/详情/修改、凭据签发/查询/撤销，以及独立Edge身份的heartbeat。软件版本/有界健康摘要和在线观测在本Change具体定义，非完整Edge运维。
- 拟保证一次性密钥只返回一次；撤销/到期/节点停用后不能调用；恢复节点需新凭据；并发/重启不丢状态。创建类写入持久幂等，不在日志/响应缓存存明文。
- 拟通过新增迁移扩展既有模型与两后端测试；保留初始六表迁移和19个操作，扩展应用测试身份的明确表集合，不放宽DDL/版本表权限，不宣称RLS。
- 不实施Pool/Lane、TrainingSession/VideoAsset/grant/UploadSession、上传/存储、Edge Runtime/小车控制、分析/模型/Web、Outbox/Inbox、生产部署或真实学员数据。
- 复用Notion[Edge Node原任务](https://www.notion.so/410f602574aa81e9bfa5cb7ca947e7f7)，直接提供[数据模型](https://www.notion.so/410f602574aa811bbad3c6e452a065b6)、[架构/API](https://www.notion.so/410f602574aa816582ccc14817ce4601)和[RBAC](https://www.notion.so/410f602574aa816e87dcd70f56c4100e)的本片证据，不将总体任务标完成或创建重复任务。

## Capabilities

### New Capabilities

- cloud-edge-registry：同机构/场馆的节点和设备登记、独立可撤销凭据、可信心跳观测、持久化幂等与来源保留。

### Modified Capabilities

- cloud-identity：修改Isolated database validation、PostgreSQL schema integrity两项，把固定六表授权/验证扩为“保留六表基线+本Change明确新增表”的集合；保留容器实际归属、应用最小权限、清理非零传播等全部原保证。其余8项要求与Purpose不变；本轮仅写增量，不同步主规格。

## Impact

- 事实基线main@d7f1eed；输入为[ADR0003](../../../docs/decisions/0003-capture-media-domain-contracts.md)、[领域模型](../../../docs/architecture/cloud-capture-media-domain.md)与[API草案](../../../docs/contracts/cloud-capture-media.md)，不把它们当已实现。
- 将来Apply触及services/cloud的模型/新增迁移、认证/路由/输入输出、安装与两后端测试、API/领域文档及OpenAPI快照；复用当前测试编排，不连旧库/生产库，不新增队列、GPU或对象存储依赖。
- 现有六表、注册/机构/场馆API保持兼容；新增表的RESTRICT和权限集合须在迁移/回归中显式验证，不改写初始revision，不用关闭旧断言换取通过。
- 已确认参数与边界见D11–D13；有界健康字段、幂等记录不自动淘汰等其他实施细化仍待最终审阅，不因本轮确认自动视为批准。长期离线恢复见Design的Future Considerations / Known Limitations。本轮不改主规格或实现；Apply、Verify、Archive和本PR Merge各等后续授权。
