# M3 Propose 交接与检查记录

日期：2026-11-14。阶段：**Explore + Propose，待负责人审阅；未 Apply**。

## 基线与产物

- Repository：`TuIanL/zhiyong-swim-platform`；基线 main：[3352c6b17b2dd3b6921028b25606a999bb69b331](https://github.com/TuIanL/zhiyong-swim-platform/commit/3352c6b17b2dd3b6921028b25606a999bb69b331)。本地 main 已快进到此提交；工作分支 `feat/cloud-media-upload-transfer`。
- 唯一活跃 Change：`implement-cloud-media-upload-transfer`，spec-driven，未设置skip_specs；规划图四类产物齐备，实施 **0/42**。
- [Proposal](proposal.md)、[Design](design.md)、[Tasks](tasks.md)、[六份Delta](specs/)；共29项增量要求（18 ADDED、11 MODIFIED）、91个场景。M2归档及其四项WARNING保持原样，W1–W4分别进入任务1.2–1.5，不能在Propose标为修复完成。
- 直接任务：[P1 分片上传与完整性校验](https://app.notion.com/p/410f602574aa8129ab07d088ad80aa5b)，原状态待确认；工程入口：[Notion](https://app.notion.com/p/410f602574aa81288834cc297ae5b039)。关联原任务与子范围见Design追溯表，不建新任务、不改状态/负责人/日期。

## 实际规划检查

- `openspec validate implement-cloud-media-upload-transfer --strict` 通过；主规格 `openspec validate --specs --strict` 为5/5通过。CLI规划done仅代表文件完整，`openspec list --json`为0/42，不能当作业务完成。
- Markdown检查范围为仓库已跟踪文件加本Change新文件，排除用户未跟踪模板；本README加入后共72份Markdown、281个相对链接和1个锚点，均有效。检查包含新文件，不能仅依空的未暂存`git diff`声称无范围外改动。
- 对所有MODIFIED块逐项比较原主规格要求名及原场景名，没有遗漏原场景；M2无直接完成场景保留原标题并明确其“不可绕过校验”的M3行为变化，不删除历史要求规避strict。
- G1–G6、M2 W1–W4、ADR D1–D10/C1–C5、十个新增操作、19表候选与Q1–Q8已做设计/任务/Delta交叉核对。发现并通过Delta处理Registry“仅heartbeat”与M2节点上传范围的来源冲突；正式主规格本轮不动。
- `git diff --check`通过；提交范围仅本Change。业务代码、数据库、迁移、OpenAPI、CI、主规格与M2归档均不修改。
- `.workbuddy/`、`docs/workflow/`仍未跟踪，5个既有文件逐文件SHA-256与本轮开始一致，不纳入PR。

## CI与未验证范围

M2归档head `dbad6a1`的[CI 43567828849](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/43567828849)已通过，SQLite与PostgreSQL两个job均success；这是读取到的历史前置证据。固定M2业务核验head及详细用例/清理结果见[M2 Verify](../archive/2026-11-14-implement-cloud-session-asset-foundation/verification.md)，不改写报告。

本轮不在本机运行M3业务测试、不创建存储实例、不执行迁移。提案push/PR会运行现有CI，最新head对应状态在PR和Notion记录；它仅证明现有基线回归，**不证明尚未实现的M3分片、校验、清扫或访问已验收**。本文件不是独立OpenSpec Verify报告。

## 下一步与停止条件

Q1开发/CI存储profile、Q3分片/容量候选（含新增意图大小收窄）、Q4媒体类型/最终失权行为需负责人审阅；Q2生产产品/区域/隐私保留等决策不由本稿冻结，Q5清理参数与Q6/Q7运行配置有明确门槛；Q8/M4另阶段。参数确认不自动授权Apply。

发布同一分支Draft PR并同步工程入口、原分片任务和相关原任务后停止，等待新的明确Apply授权。Verify、Archive、主规格同步、Ready与Merge不得自动执行；本片不表示原P0/P1总体任务或整个项目完成。
