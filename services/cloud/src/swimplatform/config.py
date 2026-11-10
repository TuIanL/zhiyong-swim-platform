from dataclasses import dataclass
from pathlib import Path
import os

def project_root():
    # 源码运行/项目venv安装时定位项目；独立wheel运行时以启动目录作为本地数据根。
    for parent in Path(__file__).resolve().parents:
        metadata = parent / "pyproject.toml"
        if metadata.is_file() and 'name = "swim-platform-cloud"' in metadata.read_text():
            return parent
    return Path.cwd().resolve()


ROOT = project_root()


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_seconds: int = 3600

    @classmethod
    def from_environment(cls):
        # 不读取旧项目或父目录的 .env，不使用泛化 DATABASE_URL。
        return cls(os.getenv("SWIM_CLOUD_DATABASE_URL", f"sqlite:///{ROOT / 'var/cloud.sqlite3'}"))
