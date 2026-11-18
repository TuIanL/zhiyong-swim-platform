# Design

**M4.1 · 负责人签认记录 · 纯文档 Apply**

## Context

### 基线与取证

- GitHub PR #6 于 2026-11-18 10:02:22（北京时间）合并。GitHub `main` 与本次 fetch 后的 `origin/main` 均为 `94fed6b03d50ccca52f6ec959bcde1636148c65c`，两父提交为此前 main `3352c6b` 和最终 PR head `6dcedf8`。工作分支从完整 merge SHA 建立。[PR #6](https://github.com/TuIanL/zhiyong-swim-platform/pull/6) · [Merge commit](https://github.com/TuIanL/zhiyong-swim-platform/commit/94fed6b03d50ccca52f6ec959bcde1636148c65c)
- 合并后 main Push CI Run `44220297894` 的三个 Job 全部成功。原始日志的 checkout SHA 和两份 artifacts 元数据均与合并 SHA 一致。SQLite **210 passed / 92 skipped**，PG17 **281 passed / 21 skipped**，PG 专用实例清理为 `removed`。隔离 RustFS 使用 **ffprobe 6.1.1**，验收和精确清理成功。此结果更新了 Notion 新版入口中 RustFS 仍在运行的时间截面。[main CI](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894) · [PG 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14389754072) · [RustFS 证据](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/44220297894/artifacts/14390244558)
- 基线含 144 个受跟踪路径。服务树只有 `services/cloud`，包括一个 Python 3.13/FastAPI 包、SQLAlchemy/Alembic、SQLite/PG17/RustFS 测试和合成 MP4。真正的迁移位于包内，`services/cloud/migrations` 是兼容符号链接，版本为 0001–0004。其余目录为 `.github` CI、`configs`、`scripts`、`docs`、`openspec` 和 `var/.gitkeep`。模型 **19 表**，OpenAPI 快照 **43 paths / 57 operations**（含健康/就绪）。Pose 配置仅记录默认选型。[目录树](https://github.com/TuIanL/zhiyong-swim-platform/tree/94fed6b03d50ccca52f6ec959bcde1636148c65c) · [应用入口](../../../services/cloud/src/swimplatform/main.py) · [模型](../../../services/cloud/src/swimplatform/models.py) · [OpenAPI](../../../docs/contracts/openapi.json)
- 规划前活动 Change 为 0。主规格有 `cloud-identity`、`cloud-edge-registry`、`cloud-training-session`、`cloud-media-asset`、`cloud-media-authorization`、`cloud-media-transfer` 共 6 份。M1/M2/M3 分别对应 PR #4/#5/#6 的 Registry、Session/Asset、Media Transfer 实施归档。此前 PR #3 的领域契约已约定 D4/D10，允许 Edge 保存临时本地记录，正式 Session 的接纳、ID 映射和冲突规则由后续 Change 界定。[主规格](../../specs/) · [M1 归档](../archive/2026-11-11-implement-cloud-edge-device-foundation/) · [M2 归档](../archive/2026-11-14-implement-cloud-session-asset-foundation/) · [M3 归档](../archive/2026-11-16-implement-cloud-media-upload-transfer/) · [ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md)
- Notion 项目明确本地优先和统一云端权威。同步 P1 要事务队列、ACK、去重、退避及冲突记录，验收看断网不丢失、重复投递无重复记录及恢复后收敛。部署包 P1 要可重复安装、健康检查、重启及无公网可用，目标 GPU 工作站验证另由负责人安排。07 是草案，内含指令版本、有效期、签名或校验线索。v1 签认范围为单一合成任务类型，Q4 决定以有效身份的 HTTPS/TLS 拉取与版本校验下发。[项目](https://app.notion.com/p/410f602574aa816ea4a6f2b06985d412) · [同步 P1](https://app.notion.com/p/410f602574aa8181a19ae87e25b62b4d) · [Edge 部署包 P1](https://app.notion.com/p/410f602574aa81608463d9de3e26368a) · [07 协议](https://app.notion.com/p/410f602574aa81cda7bff8c3ed483f4d) · [04 Runtime 设计](https://app.notion.com/p/410f602574aa8142a2ecde4eb3a6872a) · [新版工程入口](https://app.notion.com/p/410f602574aa81288834cc297ae5b039)

### 已批准边界、待决设计与实施状态

| 状态 | 内容与凭据 |
| --- | --- |
| 已批准的既有边界 | 本地优先，已业务接单的任务可离线继续，原片默认留场馆，获准传输沿用 M3。Session 最终状态及离线临时记录继承 ADR 0003 D4/D10。D12 的服务端 UTC、7 天默认/30 天上限、撤销不可恢复、受控签发及禁止自动续期已批准。[ADR 0003](../../../docs/decisions/0003-capture-media-domain-contracts.md) · [Notion 决策记录](https://app.notion.com/p/410f602574aa81618d05efd317151022) · [Registry 主规格](../../specs/cloud-edge-registry/spec.md) |
| 本轮明确的交付边界 | M4.1 为纯文档契约，沿用 `skip_specs: true`。候选需求、样例和矩阵随 Change 留存。后续 M4.2/M4.3 分别起草并审查行为 Delta。[纯文档先例](../archive/2026-11-10-define-cloud-capture-media-contracts/proposal.md) |
| 已批准的 M4 v1 设计方向 | Q1=A、Q2=A、Q3=A、Q4=A、Q5=B、Q6=A、Q7=A。实施参数和外部政策的待决边界见签认表。 |
| 实施满足 | 文档签认和 OpenSpec strict 证明可评审与结构正确。M4.2/M4.3 各自凭实现和对应的测试证据判断所负责条款是否满足，双向同步的系统行为由 M4.4 验收。 |

### 现有能力和缺口

| 基线 | 可复用基础 | M4 缺口 |
| --- | --- | --- |
| Cloud Identity / M1 Registry | User/AuthSession、Tenant/Site 和成员授权。Node、Camera Device 的固定归属与复合外键。Owner/Admin 签发和撤销独立 Edge 凭据，服务端 7 天默认/30 天上限。Heartbeat 只记录观察值，默认 30 秒、在线窗口 90 秒 | Edge 本地服务、数据目录与本地数据库、启动/恢复器、运行时同步客户端、受控凭据装载及本地访问身份。心跳在线状态只供观测 |
| M2 TrainingSession、Asset、授权 | Session 由用户创建，持久记录创建者和 Cloud 状态 `planned → recording → completed` 或合法取消。读权限按现有角色/资源 grant 派生。当前 Edge 可为同场馆已有 Session、所属 Camera 创建上传意图 | TrainingTask / 分配 / 指令版本、Edge 领任务及执行回报、临时 Session 接纳映射、纯采集元数据的云端投影。Session 无 node 归属或同步 revision。当前 Edge 上传路径的同场馆校验不能代替 M4 的分配校验 |
| M3 Media Transfer | UploadSession 与 VideoAsset 受控创建，支持分片签名、确认、续传、异步完成、整对象 SHA-256/大小/媒体探测、`ready` 事务以及授权播放/下载。MediaJob/CleanupCandidate 是媒体专用持久工作 | 通用业务 Outbox/Inbox、节点下发日志、游标、ACK、对账。缺本地分析执行器、AnalysisTask / AnalysisResult / Report 模型和服务身份的结果/发布入口。媒体 worker 的完成只表示媒体处理 |
| 开发及交付 | 已有 SQLite 快速验证、专用 PG17 双后端事务/约束校验，以及真实隔离 RustFS 媒体套件 | 实际 Cloud 与 Edge 进程经网络通信、独立持久卷及断网/重启/失 ACK 故障注入；场馆部署验证单独验收 |

代码入口见 [Edge Registry](../../../services/cloud/src/swimplatform/edge_registry.py) · [Session/Asset API](../../../services/cloud/src/swimplatform/media.py) · [媒体访问](../../../services/cloud/src/swimplatform/media_access.py) · [媒体传输](../../../services/cloud/src/swimplatform/media_transfer.py) · [迁移](../../../services/cloud/src/swimplatform/migrations/versions/) · [CI](../../../.github/workflows/ci.yml)。

## Goals / Non-Goals

签认契约描述一条可复核的闭环。Cloud 为已有 Session 分配一个 TrainingTask 给一个 Node，Edge 持久接收命令并业务接单后可离线记录合成采集事实和执行终态，重连后更新 Cloud 的独立任务视图。M4.1 交付仅为可评审、可逐场景走读的契约。真实摄像头、算法执行、分析结果摄取、报告发布、权限/配置/模型分发、离线自建 Session 的正式接纳、节点转移及生产选型均留给对应领域 Change。

## Decisions

| 设计 | 生效的文档位置 |
| --- | --- |
| D1 数据权威与 Q5 B 数据流 | [架构](../../../docs/architecture/cloud-edge-sync-v1.md#authority) |
| D2 v1 信封、流与负载 | [API 契约](../../../docs/contracts/cloud-edge-sync-v1.md#event-envelope) |
| D3 事务与四个 ACK/执行边界 | [API 契约](../../../docs/contracts/cloud-edge-sync-v1.md#delivery) |
| D4 任务控制、终态与父 Session | [控制 API](../../../docs/contracts/cloud-edge-sync-v1.md#cloud-control) · [PG17 锁依赖与竞态](../../../docs/architecture/cloud-edge-sync-v1.md#postgresql-races) |
| D5 凭据与安全停止 | [架构](../../../docs/architecture/cloud-edge-sync-v1.md#offline-safety) |
| D6 分段交接及验收 | [架构](../../../docs/architecture/cloud-edge-sync-v1.md#handoff) |
| Q6 技术参数 | [已签认的隔离开发与测试参数](../../../docs/architecture/cloud-edge-sync-v1.md#timing-register) |

## Q1–Q7 负责人签认

<a name="decision-signoff"></a>

记录日期 **2026-11-18（Asia/Shanghai）**。批准来源为本次负责人明确授权纯文档 Apply 的请求。签认对应 [二轮评审 Head](https://github.com/TuIanL/zhiyong-swim-platform/commit/a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b) 及 [Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7)。业务选择统一为 **Q1=A、Q2=A、Q3=A、Q4=A、Q5=B、Q6=A、Q7=A**。

| 决策 | 原 A / B 候选 | 已批准 v1 选择 | 对 DB、API、Edge 和验收的影响 | 仍待确认 |
| --- | --- | --- | --- | --- |
| Q1 | A 全生命周期唯一，仅 Owner/Admin；B 仅活动任务唯一，扩展控制权限需另审 | **A**。一个 Session 最多一个 Task、Task 最多一次 Assignment，固定一个 Node，终态占位，首跑 `capture_demo` | M4.3 同事务创建任务、分配、命令和收据。唯一约束、权限、幂等和重复取消按 D4 / T1–T9 / L2 | 多任务、多次分析和重派后续另议 |
| Q2 | A 父取消联动、合法先提交终态；B 显式任务取消、父取消单独协调 | **A**。Cloud 控制，Edge 报事实。迟到合规事实与冲突收据留存，完成历史保留，离线临时 Session 留本地 | M4.2 取消消费，M4.3 Cloud 投影和父事务，M4.4 竞态，保持 M3 终态与 ready 兼容 | 临时 Session 正式接纳及 ID 映射另议 |
| Q3 | A 仅撤钥继续本地运行，可信停用/停机触发安全挂起；B 撤钥亦挂起或另增管理通道 | **A**。断网/自然过期/仅撤钥时已接单任务继续。经验证的停用或本地停机持久挂起，保留事实和检查点。D12 继续适用 | M4.2 安全停止、解挂及重启，M4.3 现行凭据重验和 Registry 恢复，C1–C4/L4 | 可信通知、现场核验、凭据交付与解挂实现；完全离线无法保证及时收到远端停用 |
| Q4 | A HTTPS/TLS 拉取 + 固定水位；B 独立签名和未接单硬截止 | **A**。有效认证、连号、版本及载荷校验，无逐命令签名或独立任务硬截止 | M4.2/M4.3 区分持久接收、Command ACK、业务接单、实际执行。A1/A2，尚未送达取消不视为 Edge 已停止 | 各实现的调度及事务细节按 D3、Q6 验证 |
| Q5 | A 首版只验元数据，上传另行获准；B 在明确人工批准后纳入媒体验证 | **B**。M4.4 必验经过人工批准的合成 MP4 上传。原片默认本地，事件、执行终态及收据均不触发上传 | 现有 M3 权限、UploadSession、分片、续传及整对象验证，M1–M6 验收，无 M4 媒体授权扩展 | 真实审批人/记录产品规则、真实个人信息和监护人授权、生产存储/区域/访问控制、保留、备份、删除、撤回、审计 |
| Q6 | A 限额、持久化与人工恢复；B 改分页预算或带快照裁剪 | **A**。8 KiB/事件、50 条/页、双向连续序号、带抖动有界指数退避、原信封保留、`recovery_required`、独立文件库和 PG17 | M4.2 重试/不丢事实，M4.3 服务端限额与对账，M4.4 故障注入。问题分配不阻断其它上行分配 | 负责人已补充签认隔离环境 P01–P10，生产默认值另审 |
| Q7 | A 按当前设备状态和授权，停用转冲突；B 按可信历史采集授权版本接纳 | **A**。同作用域停用设备仅在当前授权和因果合法时可记录冲突并消费序号，自报时间不能证明采集时授权 | M4.3 接纳及最小审计，越 Tenant/Site/Node 或无效凭据仍拒绝，验收 S1.1 及 D2 样例 | 可证明的历史授权版本另审 |

2026-11-18（Asia/Shanghai），负责人基于 [6/7 交付 Head](https://github.com/TuIanL/zhiyong-swim-platform/commit/ff5d82c1b4c85e7b438cb125b581a52784cc3f6a) 确认采用 P01–P10 原建议值，适用范围仅为隔离开发与测试。详见 [ADR 0004](../../../docs/decisions/0004-cloud-edge-sync-v1.md) 与 [参数登记表](../../../docs/architecture/cloud-edge-sync-v1.md#timing-register)。

[行为契约与样例](../../../docs/contracts/cloud-edge-sync-v1.md) · [验收矩阵](tasks.md#acceptance-matrix)
