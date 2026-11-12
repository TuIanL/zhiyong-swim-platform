# Tasks

本清单全部未勾选。Q10–Q13（见 [design](design.md#待负责人裁决)）暂按建议默认规划；若 Q11 或 Q13 被否，第 2.6、4.1 组与 proposal 的边界需重写，而不是改勾选状态。

## 1. 迁移与物理模型

- [ ] 1.1 新增 revision `20261112_0003`（`down_revision=20261110_0002`）创建 `training_sessions`、`video_assets`、`upload_sessions`、`session_read_grants`、`asset_read_grants`，含 design 的复合唯一键、复合外键（一律 RESTRICT）、CHECK、部分唯一索引与查询索引；不改写 0001/0002。验证：两后端空库 0001→head 后反射列、约束、索引与模型一致
- [ ] 1.2 扩展 `idempotency_records`：新增 `actor_kind`、`edge_node_id`，`user_id` 改可空，加主体配对 CHECK、节点复合外键、`operation`/`resource_kind` 词表、两条部分唯一索引并删除原唯一约束。验证：两后端 head→0002→head 往返成功，且既有 12 个 Registry 幂等用例不改断言即通过
- [ ] 1.3 把应用测试身份的批准表集合由 10 张扩到 15 张（`pg_support.APPROVED_APP_TABLES`、`test_postgresql_schema` 集合断言、`test_postgresql_identity` 行数断言），保持 `USAGE`、版本表仅 `SELECT`、DDL/TRUNCATE/SET ROLE 拒绝。验证：未批准 canary 表仍无 DML，15 张表正常读写
- [ ] 1.4 增加历史保护与失败回滚用例：带 Session/Asset 的 Site 删除被 RESTRICT 拒绝；迁移中途失败回滚后不留半成品且版本标记不推进。验证：两后端各一条负向用例通过
- [ ] 1.5 在本组内更新 [迁移 0002 之后的模型说明](../../../services/cloud/src/swimplatform/models.py) 对应模型类与 design 的字段表逐项一致（列、可空性、约束名）。验证：模型反射与 design 表格人工逐行比对无差异

## 2. 领域行为与授权

- [ ] 2.1 实现统一授权谓词构造器，供列表、详情、子列表、游标续页共用，覆盖 S-read / S-manage / A-read 与 owner/admin 免 SiteMembership。验证：授权矩阵逐格测试（owner/admin/coach/athlete/非成员/匿名 × 六类资源操作）通过且无手写重复谓词
- [ ] 2.2 实现 Session 创建与读取（含 `created_by_user_id` 由云端写入、归属不可变、请求自报字段 422）。验证：创建/越权归属/跨机构/跨场馆用例通过
- [ ] 2.3 实现 Session PATCH 状态机（planned→recording→completed、planned/recording→cancelled、终态不可回退、同状态重放 200 无副作用）与加锁后判定。验证：状态-时间组合 CHECK 用例与非法迁移 409 用例通过
- [ ] 2.4 实现取消收口：单事务内终结未完成上传并失败其 pending 资产。验证：取消后无 `pending_upload` 残留；取消 vs 中止两个方向各一条用例只有一方获胜且原因不被改写
- [ ] 2.5 实现用户上传意图（`S-manage`、发起人=自己）在一个事务内创建 Asset+UploadSession 并写幂等记录。验证：受控失败后两侧均不存在；同键同参返回同一 ID、同键异参 409
- [ ] 2.6 实现 Edge 上传意图（节点凭据、Session 同 tenant/site、device 属该节点且 active），并证明设备来源与场馆一致性。验证：跨场馆 device、disabled device、跨节点 device 各返回既定 404/409 且不留下记录
- [ ] 2.7 实现上传会话读取、中止与懒物化过期（`expires_at` 由服务端派生，默认 24 小时、上限 7 天）。验证：可控时钟下过期读取返回 `expired` 且 Asset 为 `failed(upload_expired)`；重复中止 204 不重写首次原因与时间
- [ ] 2.8 实现 Session/Asset grant 的 upsert 与软撤销（保留首次 `granted_at`/`granted_by`，重复撤销不覆盖）。验证：重复 PUT 只留一条有效记录；重复 DELETE 204 且执行者与时间不变
- [ ] 2.9 实现采集时间与声明值校验（原始字符串字面值、四类基准交叉规则、`unknown` 禁 UTC、`ready ⇒ checksum/received_at/size/media_type 非空`）。验证：每种基准的合法/非法组合各一条 422 用例，原始字符串含首尾空格往返不变
- [ ] 2.10 实现过滤式游标分页（`created_at DESC, id DESC`、默认 20/上限 100、游标绑定 scope+筛选+排序版本、无 `total_count`）。验证：撤权后续页只返回当前可见项；跨场馆或跨筛选复用游标返回 422 `invalid_cursor`
- [ ] 2.11 实现并集中错误码与检查次序（401→404 机构→404 场馆→404 资源→403 能力；管理类先验角色）。验证：错误目录逐码有用例，且响应体不含未授权资源字段

## 3. 契约与文档

- [ ] 3.1 重新生成 OpenAPI 快照并核对 33 paths / 47 operations，既有 31 个操作的路径、字段、错误不变。验证：快照与运行时 `openapi()` 逐路径比对通过
- [ ] 3.2 更新[领域模型文档](../../../docs/architecture/cloud-capture-media-domain.md)：五张表标为已实现，UploadSession 标注「意图已实现、传输未实现」，派生与存储引用保持未实现。验证：文档「已实现/未实现」两栏与迁移和路由一致
- [ ] 3.3 更新[API 契约文档](../../../docs/contracts/cloud-capture-media.md)：16 个操作标为已实现，part-urls/complete/playback-url 5 个标为 M3 未实现。验证：路径清单与 OpenAPI 快照一一对应
- [ ] 3.4 在 [RBAC 契约](../../../docs/contracts/cloud-rbac.md) 增补 S-read / S-manage / A-read 矩阵、403/404 分界与「场馆授权不等于资源授权」。验证：矩阵每一格都能指向至少一条测试
- [ ] 3.5 在本 Change 内记录 M2/M3 边界与本片偏差清单（已实现 16 / M3 5 / 不实现项）。验证：清单与 design 的偏差表逐项一致

## 4. PostgreSQL 专属验收

- [ ] 4.1 用 `CONCURRENCY_POOL`（`pool_size=8`）与不同 `pg_backend_pid()` 验证四类并发：同键上传意图、取消 vs 中止、过期 vs 中止、同一资源 grant 并发写入。验证：每类断言两个以上不同 PID 且仅一个事务生效
- [ ] 4.2 验证部分唯一索引与 RESTRICT 在真实写入下生效：重复有效 grant 被拒、撤销后可重新授予、父记录删除被拒。验证：PG 专属用例通过并记录约束名
- [ ] 4.3 验证 15 表 schema 反射与本 Change 模型一致，且降级到 0002 后仅剩 10 表、重新升级恢复 15 表。验证：`test_postgresql_schema` 三段集合断言通过

## 5. 集成与交付证据

- [ ] 5.1 跑完整 SQLite 与 PostgreSQL 套件，确认既有 19 基础操作与 12 Registry 操作行为不变、新增用例零跳过（除后端专属跳过）。验证：两后端全绿且 JUnit 无 failure/error
- [ ] 5.2 产出本 Change 的实施验证报告（命令、结果、未验证项、M2 已知限制）。验证：报告区分 SQLite/PG、本机/CI，并显式列出「无 ready 路径」「无清扫作业」「无播放」
- [ ] 5.3 同步 Notion 工程入口与六个原任务的回链（change、分支、提交、PR、范围、阶段、待裁决、下一步），不改任务属性。验证：页面回读确认链接可达且未改状态/负责人/日期
- [ ] 5.4 在同一分支与 Draft PR 提交实现、契约与证据，保持 Draft。验证：PR head 与本地分支一致、CI 对应当前 head

## Workflow follow-up

- 独立 Verify、OpenSpec Archive、主规格同步与 PR 合并分别等待负责人后续明确授权，不因本清单完成而自动执行。
- M3（分片/续传/整对象校验/播放/清扫）另开 Change，不并入本清单。
