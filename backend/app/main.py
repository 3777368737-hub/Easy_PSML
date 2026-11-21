from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from contextlib import asynccontextmanager
from typing import AsyncIterator, List, Optional

from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from app.config import get_settings
from app.errors import AppError, ConflictError, InputError
from app.rate_limit import model_rate_limiter
from app.schemas import (
    AgentActionCancelResponse,
    AgentActionCommitRequest,
    AgentActionCommitResponse,
    AgentCapabilityCall,
    AgentCommandResponse,
    AgentConversationMessage,
    AgentPageContext,
    AgentPendingAction,
    AgentTextCommandRequest,
    ApplicationProjectCreateRequest,
    ApplicationProjectPatchRequest,
    ApplicationProjectResponse,
    BackgroundInstanceResponse,
    BackgroundPatchRequest,
    BackgroundRenameRequest,
    BatchCreateRequest,
    BatchResponse,
    DeleteHistoryResponse,
    DomainAgentRequest,
    DomainCommandResponse,
    DraftRequest,
    DraftResponse,
    EssayProjectCreateRequest,
    EssayBranchCreateRequest,
    EssayProjectDraftRequest,
    EssayProjectPatchRequest,
    EssayProjectResponse,
    HealthResponse,
    HistoryItem,
    OutlineRequest,
    OutlineResponse,
    PersonCreateRequest,
    PersonResponse,
    ProfileResponse,
    ProgramAnalyzeRequest,
    ProgramAnalyzeResponse,
    ReviewRequest,
    ReviewResponse,
    SessionSnapshotResponse,
    StoryInstanceReplyRequest,
    StoryInstancePatchRequest,
    StoryInstanceResponse,
    StoryInstanceStartRequest,
    StoryReplyRequest,
    StoryResponse,
    StoryStartRequest,
    WorkspaceSnapshotResponse,
)
from app.services.agent import (
    pending_action_schema,
    run_agent_command,
    stream_agent_command,
    transcribe_audio,
    transcribe_audio_stream,
)
from app.services.agent_capabilities import validate_capability
from app.services.resume_parser import extract_resume_text
from app.services.realtime_asr import run_realtime_asr_session
from app.services.batch import create_batch, retry_batch, start_worker, stop_worker
from app.services.domain_store import get_domain_store
from app.services import domain_agent
from app.services import domain_workflow
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
SUPPORTED_AUDIO_TYPES = {
    "audio/aac",
    "audio/aiff",
    "audio/amr",
    "audio/flac",
    "audio/mp3",
    "audio/mp4",
    "audio/mpeg",
    "audio/ogg",
    "audio/opus",
    "audio/wav",
    "audio/webm",
    "audio/x-m4a",
    "audio/x-wav",
    "video/mp4",
    "video/webm",
}
AUDIO_SUFFIX_TYPES = {
    "aac": "audio/aac",
    "aiff": "audio/aiff",
    "amr": "audio/amr",
    "flac": "audio/flac",
    "m4a": "audio/x-m4a",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "mpeg": "audio/mpeg",
    "ogg": "audio/ogg",
    "opus": "audio/opus",
    "wav": "audio/wav",
    "webm": "audio/webm",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_worker()
    get_domain_store().healthcheck()
    try:
        yield
    finally:
        await stop_worker()


app = FastAPI(title="GradPilot Backend", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "X-Client-Id", "X-Request-Id"],
    allow_private_network=True,
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


def validate_owner_id(raw_client_id: Optional[str]) -> str:
    if not raw_client_id:
        raise InputError(
            "X-Client-Id header is required",
            code="client_id_required",
        )
    owner_id = raw_client_id.strip()
    if not re.fullmatch(r"[A-Za-z0-9._:-]{16,128}", owner_id):
        raise InputError("X-Client-Id header is invalid", code="client_id_invalid")
    return owner_id


def get_owner_id(
    x_client_id: Optional[str] = Header(default=None, alias="X-Client-Id"),
) -> str:
    return validate_owner_id(x_client_id)


def enforce_model_rate_limit(owner_id: str = Depends(get_owner_id)) -> str:
    model_rate_limiter.check(owner_id)
    return owner_id


def parse_agent_context(raw_context: str) -> AgentPageContext:
    try:
        return AgentPageContext.model_validate_json(raw_context)
    except ValueError as exc:
        raise InputError(
            "The agent page context is invalid",
            code="agent_context_invalid",
        ) from exc


def parse_agent_history(raw_history: str) -> List[AgentConversationMessage]:
    try:
        value = json.loads(raw_history or "[]")
        return [
            AgentConversationMessage.model_validate(item)
            for item in value[:8]
        ]
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise InputError(
            "The agent history is invalid",
            code="agent_history_invalid",
        ) from exc


def agent_sse_event(event: str, data: object) -> str:
    return (
        f"event: {event}\n"
        f"data: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"
    )


def agent_stream_response(events: AsyncIterator[str]) -> StreamingResponse:
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def send_websocket_error(
    websocket: WebSocket, code: str, message: str
) -> None:
    try:
        await websocket.send_json(
            {
                "type": "asr_error",
                "code": code,
                "message": message,
            }
        )
    except (RuntimeError, WebSocketDisconnect):
        pass


def normalize_audio_type(upload: UploadFile) -> str:
    media_type = (upload.content_type or "").split(";", 1)[0].strip().lower()
    if media_type in SUPPORTED_AUDIO_TYPES:
        return media_type
    filename = upload.filename or ""
    suffix = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if suffix in AUDIO_SUFFIX_TYPES:
        return AUDIO_SUFFIX_TYPES[suffix]
    raise InputError(
        "Unsupported voice recording format",
        code="voice_audio_format_unsupported",
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    get_store().healthcheck()
    get_domain_store().healthcheck()
    return HealthResponse(ok=True, database="ok", version="1.1.0")


@app.get("/api/workspace", response_model=WorkspaceSnapshotResponse)
async def workspace_snapshot(
    owner_id: str = Depends(get_owner_id),
) -> WorkspaceSnapshotResponse:
    return get_domain_store().workspace_snapshot(owner_id)


@app.post("/api/persons", response_model=PersonResponse, status_code=201)
async def create_person(
    request: PersonCreateRequest,
    owner_id: str = Depends(get_owner_id),
) -> PersonResponse:
    return get_domain_store().create_person(
        owner_id,
        request.display_name,
        request.aliases,
    )


@app.get("/api/persons", response_model=List[PersonResponse])
async def list_persons(
    owner_id: str = Depends(get_owner_id),
) -> List[PersonResponse]:
    return get_domain_store().list_persons(owner_id)


@app.get("/api/persons/{person_id}", response_model=PersonResponse)
async def get_person(
    person_id: str,
    owner_id: str = Depends(get_owner_id),
) -> PersonResponse:
    return get_domain_store().get_person(owner_id, person_id)


@app.post(
    "/api/application-projects",
    response_model=ApplicationProjectResponse,
    status_code=201,
)
async def create_application_project(
    request: ApplicationProjectCreateRequest,
    owner_id: str = Depends(get_owner_id),
) -> ApplicationProjectResponse:
    return get_domain_store().create_application_project(
        owner_id,
        request.background_instance_id,
        request.school_name,
        request.program_name,
        request.program_details,
    )


@app.get(
    "/api/application-projects",
    response_model=List[ApplicationProjectResponse],
)
async def list_application_projects(
    owner_id: str = Depends(get_owner_id),
) -> List[ApplicationProjectResponse]:
    return get_domain_store().list_application_projects(owner_id)


@app.get(
    "/api/application-projects/{project_id}",
    response_model=ApplicationProjectResponse,
)
async def get_application_project(
    project_id: str,
    owner_id: str = Depends(get_owner_id),
) -> ApplicationProjectResponse:
    return get_domain_store().get_application_project(owner_id, project_id)


@app.patch(
    "/api/application-projects/{project_id}",
    response_model=ApplicationProjectResponse,
)
async def patch_application_project(
    project_id: str,
    request: ApplicationProjectPatchRequest,
    owner_id: str = Depends(get_owner_id),
) -> ApplicationProjectResponse:
    return get_domain_store().patch_application_project(
        owner_id,
        project_id,
        school_name=request.school_name,
        program_name=request.program_name,
        program_details=request.program_details,
    )


@app.post(
    "/api/application-projects/{project_id}/essays",
    response_model=EssayProjectResponse,
    status_code=201,
)
async def create_application_essay(
    project_id: str,
    request: EssayBranchCreateRequest,
    owner_id: str = Depends(get_owner_id),
) -> EssayProjectResponse:
    if project_id != request.application_project_id:
        raise InputError("Application project path and body do not match")
    return await domain_workflow.create_application_essay_branch(
        owner_id,
        request,
    )


@app.patch(
    "/api/backgrounds/{background_id}",
    response_model=BackgroundInstanceResponse,
)
async def rename_background(
    background_id: str,
    request: BackgroundRenameRequest,
    owner_id: str = Depends(get_owner_id),
) -> BackgroundInstanceResponse:
    return get_domain_store().rename_background(
        owner_id,
        background_id,
        request.resume_name,
    )


@app.patch(
    "/api/backgrounds/{background_id}/profile",
    response_model=BackgroundInstanceResponse,
)
async def patch_background_profile(
    background_id: str,
    request: BackgroundPatchRequest,
    owner_id: str = Depends(get_owner_id),
) -> BackgroundInstanceResponse:
    return get_domain_store().patch_background(
        owner_id,
        background_id,
        request.operations,
        base_version=request.base_version,
    )


@app.get("/api/backgrounds/{background_id}/resume")
async def download_background_resume(
    background_id: str,
    owner_id: str = Depends(get_owner_id),
) -> FileResponse:
    path, filename = get_domain_store().get_resume_file(
        owner_id,
        background_id,
    )
    return FileResponse(path, filename=filename)


@app.post(
    "/api/story-instances/start",
    response_model=StoryInstanceResponse,
    status_code=201,
)
async def start_story_instance(
    request: StoryInstanceStartRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StoryInstanceResponse:
    return await domain_workflow.start_story(owner_id, request)


@app.get(
    "/api/story-instances/{story_id}",
    response_model=StoryInstanceResponse,
)
async def get_story_instance(
    story_id: str,
    owner_id: str = Depends(get_owner_id),
) -> StoryInstanceResponse:
    return get_domain_store().get_story(owner_id, story_id)


@app.post(
    "/api/story-instances/{story_id}/reply",
    response_model=StoryInstanceResponse,
)
async def reply_story_instance(
    story_id: str,
    request: StoryInstanceReplyRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StoryInstanceResponse:
    return await domain_workflow.continue_story(owner_id, story_id, request)


@app.patch(
    "/api/story-instances/{story_id}",
    response_model=StoryInstanceResponse,
)
async def patch_story_instance(
    story_id: str,
    request: StoryInstancePatchRequest,
    owner_id: str = Depends(get_owner_id),
) -> StoryInstanceResponse:
    return get_domain_store().patch_story_cards(
        owner_id,
        story_id,
        request.cards,
        base_version=request.base_version,
    )


@app.post(
    "/api/essay-projects",
    response_model=EssayProjectResponse,
    status_code=201,
)
async def create_essay_project(
    request: EssayProjectCreateRequest,
    owner_id: str = Depends(get_owner_id),
) -> EssayProjectResponse:
    return get_domain_store().create_project(
        owner_id,
        request.background_instance_id,
        request.story_instance_ids,
        request.to_program_context(),
    )


@app.get("/api/essay-projects", response_model=List[EssayProjectResponse])
async def list_essay_projects(
    owner_id: str = Depends(get_owner_id),
) -> List[EssayProjectResponse]:
    return get_domain_store().list_projects(owner_id)


@app.get(
    "/api/essay-projects/{project_id}",
    response_model=EssayProjectResponse,
)
async def get_essay_project(
    project_id: str,
    owner_id: str = Depends(get_owner_id),
) -> EssayProjectResponse:
    return get_domain_store().get_project(owner_id, project_id)


@app.patch(
    "/api/essay-projects/{project_id}",
    response_model=EssayProjectResponse,
)
async def patch_essay_project(
    project_id: str,
    request: EssayProjectPatchRequest,
    owner_id: str = Depends(get_owner_id),
) -> EssayProjectResponse:
    return get_domain_store().patch_project(
        owner_id,
        project_id,
        changes=request.model_dump(
            exclude={"story_instance_ids"},
            exclude_none=True,
        ),
        story_instance_ids=request.story_instance_ids,
    )


@app.post(
    "/api/essay-projects/{project_id}/analyze",
    response_model=EssayProjectResponse,
)
async def analyze_essay_project(
    project_id: str,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> EssayProjectResponse:
    return await domain_workflow.analyze_project(owner_id, project_id)


@app.post(
    "/api/essay-projects/{project_id}/outline",
    response_model=EssayProjectResponse,
)
async def outline_essay_project(
    project_id: str,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> EssayProjectResponse:
    return await domain_workflow.generate_outline(owner_id, project_id)


@app.post(
    "/api/essay-projects/{project_id}/draft",
    response_model=EssayProjectResponse,
)
async def draft_essay_project(
    project_id: str,
    request: EssayProjectDraftRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> EssayProjectResponse:
    return await domain_workflow.generate_draft(owner_id, project_id, request)


@app.post(
    "/api/essay-projects/{project_id}/review",
    response_model=EssayProjectResponse,
)
async def review_essay_project(
    project_id: str,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> EssayProjectResponse:
    return await domain_workflow.review_project(owner_id, project_id)


@app.post("/api/agent/text", response_model=AgentCommandResponse)
async def agent_text_command(
    request: AgentTextCommandRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> AgentCommandResponse:
    return await run_agent_command(
        owner_id,
        request.transcript,
        request.context,
        request.history,
        source=request.source,
    )


@app.post("/api/agent/domain", response_model=DomainCommandResponse)
async def agent_domain_command(
    request: DomainAgentRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> DomainCommandResponse:
    return await domain_agent.run_domain_command(owner_id, request)


@app.post("/api/agent/text/stream")
async def agent_text_command_stream(
    request: AgentTextCommandRequest,
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StreamingResponse:
    async def events() -> AsyncIterator[str]:
        try:
            async for event, payload in stream_agent_command(
                owner_id,
                request.transcript,
                request.context,
                request.history,
                source=request.source,
            ):
                if event == "final":
                    payload = payload.model_dump(mode="json")
                yield agent_sse_event(event, payload or {})
        except AppError as exc:
            yield agent_sse_event(
                "error",
                {
                    "message": exc.message,
                    "code": exc.code,
                    "status": exc.status_code,
                },
            )
        except Exception:
            logger.exception("Streaming text agent request failed")
            yield agent_sse_event(
                "error",
                {
                    "message": "The voice agent failed",
                    "code": "internal_error",
                    "status": 500,
                },
            )

    return agent_stream_response(events())


@app.post("/api/agent/voice", response_model=AgentCommandResponse)
async def agent_voice_command(
    audio: UploadFile = File(...),
    context: str = Form(..., max_length=200000),
    history: str = Form("[]", max_length=20000),
    owner_id: str = Depends(enforce_model_rate_limit),
) -> AgentCommandResponse:
    page_context = parse_agent_context(context)
    conversation = parse_agent_history(history)
    media_type = normalize_audio_type(audio)
    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise InputError("The voice recording is empty", code="voice_audio_empty")
    if len(content) > settings.voice_max_audio_bytes:
        raise InputError(
            "The voice recording is too large",
            status_code=413,
            code="voice_audio_too_large",
        )
    transcript = await transcribe_audio(content, media_type)
    return await run_agent_command(
        owner_id,
        transcript,
        page_context,
        conversation,
        source="voice",
    )


@app.post("/api/agent/voice/stream")
async def agent_voice_command_stream(
    audio: UploadFile = File(...),
    context: str = Form(..., max_length=200000),
    history: str = Form("[]", max_length=20000),
    owner_id: str = Depends(enforce_model_rate_limit),
) -> StreamingResponse:
    page_context = parse_agent_context(context)
    conversation = parse_agent_history(history)
    media_type = normalize_audio_type(audio)
    content = await audio.read(settings.voice_max_audio_bytes + 1)
    if not content:
        raise InputError("The voice recording is empty", code="voice_audio_empty")
    if len(content) > settings.voice_max_audio_bytes:
        raise InputError(
            "The voice recording is too large",
            status_code=413,
            code="voice_audio_too_large",
        )

    async def events() -> AsyncIterator[str]:
        transcript_parts: List[str] = []
        try:
            async for delta in transcribe_audio_stream(content, media_type):
                transcript_parts.append(delta)
                yield agent_sse_event("transcript_delta", {"text": delta})
            transcript = "".join(transcript_parts).strip()
            if not transcript:
                raise InputError(
                    "The voice transcript is empty",
                    code="voice_transcript_empty",
                )
            async for event, payload in stream_agent_command(
                owner_id,
                transcript,
                page_context,
                conversation,
                source="voice",
            ):
                if event == "final":
                    payload = payload.model_dump(mode="json")
                yield agent_sse_event(event, payload or {})
        except AppError as exc:
            yield agent_sse_event(
                "error",
                {
                    "message": exc.message,
                    "code": exc.code,
                    "status": exc.status_code,
                },
            )
        except Exception:
            logger.exception("Streaming voice agent request failed")
            yield agent_sse_event(
                "error",
                {
                    "message": "The voice agent failed",
                    "code": "internal_error",
                    "status": 500,
                },
            )

    return agent_stream_response(events())


@app.post(
    "/api/agent/actions/{action_id}/commit",
    response_model=AgentActionCommitResponse,
)
async def agent_action_commit(
    action_id: str,
    request: AgentActionCommitRequest,
    owner_id: str = Depends(get_owner_id),
) -> AgentActionCommitResponse:
    store = get_store()
    pending = store.get_pending_agent_action(owner_id, action_id)
    if pending is None:
        raise InputError(
            "The pending action was not found or expired",
            status_code=404,
            code="agent_action_not_found",
        )
    if pending.status != "prepared":
        raise ConflictError("The pending action still requires more information")
    call = AgentCapabilityCall(
        name=pending.capability,
        arguments=pending.arguments,
    )
    missing = validate_capability(
        owner_id,
        request.context,
        call,
        store=store,
    )
    if missing:
        store.upsert_pending_agent_action(
            owner_id,
            pending.capability,
            pending.arguments,
            [item.model_dump(mode="json") for item in missing],
            "collecting",
            pending.summary,
            action_id=action_id,
        )
        return AgentActionCommitResponse(
            action_id=action_id,
            capability=pending.capability,
            arguments=pending.arguments,
            status="needs_input",
            missing_fields=missing,
        )
    store.mark_pending_agent_action_committed(owner_id, action_id)
    return AgentActionCommitResponse(
        action_id=action_id,
        capability=pending.capability,
        arguments=pending.arguments,
    )


@app.get(
    "/api/agent/actions/current",
    response_model=Optional[AgentPendingAction],
)
async def agent_action_current(
    owner_id: str = Depends(get_owner_id),
) -> Optional[AgentPendingAction]:
    pending = get_store().get_pending_agent_action(owner_id)
    return pending_action_schema(pending) if pending else None


@app.delete(
    "/api/agent/actions/{action_id}",
    response_model=AgentActionCancelResponse,
)
async def agent_action_cancel(
    action_id: str,
    owner_id: str = Depends(get_owner_id),
) -> AgentActionCancelResponse:
    return AgentActionCancelResponse(
        cancelled=get_store().cancel_pending_agent_action(owner_id, action_id)
    )


@app.websocket("/api/agent/voice/realtime")
async def agent_voice_realtime(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        owner_id = validate_owner_id(websocket.query_params.get("client_id"))
        model_rate_limiter.check(owner_id)
        start_message = await asyncio.wait_for(websocket.receive_json(), timeout=10)
        if not isinstance(start_message, dict) or start_message.get("type") != "start":
            raise InputError("Realtime voice session start is invalid")
        context = AgentPageContext.model_validate(start_message.get("context"))
        history = [
            AgentConversationMessage.model_validate(item)
            for item in (start_message.get("history") or [])[:8]
        ]
        sample_rate = int(start_message.get("sample_rate") or 16000)
        if sample_rate < 8000 or sample_rate > 48000:
            raise InputError("Realtime voice sample rate is unsupported")
        await run_realtime_asr_session(
            websocket,
            context,
            history,
            sample_rate,
        )
    except asyncio.TimeoutError:
        await send_websocket_error(
            websocket,
            "voice_session_timeout",
            "Realtime voice session did not start",
        )
    except (AppError, ValueError) as exc:
        code = exc.code if isinstance(exc, AppError) else "invalid_input"
        message = exc.message if isinstance(exc, AppError) else str(exc)
        await send_websocket_error(websocket, code, message)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except (RuntimeError, WebSocketDisconnect):
            pass


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
    person_id: Optional[str] = Form(default=None, max_length=128),
    resume_name: str = Form("", max_length=160),
    background_instance_id: Optional[str] = Form(default=None, max_length=128),
    resume_file: Optional[UploadFile] = File(default=None),
    owner_id: str = Depends(enforce_model_rate_limit),
) -> ProfileResponse:
    resume_text = ""
    filename = ""
    uploaded_content = b""
    if resume_file is not None:
        filename = resume_file.filename or ""
        uploaded_content = await resume_file.read(settings.max_upload_bytes + 1)
        if len(uploaded_content) > settings.max_upload_bytes:
            raise InputError(
                f"Resume exceeds the {settings.max_upload_bytes}-byte limit",
                status_code=413,
                code="resume_too_large",
            )
        resume_text = await run_in_threadpool(
            extract_resume_text,
            filename,
            uploaded_content,
        )

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
    if background_instance_id:
        background = get_domain_store().save_background_profile(
            owner_id,
            background_instance_id,
            record.profile,
            legacy_profile_id=record.id,
        )
    else:
        background = get_domain_store().ensure_background_for_profile(
            owner_id,
            record.id,
            record.profile,
            person_id=person_id or None,
            resume_name=resume_name or None,
            source_filename=filename,
        )
    if uploaded_content and filename:
        background = get_domain_store().save_resume_file(
            owner_id,
            background.id,
            filename,
            uploaded_content,
        )
    return ProfileResponse(
        profile_id=record.id,
        profile=record.profile,
        person_id=background.person_id,
        background_instance_id=background.id,
        background_version=background.version,
    )


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
    deleted = get_store().delete_history(owner_id)
    get_domain_store().delete_workspace_data(owner_id)
    return DeleteHistoryResponse(deleted=deleted)
