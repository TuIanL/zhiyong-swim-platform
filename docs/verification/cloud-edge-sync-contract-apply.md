# M4.1 纯文档 Apply 证据

**本记录用于 Apply 自检和独立 Verify 交接。**

- 记录日期为 2026-11-18（Asia/Shanghai）。
- 主线基线为 `94fed6b03d50ccca52f6ec959bcde1636148c65c`，签认参考的二轮 Propose Head 为 `a26d0065ff0a6f3c9925292176d4a4e33c4d1d6b`，签认提交为 `ef17d966a46d99da03e5c2ab68e3b2d401268c37`。提交后的 CI 证据记录在 [Draft PR #7 正文](https://github.com/TuIanL/zhiyong-swim-platform/pull/7)，分别绑定各自 SHA。
- [正式架构、锁依赖及 Q6 参数](../architecture/cloud-edge-sync-v1.md) · [API、样例与验收矩阵](../contracts/cloud-edge-sync-v1.md) · [ADR 0004](../decisions/0004-cloud-edge-sync-v1.md)

## 任务与证据

| 任务 | 阶段结果 | 复核证据 |
| --- | --- | --- |
| 1.1 范围与权威 | 完成 | Q1/Q2/Q5/Q7 已签认，D1 数据权威和独立人工 M3 路径。T1–T9、R2/R6/R8 和 M1–M6 表达原片默认本地、任务终态与媒体验证分离。 |
| 1.2 凭据与下发 | 完成 | Q3/Q4 已签认。D12 的 7 天默认、30 天上限、UTC 服务端权威及受控再签发在架构、S1.1/S7.1/S7.2 和 C1–C4 之间一致。四阶段定义涵盖未接单、接单与开工。 |
| 2.1 协议和样例 | 完成 | D2–D4、状态及错误、规范化、收据和样例已纳入唯一 API 文档。正反样例适用于 S1.1/S1.2/S3.3/S5.2。M3 意图字段对照当前 schema 并使用合成夹具的实际大小与 SHA-256。 |
| 2.2 可靠性与参数 | 完成 | 负责人签认 [P01–P10](../architecture/cloud-edge-sync-v1.md#timing-register) 原建议值，仅限隔离开发与测试。复核 A1/A2、S3.1/S3.2、R4、S5.1 的事务、ACK、预算、重连与人工恢复，见[走读证据](#task-2-2)。 |
| 2.3 终态与并发 | 完成 | 保留先取消、先完成、父 Session 取消及未接单/已接单未开工轨迹。L1–L4 对照基线两条锁依赖，给出 PG17 双连接与稳定提交序断言。 |
| 3.1 需求、场景与交接 | 完成 | 原 8 项 R、19 项 S、19 项 T/A/C/L 保留编号及归属，M1–M6 单列。六份主规格与 M1–M3 归档为兼容基线。M4.2/M4.3/M4.4 的接线、验收和前置见 D6。 |
| 3.2 静态验证与交接 | 完成 | Change strict、主规格 strict、skip_specs 与零 Delta、链接和样例检查、追溯及 Git diff 均见下节。 |

## Task 2.2 补签与走读

<a name="task-2-2"></a>

负责人于 2026-11-18（Asia/Shanghai）基于 [6/7 交付 Head](https://github.com/TuIanL/zhiyong-swim-platform/commit/ff5d82c1b4c85e7b438cb125b581a52784cc3f6a) 确认 P01–P10 原建议值仅用于隔离开发与测试。以下为文档走读预期，运行取证属于 M4.2–M4.4。

| 场景 | 复核轨迹及预期 |
| --- | --- |
| A1 / S3.1 | 命令 41 到达但 Edge 未提交即重启，Inbox、命令效果及游标均未推进。若命令已持久提交但 ACK 丢失，重启可补送 `through=41`。Cloud 更新交付水位，接单与开工仍经各自事务和检查。 |
| A2 | 第一页至 41，固定目标 42。追平前无业务接单。若 42 取消同分配，则不接单或开工。否则在有效控制流追平后原子写接单和 Outbox，实际执行另行取得资格。 |
| S3.2 / R4 | Cloud 持久提交上行事实，响应超出 5 秒请求预算。发送端保留原信封及位置，重投后收到同一收据。上行先到序号 2 得到 `sequence_gap`，补 1 后再投 2。重连按本地水位补控制指令、补送 Command ACK、重投原事件后对账。 |
| S5.1 / P06–P07 | 注入零偏移抖动和即时 503，以 1/2/4 秒间隔在第 0/1/3/7 秒尝试，首次加 3 次即停止本轮。总计 30 秒可先触发预算耗尽，仍保留原 ID、序号及信封。重启、连续失败不重置。有效认证的重连对账、显式人工恢复，或至少 60 秒冷却后的受控探测成功才可重置。 |
| R4 / P04 / P10 | 若限流等待超过本轮剩余时间，预算先耗尽且不得提前重投。已确认历史缺口不可恢复时进入 `recovery_required`，保持游标及队列。人工单次操作 300 秒超时后保留挂起，禁止快进至 Cloud 水位。 |

## 走读与兼容边界

- 取消先提交、成功回报先提交以及父 Session 终结的两端投影遵循事务提交顺序。已验证的媒体保持原 M3 历史；迟到事件只有其自身收据或审计。
- 按当前代码走读 Edge 意图、查询和中止中的 Node 先锁，以及 M3 传输/最终发布中的 Session 先锁。锁图表示潜在逆序，L1–L4 的运行证据归 M4.3。只取各路径实际需要的锁。
- Q5 B 的人工批准用隔离测试操作记录。M3 正向和授权失效路径必须通过现有 API、分片操作和 worker，实际运行归 M4.4。真实视频需另行满足 ADR 准入项。
- 原六份主规格及 M1–M3 归档、运行代码、数据库迁移、OpenAPI、依赖和 CI 配置的内容以基线为准。Apply 静态检查和历史 CI 不提供 M4 运行证据。

## 静态验证

- `openspec validate define-cloud-edge-sync-contract --strict` 通过。CLI 识别 `skip_specs: true` 与零行为 Delta，`specs` 为 skipped。
- `openspec validate --specs --strict` 六份主规格均通过，内容与 main 基线一致。`openspec validate --archived --strict` 六项既有归档均通过。
- 检查 8 份交付 Markdown 的 84 个相对链接（含 38 个带锚点链接）。解析 9 个 JSON 请求/响应样例，核对事件和 API 字段、ID 关联、状态、M3 请求模型及实际合成 MP4 指纹。
- 使用 `git diff --check` 及对基线的路径检查，差异只包含已授权的 Apply 文档与本 Change 元数据。

## 交接

M4.1 纯文档 Apply **7/7**。签认的 v1 行为和隔离参数可供 M4.2 与 M4.3 独立起草 Propose。M4.4 依赖双端实现，在隔离环境执行。当前 Draft PR 交接独立 Verify，等待另行授权。
