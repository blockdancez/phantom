from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.database import init_db, close_db
from app.logging_setup import setup_logging
from app.middleware import RequestIdMiddleware
from app.routes.ideas import router as ideas_router
from app.routes.documents import router as documents_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    setup_logging(settings.log_level)
    await init_db()
    yield
    await close_db()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(RequestIdMiddleware)

    app.include_router(ideas_router)
    app.include_router(documents_router)

    return app
