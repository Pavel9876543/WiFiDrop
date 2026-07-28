import asyncio
import logging

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger("wifidrop.uploads")


class UploadGate:
    """Tracks upload capacity without making excess requests wait in memory."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            raise ValueError("Upload capacity must be at least one.")
        self._capacity = capacity
        self._active = 0
        self._state_lock = asyncio.Lock()

    async def try_acquire(self) -> bool:
        async with self._state_lock:
            if self._active >= self._capacity:
                return False
            self._active += 1
            return True

    async def release(self) -> None:
        async with self._state_lock:
            if self._active == 0:
                raise RuntimeError("Cannot release an upload slot that is not acquired.")
            self._active -= 1


class UploadCapacityMiddleware:
    def __init__(
        self,
        app: ASGIApp,
        max_concurrent_uploads: int,
        retry_after_seconds: int,
    ) -> None:
        self._app = app
        self._gate = UploadGate(max_concurrent_uploads)
        self._retry_after_seconds = retry_after_seconds

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._is_upload_request(scope):
            await self._app(scope, receive, send)
            return

        if not await self._gate.try_acquire():
            client = scope.get("client")
            client_ip = client[0] if client else "unknown"
            logger.warning("Upload rejected because server is busy | client=%s", client_ip)
            response = JSONResponse(
                status_code=503,
                headers={"Retry-After": str(self._retry_after_seconds)},
                content={
                    "success": False,
                    "error": "server_busy",
                    "message": (
                        "Сервер занят другой загрузкой. Подождите немного "
                        "и повторите отправку позже."
                    ),
                },
            )
            await response(scope, receive, send)
            return

        try:
            await self._app(scope, receive, send)
        finally:
            await asyncio.shield(self._gate.release())

    @staticmethod
    def _is_upload_request(scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope.get("method") == "POST"
            and scope.get("path") == "/api/uploads"
        )
