from fastapi import APIRouter

from app.api.routes.health import router as health_router
from app.api.routes.pages import router as pages_router
from app.api.routes.uploads import router as uploads_router

router = APIRouter()
router.include_router(pages_router)
router.include_router(health_router)
router.include_router(uploads_router)
