import argparse
from pathlib import Path
from sqlalchemy.engine import make_url
from .config import ROOT, Settings
from .migrate import migrate_database


def main():
    parser = argparse.ArgumentParser(description="新版本地开发库管理；不支持迁移旧库或远端库")
    parser.add_argument("command", choices=["init-db"])
    parser.parse_args()
    url = make_url(Settings.from_environment().database_url)
    if url.drivername != "sqlite" or not url.database or url.database == ":memory:":
        raise SystemExit("拒绝：该命令只允许新版 var/ 内的 SQLite 本地开发库")
    target = Path(url.database).resolve()
    if not target.is_relative_to((ROOT / "var").resolve()):
        raise SystemExit("拒绝：数据库路径不在新版 var/ 目录内")
    target.parent.mkdir(parents=True, exist_ok=True)
    migrate_database(str(url))
    print("新版本地开发库已初始化，head=20261106_0001")


if __name__ == "__main__":
    main()
