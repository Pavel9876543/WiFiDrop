from pydantic import BaseModel, Field


class StoredFileResponse(BaseModel):
    original_name: str
    saved_name: str
    category: str
    size: int = Field(ge=1)
    relative_path: str


class UploadResponse(BaseModel):
    success: bool = True
    message: str = "Файл успешно загружен."
    file: StoredFileResponse


class ErrorResponse(BaseModel):
    success: bool = False
    error: str
    message: str

