import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import WiFiDropError


logger = logging.getLogger("wifidrop.errors")


def register_exception_handlers(application: FastAPI) -> None:
    application.add_exception_handler(WiFiDropError, handle_application_error)
    application.add_exception_handler(RequestValidationError, handle_validation_error)
    application.add_exception_handler(StarletteHTTPException, handle_http_error)
    application.add_exception_handler(Exception, handle_unexpected_error)


async def handle_application_error(request: Request, error: WiFiDropError) -> JSONResponse:
    logger.warning(
        "Request failed | client=%s | path=%s | code=%s | message=%s",
        _client_ip(request),
        request.url.path,
        error.error_code,
        error.message,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={"success": False, "error": error.error_code, "message": error.message},
    )


async def handle_validation_error(request: Request, _: RequestValidationError) -> JSONResponse:
    logger.warning("Invalid request | client=%s | path=%s", _client_ip(request), request.url.path)
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "invalid_request",
            "message": "Запрос повреждён или не содержит файл.",
        },
    )


async def handle_http_error(request: Request, error: StarletteHTTPException) -> JSONResponse:
    message = "Запрашиваемый ресурс не найден." if error.status_code == 404 else "Ошибка запроса."
    logger.warning(
        "HTTP error | client=%s | path=%s | status=%s",
        _client_ip(request),
        request.url.path,
        error.status_code,
    )
    return JSONResponse(
        status_code=error.status_code,
        content={"success": False, "error": "http_error", "message": message},
    )


async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
    logger.exception(
        "Unexpected error | client=%s | path=%s", _client_ip(request), request.url.path,
        exc_info=error,
    )
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "internal_error",
            "message": "Внутренняя ошибка сервера. Попробуйте загрузить файл ещё раз.",
        },
    )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

