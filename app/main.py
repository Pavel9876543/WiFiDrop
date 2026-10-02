import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_exception_handlers
from app.api.router import router
from app.config.settings import PROJECT_ROOT, get_settings
from app.core.logging import configure_logging
from app.services.router_access import RouterAccess
from app.services.upload_cleanup import remove_orphaned_uploads
from app.services.upload_gate import UploadCapacityMiddleware

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger = configure_logging(settings)
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    remove_orphaned_uploads(settings.upload_dir)
    logger.info(
        "%s started on %s:%s; upload directory: %s",
        settings.app_name,
        settings.host,
        settings.port,
        settings.upload_dir,
    )
    access = RouterAccess(settings) if settings.connection_mode == "router" else None
    try:
        if access is not None:
            await asyncio.to_thread(access.start)
        yield
    finally:
        if access is not None:
            await asyncio.to_thread(access.close)
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
    application.add_middleware(
        UploadCapacityMiddleware,
        max_concurrent_uploads=settings.max_concurrent_uploads,
        retry_after_seconds=settings.upload_busy_retry_after_seconds,
    )
    register_exception_handlers(application)
    application.include_router(router)
    application.mount(
        "/static",
        StaticFiles(directory=PROJECT_ROOT / "app" / "static"),
        name="static",
    )
    return application


app = create_app()
