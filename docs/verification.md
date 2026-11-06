# 新版云端基础验证记录

日期：2026-11-06。本轮范围为独立新工程与账号、机构、场馆的本地开发切片。

| 检查 | 结果 |
| --- | --- |
| 独立 Python3.13 venv 安装 | 已完成；依赖按 pyproject 安装，未使用旧项目环境 |
| 项目正常 wheel 构建/安装 | 已完成；补充独立进程的安装与根目录回归 |
| 新版测试 | 22 passed；每项使用临时 SQLite 真实迁移，无数据库相关跳过 |
| pip check | No broken requirements found |
| OpenSpec strict | cloud-identity 1/1 通过 |
| 实际HTTP启动 | 本机127.0.0.1:8200的health/ready均成功；导出OpenAPI，共14个path |
| 开发库初始化 | 新版var/cloud.sqlite3成功；外部与旧路径初始化拒绝用例通过 |

HTTP检查结束已停止专用测试服务，没有停止旧项目服务。OpenAPI不包含业务数据；数据库、原始日志和venv在var/.venv中不提交。

独立环境测试有1条Starlette/AnyIO的BlockingPortal弃用警告，未引发失败；后续依赖升级应重新验证。

此处不包含PostgreSQL/RLS、UI、生产部署、邮件验证、密码找回、分布式限流、完整安全审计、Edge/视频或AI分析验收，也未访问旧数据库。独立venv安装与本机HTTP检查曾受到沙箱网络/端口限制，使用受控的联网安装与本机临时启动完成验证。
