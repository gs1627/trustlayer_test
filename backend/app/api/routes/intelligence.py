from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import TypeAdapter, ValidationError

from app.api.audio import read_audio
from app.core.auth import require_backend_access, require_demo_mode
from app.schemas.contracts import EvidenceItem
from app.services.intelligence_pipeline import IntelligencePipeline, PipelineResult
from app.services.normalizer import EvidenceNormalizationError


router = APIRouter(
    prefix="/intelligence",
    tags=["demo intelligence"],
    dependencies=[Depends(require_demo_mode), Depends(require_backend_access)],
)
pipeline = IntelligencePipeline()
voice_evidence_adapter = TypeAdapter(list[EvidenceItem])


@router.post(
    "/analyze",
    response_model=PipelineResult,
    description=(
        "Development-only demo endpoint. Uploaded voice evidence is caller-supplied "
        "and is not trusted proof of identity. Disabled in production."
    ),
)
async def analyze_clip(
    call_id: str = Form(..., min_length=3, max_length=128),
    voice_evidence_json: str = Form(default="[]", max_length=100_000),
    file: UploadFile = File(...),
) -> PipelineResult:
    audio = await read_audio(file)
    try:
        voice_evidence = voice_evidence_adapter.validate_json(voice_evidence_json)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail="voice_evidence_json must be a JSON array of EvidenceItem objects",
        ) from exc

    if any(item.check_type not in {"deepfake", "speaker_verification"} for item in voice_evidence):
        raise HTTPException(
            status_code=422,
            detail="Only deepfake and speaker_verification evidence may be supplied",
        )

    try:
        return await pipeline.analyze_clip(
            audio,
            call_id=call_id,
            voice_evidence=voice_evidence,
            filename=file.filename or "recording.wav",
            content_type=file.content_type or "application/octet-stream",
        )
    except EvidenceNormalizationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
