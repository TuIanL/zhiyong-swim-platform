from dataclasses import dataclass
from pathlib import Path
import os

def project_root():
    # 兼容源码运行以及项目内独立venv中的wheel安装，不能依赖固定父目录层数。
    for parent in Path(__file__).resolve().parents:
        metadata = parent / "pyproject.toml"
        if metadata.is_file() and 'name = "swim-platform-cloud"' in metadata.read_text():
            return parent
    raise RuntimeError("未找到新版项目根目录；请从新版工作区安装运行")


ROOT = project_root()


@dataclass(frozen=True)
class Settings:
    database_url: str
    session_seconds: int = 3600

    @classmethod
    def from_environment(cls):
        # 不读取旧项目或父目录的 .env，不使用泛化 DATABASE_URL。
        return cls(os.getenv("SWIM_CLOUD_DATABASE_URL", f"sqlite:///{ROOT / 'var/cloud.sqlite3'}"))
