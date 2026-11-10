# 采集与媒体领域契约归档记录

- Change：`define-cloud-capture-media-contracts`；schema：`spec-driven`。
- 归档日期：2026-11-10（Asia/Shanghai）。
- 授权：负责人确认独立Verify通过，明确授权归档并提交到现有Draft PR #3；不转正式评审、不合并、不创建下一业务Change。
- 归档前基线：`78708928ad6b0f7201d432320eb93252b5ca0202`；独立Verify固定对象仍为 `f029864b3d716306f3147faf80655cf4851f8bc8`。
- 归档前CLI：proposal/design/tasks全部done，specs合法skipped；任务11/11，无未完成项。[独立核验](verification.md)为CRITICAL 0 / WARNING 0 / SUGGESTION 0、Not verified 0；全部适用检查通过。

## 正式归档操作与规格边界

实际执行项目当前CLI正式命令：

```bash
openspec archive define-cloud-capture-media-contracts --yes --skip-specs --json
```

CLI返回 `archivedAs=2026-11-10-define-cloud-capture-media-contracts`、`specsUpdated=false`，正式归档目录即本目录；未以手工移动代替归档命令。归档前先确认目标不存在，未覆盖旧归档。

本Change的`.openspec.yaml`保留`skip_specs: true`，status返回的`artifactPaths.specs.existingOutputPaths`为空：**No delta specs**，无需同步，未修改主规格。

## 历史文件完整性

CLI移动完成、修正链接之前，对原6份文件逐一核对SHA-256全部一致：

| 历史文件 | 归档后处理 |
| --- | --- |
| [.openspec.yaml](.openspec.yaml) | 原字节不变，含schema、created及skip_specs |
| [README](README.md) | 原字节不变 |
| [proposal](proposal.md) | 仅修正5处向仓库根引用的相对链接 |
| [design](design.md) | 仅修正5处向仓库根引用的相对链接 |
| [tasks](tasks.md) | 原字节不变，保留11个完成勾选 |
| [verification](verification.md) | 仅修正5处文档相对链接；固定核验SHA、证据行号、结论和原始CI均保留 |

另新增本归档记录。历史阶段、授权及核验事实没有改写为新的批准。

## 正式设计文档与范围

[采集领域模型](../../../../docs/architecture/cloud-capture-media-domain.md)、[API契约](../../../../docs/contracts/cloud-capture-media.md)、[既有领域模型接线](../../../../docs/architecture/cloud-domain-model.md)及[Apply交叉核对记录](../../../../docs/verification/cloud-capture-media-contracts-apply.md)保持原字节；[ADR 0003](../../../../docs/decisions/0003-capture-media-domain-contracts.md)仅将Proposal和Design两处来源链接指向本归档目录，设计正文未改。四份设计文档与交叉核对记录均保留。

原71份跟踪文件中，6份作为本Change历史归档；其余65份中仅ADR的两处路径更新，另外64份原字节不变。`.workbuddy/`与`docs/workflow/`原4份未跟踪文件保持原哈希且未纳入提交。

业务代码、数据库、迁移、OpenAPI、配置、依赖、CI与主规格均未改；不连接数据库、不执行迁移、不在本机重跑不受路径移动影响的业务测试，不创建下一阶段Change。

## 检查与发布证据

- 归档后运行`openspec list --json`确认活跃Change为空；`openspec validate --all --strict --json`主规格1/1通过，`openspec validate --archived --strict --json`三项归档3/3通过。
- 归档后的历史文件与全部当前跟踪Markdown（含本记录）共34份，134处本地路径链接、含1处标题锚点，0失效；`git diff --check`通过。归档提交SHA在下列PR/Notion最终发布记录绑定，避免把报告提交前的CI当作归档head CI。
- 归档前报告提交`7870892`的[CI 42734676200](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42734676200)保留为历史：SQLite112 passed/39 skipped，PG150 passed/1 SQLite专属skipped；主清理removed，兜底absent/exit0。
- 归档提交及其最新CI在[Draft PR #3](https://github.com/TuIanL/zhiyong-swim-platform/pull/3)和[Notion工程入口](https://www.notion.so/410f602574aa81288834cc297ae5b039)同步；固定提交的历史证据链接不改指向。

归档只完成采集/媒体契约文档Change。Notion数据模型/历史资产取舍、架构/API两项总体任务仍进行中；媒体授权、Edge注册、分片上传和组织模型未因此完成。四实体与新API仍是草案，未实施。

本轮main保持`afb0e5fce4c187c8d3c3d5607d2a675375c2a04d`；PR #3保持Draft、未合并。归档后等待负责人最终审阅，不自动转Ready for review或执行GitHub Merge。
