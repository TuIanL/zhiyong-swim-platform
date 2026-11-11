# Cloud Edge Registry Apply 交付证据

> 本记录覆盖 `implement-cloud-edge-device-foundation` 的 Apply，不是独立 Verify、Archive、主规格同步或合并结论。四个实施实体和12个API操作只代表本Change范围；不代表完整Edge Runtime、云端媒体业务或平台项目已完成。

- OpenSpec Change：[implement-cloud-edge-device-foundation Proposal](../../openspec/changes/archive/2026-11-11-implement-cloud-edge-device-foundation/proposal.md)
- PR：[Draft PR #4](https://github.com/TuIanL/zhiyong-swim-platform/pull/4)
- Apply批准基线：`334f589b66e22dc55716f5e6befb44d31e003cd1`
- 事实main基线：`d7f1eedb13ac0f44abb738bc6e8b4d0d38d7766d`
- 可复查实现：[Edge API](../../services/cloud/src/swimplatform/edge_registry.py)、[模型](../../services/cloud/src/swimplatform/models.py)、[增量迁移](../../services/cloud/src/swimplatform/migrations/versions/20261110_0002_cloud_edge_registry.py)、[API契约](../contracts/cloud-edge-registry.md)、[领域模型](../architecture/cloud-edge-registry-domain.md)

## Apply范围与实现证据

本Change在初始六表基础上增加四表：`edge_nodes`、`devices`、`edge_credentials`、`idempotency_records`。迁移版本为 `20261110_0002`，依赖 `20261106_0001`；初始revision文件内容保持逐字节一致。旧的 `services/cloud/migrations` 路径保留兼容入口，Alembic迁移资源也随 `swimplatform` 包发布。

| 能力 | 实现位置与边界 |
| --- | --- |
| 12个操作 | 4个Node管理、4个Device管理、3个Credential操作、1个Edge heartbeat；[OpenAPI快照](../contracts/openapi.json)总计21 paths / 31 operations，其中基础19项保持兼容 |
| 归属与历史 | Site/Node复合外键、RESTRICT、状态与字段检查；登记历史不因成员关系撤销而级联删除；无Node/Device删除端点 |
| D11 Camera-first | Device.kind第一版只接受`camera`；一摄一车随车移动是物理关系，不创建Cart或泳池固定机位；Device ID和kind字段保持未来扩展边界 |
| D12 EdgeCredential | 默认7天、最长30天、服务端UTC；明文仅首次成功签发返回，普通读取不返回明文/hash；撤销不可恢复，生命周期记录签发/撤销主体与时间 |
| D13 Heartbeat | 默认发送30秒、服务端接收时间为权威；Node active且距最近有效心跳不足90秒才online；有界输入，不把心跳失败转成行政停用，也不把90秒描述为SLA |
| 身份和并发 | User与Edge身份只用于各自操作；PostgreSQL Node行锁和SQLite数据库写锁串行化相关状态变更；Node停用与凭据撤销同事务提交 |
| 持久幂等 | Node/Device/Credential创建请求在同事务存储键摘要/请求摘要/资源引用；异参409；凭据重放返回可见ID但不重放secret |
| PostgreSQL最小权限 | 测试身份仅对明确批准的10张业务表有DML；`alembic_version`只读；保留拒绝未批准表、DDL、TRUNCATE和角色切换的测试 |

## 本地验证

| 检查 | 命令/证据 | 结果 |
| --- | --- | --- |
| 完整默认SQLite套件 | `PYTHONPATH=services/cloud/src .venv/bin/python -m pytest -o addopts='' -q` | 121 passed、47 skipped、0 failed；跳过项要求专用PostgreSQL后端 |
| Registry模型/API定向回归 | `pytest services/cloud/tests/test_edge_registry_schema.py services/cloud/tests/test_edge_registry_api.py` | 9 passed；包含无副作用同状态PATCH、角色边界、幂等、明文不泄露、期限、在线边界和35天离线行为 |
| Change strict | `OPENSPEC_TELEMETRY=0 openspec validate implement-cloud-edge-device-foundation --strict --json` | 1/1 passed，0 issues |
| 主规格 strict | `OPENSPEC_TELEMETRY=0 openspec validate --specs --strict --json` | cloud-identity 1/1 passed，0 issues；本次未同步/修改主规格 |
| Markdown本地链接 | 一次性Python解析器扫描43份跟踪Markdown；检查191处本地路径链接，且单独确认1个标题锚点目标存在 | 0失效 |
| Git whitespace | `git diff --check` | 通过 |
| 初始迁移一致性 | 将批准基线的 `20261106_0001_cloud_identity.py` 与包内文件逐字节比较 | 完全一致，3214 bytes |
| wheel独立安装 | `python -m pip wheel --no-deps --no-build-isolation .`；再将wheel安装至隔离target，以`python -I`从临时目录运行 | wheel `swim_platform_cloud-0.1.0-py3-none-any.whl`；SHA-256 `3fe82e511f2d94df1af5852e260f8a1d063178e86f2ab4490099a8826c57e27e` |

wheel包含Registry模块、初始迁移和 `20261110_0002`。隔离安装后的应用启动不自动迁移（`/ready`对空库返回503）；`init-db`对临时目录`var/`以外SQLite目标拒绝且不创建文件；在临时工作目录自己的`var/`内显式初始化成功，revision为`20261110_0002`、含11张表（10张业务表及`alembic_version`）。

本机Docker daemon未启动，未在本机声称执行PostgreSQL；真实数据库结果来自PR #4专用PostgreSQL 17 Actions job。实现代码head `1b3863483080e0f877147d20689a81960e71a180` 的[CI run 42823504176](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42823504176)（run 63）两job均成功：SQLite `121 passed, 49 skipped`（49项均为PG专属）；PG `shared=120, postgresql=49`，`169 passed, 1 skipped`（仅SQLite专属），0 failed。新增UTC及Asia/Shanghai独立数据库会话凭据截止前/恰好/之后场景各通过。PG日志记录专用run id `21f52896263968a4`，结果`passed`、主清理`removed`；CI always兜底再次核验容器为`absent`、`exit_code=0`，摘要状态/结果一致。脱敏测试证据上传为[postgresql-evidence artifact 13766394673](https://github.com/TuIanL/zhiyong-swim-platform/actions/runs/42823504176/artifacts/13766394673)，同head。workflow含权限、schema、角色、迁移、真实独立backend并发、D11–D13及核心API完整回归。此前失败的执行只暴露测试夹具问题：密码遮蔽的URL重建、账号种入错误应用数据库、三请求竞态监听器精确计数；已逐一修正，最终上述运行通过。最终文档提交还会触发PR检查，并在PR/Notion交付记录中列出其head对应的CI。

## 任务状态与阶段边界

当前`tasks.md`为14/14：四表模型/增量迁移、12个API操作、权限与并发验证、D11–D13验收、双后端完整测试、wheel独立安装、文档和Notion同步均有交付证据。这里的完成仅表示本OpenSpec Apply工作项完成；Notion唯一原始[P1 Edge Node任务](https://www.notion.so/410f602574aa81e9bfa5cb7ca947e7f7)已提交负责人验收（待验收），[新版工程入口](https://www.notion.so/410f602574aa81288834cc297ae5b039)已记录交付。其他P0/P1任务状态与属性不变，不标记整个P1或云端平台完成。

Apply停止时保持 PR #4 Draft、`main` 不变。独立Verify、OpenSpec Archive、主规格同步和GitHub Merge均等待项目负责人分别授权。
