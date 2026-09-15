
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse

from app.config import Settings, get_settings
from app.logging import configure_logging
from app.middleware import CorrelationIdMiddleware
from app.errors import register_exception_handlers
from app.api.router import api_router


logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


def create_app(settings: Settings | None = None):
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Application starting...")
        yield
        logger.info("Application shutdown...")

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

        @app.get("/", include_in_schema=False)
        async def demo_ui():
            index = STATIC_DIR / "index.html"
            if not index.is_file():
                raise HTTPException(status_code=500, detail="Demo UI not found")
            return FileResponse(index)

    return app


app = create_app()