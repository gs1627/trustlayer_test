from fastapi import HTTPException, UploadFile

from app.core.config import get_settings


ALLOWED_CONTENT_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/flac",
    "audio/ogg",
    "audio/webm",
    "audio/aiff",
    "application/octet-stream",
}


async def read_audio(file: UploadFile) -> bytes:
    settings = get_settings()
    normalized_type = (
        (file.content_type or "application/octet-stream")
        .split(";", 1)[0]
        .strip()
        .lower()
    )
    if normalized_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported audio content type")
    content = await file.read(settings.max_upload_bytes + 1)
    if not content:
        raise HTTPException(status_code=400, detail="The uploaded audio file is empty")
    if len(content) > settings.max_upload_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"Audio exceeds the application limit of {settings.max_upload_mb} MB",
        )
    return content
