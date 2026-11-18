import argparse
import json
from pathlib import Path
from sqlalchemy.engine import make_url
from .config import ROOT, Settings
from .migrate import migrate_database


def main():
    parser = argparse.ArgumentParser(description="新版本地库与受控媒体后台操作")
    parser.add_argument("command", choices=["init-db", "media-worker", "media-sweep"])
    parser.add_argument("--once", action="store_true", help="media-worker 只处理一个已持久化作业")
    parser.add_argument("--execute", action="store_true", help="media-sweep 执行隔离测试残留清理；默认 dry-run")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    settings = Settings.from_environment()
    if args.command == "init-db":
        url = make_url(settings.database_url)
        if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
            raise SystemExit("拒绝：该命令只允许新版 var/ 内的 SQLite 本地开发库")
        target = Path(url.database).resolve()
        if not target.is_relative_to((ROOT / "var").resolve()):
            raise SystemExit("拒绝：数据库路径不在新版 var/ 目录内")
        target.parent.mkdir(parents=True, exist_ok=True)
        migrate_database(str(url))
        print("新版本地开发库已初始化，head=20261114_0004")
        return

    if not settings.media_enabled:
        raise SystemExit("媒体 profile 未启用；开发配置缺失时不连接对象存储")
    from .main import create_app
    from .media_transfer import cleanup_candidates, run_worker, sweep_expired
    app = create_app(settings)
    try:
        provider = app.state.storage_provider
        try:
            provider.check_capabilities()
        except Exception as exc:
            raise SystemExit(f"对象存储能力校验失败，拒绝启动媒体后台操作：{type(exc).__name__}") from exc
        if args.command == "media-worker":
            run_worker(app.state.sessions, provider, settings, once=args.once)
            return
        expired = sweep_expired(app.state.sessions, limit=args.limit)
        cleanup = cleanup_candidates(app.state.sessions, provider, settings,
                                     execute=args.execute, limit=args.limit)
        print(json.dumps({"expired": expired, "cleanup": cleanup}, sort_keys=True))
        if args.execute and cleanup["failed"]:
            raise SystemExit(1)
    finally:
        app.state.engine.dispose()


if __name__ == "__main__":
    main()
