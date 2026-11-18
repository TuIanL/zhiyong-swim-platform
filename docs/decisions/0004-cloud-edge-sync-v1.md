# ADR 0004｜M4 v1 云边可靠同步契约

**批准状态为 v1 业务方向已签认，技术参数和生产前置按下列范围待审。**

- 记录日期为 2026-11-18（Asia/Shanghai）。签认来源为本次负责人的明确 Q1–Q7 决策及 M4.1 纯文档 Apply 授权。
- 签认基于 [二轮 Propose Head `a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b`](https://github.com/TuIanL/zhiyong-swim-platform/commit/a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b) 和 [M3 合并基线 `94fed6b03d50ccca52f6ec959bcde1636148c65c`](https://github.com/TuIanL/zhiyong-swim-platform/commit/94fed6b03d50ccca52f6ec959bcde1636148c65c)。[签认提交 `ef17d966a46d99da03e5c2ab68e3b2d401268c37`](https://github.com/TuIanL/zhiyong-swim-platform/commit/ef17d966a46d99da03e5c2ab68e3b2d401268c37) · [Draft PR #7](https://github.com/TuIanL/zhiyong-swim-platform/pull/7)
- M4.1 为 `skip_specs: true` 的文档 Change。[架构](../architecture/cloud-edge-sync-v1.md) 定义数据权威、事务、锁序和交接。[API 契约](../contracts/cloud-edge-sync-v1.md) 定义协议、样例和验收要求。

| 签认 | 采用的 v1 方向 | 留待后续的范围 |
| --- | --- | --- |
| Q1 **A** | 全生命周期每 Session 最多一个 Task，Task 最多一次 Assignment，固定一个 Node。终态占位。Owner/Admin 控制，`capture_demo` 为首个工作类型 | 活动任务唯一、多任务、多分析和重派另审 |
| Q2 **A** | Cloud 控制，Edge 上报事实。合法终态先提交优先。父 Session 取消联动未终结任务，保留此前合法完成；迟到合规事实写冲突收据 | 离线临时 Session 的正式接纳与 ID 映射另议 |
| Q3 **A** | 断网、自然过期或单纯撤钥时允许已接单任务继续。经验证的停用/停机持久安全挂起。受控签发恢复同 Node 身份，已停用节点须显式恢复，本地开工另行审计解挂 | 通知渠道、现场和身份核验、凭据交付及解挂实现另审。离线实时远程停机无实现承诺 |
| Q4 **A** | 有效身份的 HTTPS/TLS 主动拉取。节点连号、任务版本、固定追平水位和严格信封校验。逐命令签名及独立任务硬截止不进入 v1 | 已签认设计解释了 Notion 07 草案中的有效期和签名要求，生产密钥分发另议 |
| Q5 **B** | M4.4 必验人工批准的合成 MP4 通过既有 M3 授权、分片、续传和整对象验证。事件与媒体状态独立，原片默认本地且成功后继续保留 | 真实审批人/记录规则和真实数据治理见下方准入项 |
| Q6 **A** | 8192 字节/事件、50 命令/页、双向连续序号、带抖动有界退避、原信封和队列保留、`recovery_required` 人工恢复。隔离 Edge 文件库和 PG17 | [P01–P10](../architecture/cloud-edge-sync-v1.md#timing-register) 只有开发/测试建议，Task 2.2 尚缺退避预算签认 |
| Q7 **A** | 当前来源与身份校验。同归属的停用设备迟到事实经有效身份、格式和因果验证后仅记冲突，可消费上行序号。设备自报时间不能证明历史授权 | 可信历史授权版本另议 |

## 真实数据与生产准入

<a name="production-gates"></a>

M4.4 的批准动作、合成资产、M3 用户权限、隔离 RustFS 和测试证据属于联调条件。真实数据或生产试点须先确认：

- 实际上传审批角色与审批记录规则，包含 Session、具体资产、目的、现行授权和变更审计。
- 视频采集/传输及个人信息处理依据，涉及未成年人时的监护人同意和适用保护要求。
- 生产存储服务、区域、访问控制，以及视频和分析结果的保留期限。
- 备份、删除、撤回、审计与本地原件处置的规则。

对接以 [M3 现有媒体契约](../contracts/cloud-capture-media.md) 和 [Q5 B 验收矩阵](../contracts/cloud-edge-sync-v1.md#media-matrix) 为准。此前 ADR 0003 的 Session 权威、时钟/离线语义及 Registry D12 的凭据约束继续作为继承基线。[ADR 0003](0003-capture-media-domain-contracts.md) · [Registry 契约](../contracts/cloud-edge-registry.md)
