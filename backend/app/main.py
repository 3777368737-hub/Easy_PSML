from __future__ import annotations

import logging
import re
import uuid
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Request,
    UploadFile,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.errors import AppError, InputError
from app.rate_limit import model_rate_limiter
from app.schemas import (
    BatchCreateRequest,
    BatchResponse,
    DeleteHistoryResponse,
    DraftRequest,
    DraftResponse,
    HealthResponse,
    HistoryItem,
    OutlineRequest,
    OutlineResponse,
    ProfileResponse,
    ProgramAnalyzeRequest,
    ProgramAnalyzeResponse,
    ReviewRequest,
    ReviewResponse,
    SessionSnapshotResponse,
    StoryReplyRequest,
    StoryResponse,
    StoryStartRequest,
)
from app.services.resume_parser import extract_resume_text
from app.services.batch import create_batch, retry_batch, start_worker, stop_worker
from app.services.store import get_store
from app.services.workflow import (
    analyze_program,
    continue_story_session,
    extract_profile_from_input,
    generate_draft,
    generate_outline,
    review_draft,
    start_story_session,
)


logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_worker()
    try:
        yield
    finally:
        await stop_worker()


app = FastAPI(title="GradPilot Backend", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-Id", "X-Request-Id"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.message,
            "code": exc.code,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "loc": ".".join(str(part) for part in error["loc"]),
            "msg": error["msg"],
            "type": error["type"],
        }
        for error in exc.errors()[:10]
    ]
    return JSONResponse(
        status_code=422,
        content={
            "detail": "Request validation failed",
            "code": "request_validation_failed",
            "errors": errors,
            "request_id": getattr(request.state, "request_id", ""),
        },
    )


@app.exception_handler(Exception)
async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "")
    logger.exception("Unhandled request error: request_id=%s", request_id)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "code": "internal_error",
            "request_id": request_id,
        },
    )


def get_owner_id(
    x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
) -> str:
    if not x_client_id:
        raise InputError(
            "X-Client-Id header is required",
            code="client_id_required",
        )
    owner_id = x_client_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", owner_id):
        raise InputError("X-Client-Id header is invalid", code="client_id_invalid")
    return owner_id


def enforce_model_rate_limit(owner_id: str = Depends(get_owner_id)) -> str:
    model_rate_limiter.check(owner_id)
    return owner_id


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    get_store().healthcheck()
    return HealthResponse(ok=True, database="ok", version="1.1.0")


@app.post("/api/profile/extract", response_model=ProfileResponse)
async def profile_extract(
    full_name: str = Form("", max_length=120),
    current_university: str = Form("", max_length=200),
    major: str = Form("", max_length=200),
    gpa: str = Form("", max_length=80),
    graduation_year: str = Form("", max_length=40),
    english_test_score: str = Form("", max_length=160),
    target_degree: str = Form("Master's", max_length=120),
    target_field: str = Form("", max_length=200),
    target_country: str = Form("", max_length=160),
    research_experience: str = Form("", max_length=12000),
    internship_experience: str = Form("", max_length=12000),
    project_experience: str = Form("", max_length=12000),
    activities_awards: str = Form("", max_length=12000),
    motivation_text: str = Form("", max_length=12000),
    career_goal: str = Form("", max_length=4000),
    strict_profile: bool = Form(False),
    resume_file: Optional[UploadFile] = File(default=None),
    owner_id: str = Depends(enforce_model_rate_limit),
) -> ProfileResponse:
    resume_text = ""
    if resume_file is not None:
        filename = resume_file.filename or ""
        content = await resume_file.read(settings.max_upload_bytes + 1)
        if len(content) > settings.max_upload_bytes:
            raise InputError(
                f"Resume exceeds the {settings.max_upload_bytes}-byte limit",
                status_code=413,
                code="resume_too_large",
            )
        resume_text = await run_in_threadpool(extract_resume_text, filename, content)

    payload = {
        "full_name": full_name.strip(),
        "current_university": current_university.strip(),
        "major": major.strip(),
        "gpa": gpa.strip(),
        "graduation_year": graduation_year.strip(),
        "english_test_score": english_test_score.strip(),
        "target_degree": target_degree.strip() or "Master's",
        "target_field": target_field.strip(),
        "target_country": target_country.strip(),
        "research_experience": research_experience.strip(),
        "internship_experience": internship_experience.strip(),
        "project_experience": project_experience.strip(),
        "activities_awards": activities_awards.strip(),
        "motivation_text": motivation_text.strip(),
        "career_goal": career_goal.strip(),
        "resume_text": resume_text,
    }
    if strict_profile:
        required_fields = {
            "full_name": "full name",
            "current_university": "current university",
            "major": "major",
            "target_degree": "target degree",
            "target_field": "target field",
            "target_country": "target country",
        }
        missing = [
            label
            for field, label in required_fields.items()
            if not str(payload.get(field) or "").strip()
        ]
        if missing:
            raise InputError(
                "Missing required profile fields: " + ", ".join(missing),
                code="required_profile_fields_missing",
            )
        has_experience = any(
            str(payload.get(field) or "").strip()
            for field in (
                "research_experience",
                "internship_experience",
                "project_experience",
                "activities_awards",
            )
        )
        if not resume_text and not has_experience:
            raise InputError(
                "Upload a resume or enter at least one experience",
                code="profile_experience_required",
            )
    if not resume_text and not any(
        value
        for key, value in payload.items()
        if key not in {"target_degree", "resume_text"}
    ):
        raise InputError(
            "Upload a resume or enter at least one background field",
            code="profile_input_empty",
        )

    record = await extract_profile_from_input(owner_id, payload)
    return ProfileResponse(profile_id=record.id, profile=record.profile)


@app.post("/api/program/analyze", response_model=ProgramAnalyzeResponse)
async def program_analyze(
    request: ProgramAnalyzeRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> ProgramAnalyzeResponse:
    return await analyze_program(owner_id, request)


@app.post("/api/story/start", response_model=StoryResponse)
async def story_start(
    request: StoryStartRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StoryResponse:
    return await start_story_session(
        owner_id,
        request.profile_id,
        request.analysis_id,
    )


@app.post("/api/story/reply", response_model=StoryResponse)
async def story_reply(
    request: StoryReplyRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StoryResponse:
    return await continue_story_session(
        owner_id,
        request.session_id,
        request.user_message,
    )


@app.post("/api/essay/outline", response_model=OutlineResponse)
async def essay_outline(
    request: OutlineRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> OutlineResponse:
    return await generate_outline(owner_id, request.session_id)


@app.post("/api/essay/draft", response_model=DraftResponse)
async def essay_draft(
    request: DraftRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> DraftResponse:
    return await generate_draft(owner_id, request)


@app.post("/api/review/run", response_model=ReviewResponse)
async def review_run(
    request: ReviewRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> ReviewResponse:
    return await review_draft(owner_id, request.session_id)


@app.get("/api/session/{session_id}", response_model=SessionSnapshotResponse)
async def session_snapshot(
    session_id: str,
    owner_id: str = Depends(get_owner_id),
) -> SessionSnapshotResponse:
    return get_store().session_snapshot(session_id, owner_id)


@app.get("/api/history", response_model=List[HistoryItem])
async def history(
    owner_id: str = Depends(get_owner_id),
) -> List[HistoryItem]:
    return get_store().list_history(owner_id)


@app.post("/api/batches", response_model=BatchResponse, status_code=202)
async def batch_create(
    request: BatchCreateRequest,
    owner_id: str = Depends(get_owner_id),
) -> BatchResponse:
    return create_batch(owner_id, request)


@app.get("/api/batches", response_model=List[BatchResponse])
async def batch_list(
    owner_id: str = Depends(get_owner_id),
) -> List[BatchResponse]:
    return get_store().list_batches(owner_id)


@app.get("/api/batches/{batch_id}", response_model=BatchResponse)
async def batch_snapshot(
    batch_id: str,
    owner_id: str = Depends(get_owner_id),
) -> BatchResponse:
    return get_store().batch_snapshot(batch_id, owner_id)


@app.post("/api/batches/{batch_id}/retry", response_model=BatchResponse, status_code=202)
async def batch_retry(
    batch_id: str,
    owner_id: str = Depends(get_owner_id),
) -> BatchResponse:
    return retry_batch(owner_id, batch_id)


@app.delete("/api/history", response_model=DeleteHistoryResponse)
async def clear_history(
    owner_id: str = Depends(get_owner_id),
) -> DeleteHistoryResponse:
    return DeleteHistoryResponse(deleted=get_store().delete_history(owner_id))
