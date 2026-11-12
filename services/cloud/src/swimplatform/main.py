from contextlib import asynccontextmanager
from datetime import UTC, datetime
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .api import router
from .config import Settings
from .database import database
from .edge_registry import router as edge_registry_router
from .media import router as media_router


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_environment()
    engine, sessions = database(settings.database_url)

    @asynccontextmanager
    async def lifespan(_):
        # 启动不建表、不迁移、不导入历史数据。
        yield
        engine.dispose()

    app = FastAPI(title="智泳云枢｜新版云端基础", version="0.1.0", lifespan=lifespan)
    app.state.settings, app.state.engine, app.state.sessions = settings, engine, sessions
    app.state.clock = lambda: datetime.now(UTC)
    app.include_router(router)
    app.include_router(edge_registry_router)
    app.include_router(media_router)

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
