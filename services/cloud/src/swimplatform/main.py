from contextlib import asynccontextmanager
from datetime import UTC, datetime
import asyncio
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import router
from .config import Settings
from .database import database
from .edge_registry import router as edge_registry_router
from .media import router as media_router
from .media_transfer import router as media_transfer_router
from .storage import S3StorageProvider


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_environment()
    engine, sessions = database(settings.database_url)
    storage_provider = None
    if settings.media_enabled:
        storage_provider = S3StorageProvider(
            endpoint_url=settings.media_endpoint_url,
            region=settings.media_region,
            bucket=settings.media_bucket,
            access_key=settings.media_access_key,
            secret_key=settings.media_secret_key,
            profile=settings.media_profile,
        )

    @asynccontextmanager
    async def lifespan(_):
        # 启动不建表、不迁移、不导入历史数据。
        try:
            if storage_provider:
                await asyncio.to_thread(storage_provider.check_capabilities)
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="智泳云枢｜新版云端基础", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.sessions = settings, engine, sessions
    app.state.clock = lambda: datetime.now(UTC)
    app.state.storage_provider = storage_provider
    app.include_router(router)
    app.include_router(edge_registry_router)
    app.include_router(media_router)
    app.include_router(media_transfer_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "swim-platform-cloud", "version": "0.1.0"}

    @app.get("/ready")
    def ready():
        from fastapi.responses import JSONResponse
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1 FROM alembic_version LIMIT 1"))
        except SQLAlchemyError:
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return {"status": "ready"}

    return app
