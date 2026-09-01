"""Small HTTP listener used for OS captive-portal probes on TCP port 80."""

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

from app.api.routes.captive_portal import _portal_url, router


def create_captive_app() -> FastAPI:
    application = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    application.include_router(router)

    @application.get("/{path:path}", include_in_schema=False)
    async def fallback(request: Request, path: str) -> RedirectResponse:
        del path
        return RedirectResponse(
            _portal_url(request),
            status_code=302,
            headers={"Cache-Control": "no-store"},
        )

    return application


app = create_captive_app()
