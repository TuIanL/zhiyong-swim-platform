from pathlib import Path
from alembic import command
from alembic.config import Config

MIGRATIONS = Path(__file__).resolve().parent / "migrations"


def migrate_database(url: str):
    """显式调用方提供目标；应用启动不调用此函数。"""
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
