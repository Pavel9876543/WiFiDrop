from typing import Annotated

from fastapi import APIRouter, Depends, File, Request, UploadFile, status

from app.api.dependencies import get_upload_manager
from app.api.schemas import ErrorResponse, StoredFileResponse, UploadResponse
from app.services.upload_manager import UploadManager


router = APIRouter(prefix="/api/uploads", tags=["uploads"])


@router.post(
    "",
    response_model=UploadResponse,
    status_code=status.HTTP_201_CREATED,
    responses={400: {"model": ErrorResponse}, 413: {"model": ErrorResponse}},
)
async def upload_file(
    request: Request,
    file: Annotated[UploadFile, File(...)],
    manager: Annotated[UploadManager, Depends(get_upload_manager)],
) -> UploadResponse:
    client_ip = request.client.host if request.client else "unknown"
    try:
        stored = await manager.store(file, client_ip)
    finally:
        await file.close()

    return UploadResponse(
        file=StoredFileResponse(
            original_name=stored.original_name,
            saved_name=stored.saved_name,
            category=stored.category.value,
            size=stored.size,
            relative_path=stored.relative_path.as_posix(),
        )
    )

