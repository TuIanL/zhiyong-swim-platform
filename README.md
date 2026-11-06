# 智泳云枢 · 新版平台

独立重建的游泳智能视频分析平台。首个开发切片是**账号、机构与场馆的云端基础**。

仓库：[TuIanL/zhiyong-swim-platform](https://github.com/TuIanL/zhiyong-swim-platform)。产品需求与任务：[Notion 项目](https://app.notion.com/p/410f602574aa816ea4a6f2b06985d412)。

## 当前已实现

- 账号注册、登录、可撤销/过期会话、当前账号、退出登录。
- 机构创建与当前用户所属机构查询；创建者成为该机构所有者。
- 机构成员管理及 owner/admin/coach/athlete 角色边界。
- 场馆创建、列表、详情和修改；教练/学员通过明确场馆授权访问。
- 服务器端机构/场馆归属检查、跨机构负向测试、专用测试库和独立初始迁移。

这是本地开发基线，尚未完成商业化平台。网页应用、邮件验证/找回密码、所有权转移、平台管理员、PostgreSQL/RLS 实测、外部身份系统、审计日志、Edge、媒体/视频与模型接入均待后续建设；当前没有复制旧演示数据或接入真实学员资料。

## 启动

使用 Python3.13，创建新版自己的环境：

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.lock
python -m pip install . --no-deps
sh scripts/dev-cloud.sh init-db
sh scripts/dev-cloud.sh serve
```

交互接口：[http://127.0.0.1:8200/docs](http://127.0.0.1:8200/docs)。先注册、登录，再把返回的 access_token 填入 Authorize，即可创建机构和场馆。

开发数据库默认为本项目 `var/cloud.sqlite3`，不读取旧 `.env`。`init-db` 只允许新版 `var/` 内的 SQLite 文件；应用启动不会自动迁移数据库。没有默认账号、密码或超级管理员。

## 验证

```bash
python -m pytest
OPENSPEC_TELEMETRY=0 openspec validate --specs --strict
```

每项集成测试在 pytest 临时目录创建真实 SQLite 库并执行新版迁移，不连接旧库。当前覆盖注册角色注入、密码与会话、账号锁定、机构隔离、场馆授权/撤销、成员移除、复合外键、迁移一致性与安全初始化。PostgreSQL 驱动已声明，尚未实际运行 PostgreSQL；SQLite 的通过不作为 PostgreSQL/RLS 验收证据。

## 结构

```text
services/cloud/       新版云端 API、迁移、测试
docs/contracts/       API 与角色权限契约
docs/decisions/       决策及实现边界
docs/reference/       历史资产的选择性借鉴记录
openspec/             新版规格，不直接继承旧规格的完成状态
configs/              非敏感配置与模型选型记录
var/                  本地开发数据（不提交）
```

已创建新版专属 `.venv`，独立安装依赖并构建/安装项目 wheel，没有复用旧 `.conda` 或 `.env`、也没有向全局安装依赖。依赖锁记录本轮验证组合；依赖漏洞审计、其他操作系统及 PostgreSQL 环境仍需验证。开发脚本显式使用新版源码与环境；源码改动后无需重新安装 wheel。

本机曾出现隐藏 `.pth` 被 Python3.13 忽略的可编辑安装问题，已通过正常 wheel 安装及显式源码开发入口验证；打包回归用例防止 pytest 的源码路径掩盖安装问题。


公开注册只创建账号。机构角色来自服务端成员关系，不能由登录请求或注册字段指定。会话采用随机 bearer token，数据库仅存摘要；开发示例不将 token 写入文件。面向公网前仍需完成 TLS、注册/登录入口限流、邮箱验证、运维与安全评审。

历史代码、界面、视频、PPT 和研究资料位于本仓库外的历史归档。只按模块评估后引入，并保留来源、许可证、契约与回归证据。
