import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.router import router
from app.config.settings import get_settings
from app.core.logging import configure_logging


settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger = configure_logging(settings)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    logger.info(
        "%s started on %s:%s; upload directory: %s",
        settings.app_name,
        settings.host,
        settings.port,
        settings.upload_dir,
    )
    try:
        yield
    finally:
        logger.info("%s stopped", settings.app_name)
        logging.shutdown()


def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )
    application.include_router(router)
    return application


app = create_app()

