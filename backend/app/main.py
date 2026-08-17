
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.logging import configure_logging
from app.middleware import CorrelationIdMiddleware
from app.errors import register_exception_handlers
from app.api.router import api_router


logger = logging.getLogger(__name__)

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
        lifespan=lifespan
    )
    
    app.add_middleware(CorrelationIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    
    return app

app = create_app()