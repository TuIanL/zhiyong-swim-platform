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
    media_enabled: bool = False
    media_endpoint_url: str | None = None
    media_region: str = "us-east-1"
    media_bucket: str | None = None
    media_access_key: str | None = None
    media_secret_key: str | None = None
    media_profile: str = "s3"
    media_environment: str = "development"
    media_run_id: str | None = None
    media_part_size_bytes: int = 16 * 1024 * 1024
    media_part_url_seconds: int = 300
    media_read_url_seconds: int = 60
    media_read_url_max_seconds: int = 300
    media_ffprobe_path: str = "ffprobe"
    media_ffprobe_version: str = "6.1.1"

    @classmethod
    def from_environment(cls):
        # 不读取旧项目或父目录的 .env，不使用泛化 DATABASE_URL。
        enabled = os.getenv("SWIM_MEDIA_ENABLED", "false").strip().lower() == "true"
        values = {
            "database_url": os.getenv("SWIM_CLOUD_DATABASE_URL", f"sqlite:///{ROOT / 'var/cloud.sqlite3'}"),
            "media_enabled": enabled,
            "media_endpoint_url": os.getenv("SWIM_MEDIA_ENDPOINT_URL"),
            "media_region": os.getenv("SWIM_MEDIA_REGION", "us-east-1"),
            "media_bucket": os.getenv("SWIM_MEDIA_BUCKET"),
            "media_access_key": os.getenv("SWIM_MEDIA_ACCESS_KEY"),
            "media_secret_key": os.getenv("SWIM_MEDIA_SECRET_KEY"),
            "media_profile": os.getenv("SWIM_MEDIA_PROFILE", "s3"),
            "media_environment": os.getenv("SWIM_MEDIA_ENVIRONMENT", "development"),
            "media_run_id": os.getenv("SWIM_MEDIA_RUN_ID"),
            "media_part_size_bytes": int(os.getenv("SWIM_MEDIA_PART_SIZE_BYTES", str(16 * 1024 * 1024))),
            "media_part_url_seconds": int(os.getenv("SWIM_MEDIA_PART_URL_SECONDS", "300")),
            "media_read_url_seconds": int(os.getenv("SWIM_MEDIA_READ_URL_SECONDS", "60")),
            "media_read_url_max_seconds": int(os.getenv("SWIM_MEDIA_READ_URL_MAX_SECONDS", "300")),
            "media_ffprobe_path": os.getenv("SWIM_MEDIA_FFPROBE_PATH", "ffprobe"),
            "media_ffprobe_version": "6.1.1",
        }
        settings = cls(**values)
        if settings.media_enabled:
            if settings.media_environment not in {"development", "isolated-test"}:
                raise ValueError("媒体 profile 仅允许开发或隔离测试环境；生产配置尚未冻结")
            if settings.media_profile not in {"s3", "rustfs-isolated"} or not all((
                settings.media_endpoint_url, settings.media_bucket,
                settings.media_access_key, settings.media_secret_key,
            )):
                raise ValueError("SWIM_MEDIA_ENABLED 需要 S3 profile 与 endpoint/bucket/Secret 配置")
            if settings.media_environment == "isolated-test" and (
                settings.media_profile != "rustfs-isolated" or not settings.media_run_id
            ):
                raise ValueError("隔离测试媒体必须锁定 rustfs-isolated profile 与本次 run id")
            if not 5 * 1024 * 1024 <= settings.media_part_size_bytes <= 64 * 1024 * 1024:
                raise ValueError("媒体分片配置超出允许范围")
            if settings.media_part_url_seconds > 300 or settings.media_part_url_seconds < 1:
                raise ValueError("分片 URL TTL 必须为 1..300 秒")
            if not 1 <= settings.media_read_url_seconds <= settings.media_read_url_max_seconds <= 300:
                raise ValueError("读取 URL TTL 配置无效")
        return settings
