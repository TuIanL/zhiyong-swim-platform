# Personal Workbench

Mike 负责独立个人视频上传、分析提交、指标展示、报告及历史。Personal Upload API 可先作为本模块的内部后端。独立部署或依赖隔离有明确需求时，再评审是否提取为独立服务。

本目录是开发入口。首个可运行切片在此交付前后端依赖、锁文件、启动与构建命令，以及上传、来源适配、Mock Analysis Gateway 和 E2E 测试入口。个人来源通过适配器接入项目负责人维护的统一分析契约，保留真实来源归属。通过 [personal Profile](../../deploy/personal/README.md) 独立交付。
