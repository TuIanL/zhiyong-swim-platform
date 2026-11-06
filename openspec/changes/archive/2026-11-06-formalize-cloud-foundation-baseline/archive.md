# 归档记录

归档日期：2026-11-06（Asia/Shanghai）。变更：`formalize-cloud-foundation-baseline`；schema：`spec-driven`。

用户在规划确认、apply及独立verify完成后，明确调用`openspec-archive-change`。本次按CLI返回的planningHome/changeRoot执行归档，未扩展业务功能。

| 归档输入 | 结果 |
| --- | --- |
| proposal / design / tasks | 全部done |
| specs | skipped；`skip_specs: true`；artifactPaths.specs.existingOutputPaths为空 |
| CLI任务计数 | 12/12完成，未完成0；唯一匹配项，计数有效 |
| 独立verify | [报告](verification.md)针对apply提交b3139f1；适用检查全部通过，CRITICAL/WARNING/SUGGESTION均0 |
| 目标目录 | `openspec/changes/archive/2026-11-06-formalize-cloud-foundation-baseline`；移动前不存在，没有覆盖既有归档 |
| 主规格同步 | No delta specs；未执行sync，主规格保持原文 |
| 原记录保留 | proposal、design、tasks、verification和.openspec.yaml五份文件移动后SHA-256全部与移动前一致 |

归档前提交为`279ed0b885fc43ed798f967d94f3e9791de22fa9`。已修正正式基线及验证记录到归档目录的相对链接；不可变提交中的历史证据链接保留原指向。

本次仅移动本change并保存归档记录，不连接数据库、不导入旧数据、不重跑本地业务测试，不修改业务源码、迁移、依赖或现有主规格。原规划、apply与verify中“尚未归档”的表述保留为对应阶段历史，以本记录为当前归档阶段说明。

PR #1沿用同一分支，归档和发布不等于PR已合并；项目任务及全平台验收仍按Notion中的实际范围处理。PostgreSQL/RLS及未来实体仍为后续独立提案范围。

## 归档后检查

- `openspec list --json`已不再列出该活跃change，root仍为独立新版工程。
- `openspec validate --specs --strict --json`：cloud-identity 1/1通过。
- 全工程Markdown相对链接检查通过，共42处；原5份change记录字节一致，12个任务勾选保留。
- 受保护的源码、迁移、配置、依赖、测试、原验证记录、OpenAPI与主规格未改变；Git差异检查通过。
