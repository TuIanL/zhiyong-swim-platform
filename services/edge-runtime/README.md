# Edge Runtime

Mike 负责场馆本地计算服务及其依赖、数据、测试、部署和运维交付。Edge API、Device Manager、Video Ingest、Media Catalog、Local Storage、Task Runtime、Worker Lifecycle、Offline Recovery 和 Operations 作为同一运行时的内部模块。独立进程拆分需另行评审。

本目录是开发入口。首个可运行切片在此交付独立依赖与锁文件、启动命令、单元及集成测试，并覆盖合成视频采集和断网恢复。通过版本化 Edge API 对接 Venue Console，通过[云边同步契约](../../docs/contracts/cloud-edge-sync-v1.md)对接 Cloud。

场馆部署说明见 [venue Profile](../../deploy/venue/README.md)。
