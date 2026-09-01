from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config.settings import PROJECT_ROOT, get_settings

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=PROJECT_ROOT / "app" / "templates")


@router.get("/", response_class=HTMLResponse)
async def home(request: Request) -> HTMLResponse:
    settings = get_settings()
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={
            "app_name": settings.app_name,
            "max_file_size_mb": settings.max_file_size_mb,
        },
    )


@router.get("/service-worker.js", response_class=FileResponse)
async def service_worker() -> FileResponse:
    return FileResponse(
        PROJECT_ROOT / "app" / "static" / "js" / "service-worker.js",
        media_type="application/javascript",
        headers={
            "Cache-Control": "no-cache",
            "Service-Worker-Allowed": "/",
        },
    )
