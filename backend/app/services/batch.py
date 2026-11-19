from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from typing import Optional

from app.errors import AppError, NotFoundError
from app.rate_limit import model_rate_limiter
from app.schemas import (
    BatchCreateRequest,
    BatchResponse,
    DraftRequest,
    ProgramAnalyzeRequest,
    StoryCards,
    StoryMessage,
)
from app.services import workflow
from app.services.store import get_store


logger = logging.getLogger(__name__)
_worker_task: Optional[asyncio.Task] = None
_wake_event: Optional[asyncio.Event] = None


def _wake_worker() -> None:
    if _wake_event is not None:
        _wake_event.set()


def create_batch(owner_id: str, request: BatchCreateRequest) -> BatchResponse:
    batch = get_store().create_batch(owner_id, request)
    _wake_worker()
    return batch


def retry_batch(owner_id: str, batch_id: str) -> BatchResponse:
    batch = get_store().retry_batch(batch_id, owner_id)
    _wake_worker()
    return batch


async def _process_item(owner_id: str, batch: BatchResponse, item_id: str) -> None:
    store = get_store()
    state = store.batch_item_state(batch.id, item_id, owner_id)
    if state["status"] != "pending":
        return
    item = next(item for item in batch.items if item.id == item_id)
    store.update_batch_item(
        batch.id, item_id, owner_id, status="running", error_code=None, error_message=None,
    )

    analysis_id = state["analysis_id"]
    if not analysis_id:
        store.update_batch_item(batch.id, item_id, owner_id, stage="analysis")
        model_rate_limiter.check(owner_id)
        analysis = await workflow.analyze_program(
            owner_id,
            ProgramAnalyzeRequest(profile_id=batch.profile_id, **item.program.model_dump()),
        )
        analysis_id = analysis.analysis_id
        store.update_batch_item(batch.id, item_id, owner_id, analysis_id=analysis_id)

    session_id = state["session_id"]
    if not session_id:
        # Batch mode uses the complete supplied profile as evidence. Empty cards
        # avoid both fabricated interview answers and lossy profile summaries.
        # The existing outline/draft workflow receives that full profile.
        session = store.create_session(
            owner_id=owner_id,
            profile_id=batch.profile_id,
            analysis_id=analysis_id,
            messages=[StoryMessage(
                role="assistant",
                content="批量生成：直接使用已录入的个人资料，未进行故事访谈。",
            )],
            cards=StoryCards(),
            round_no=1,
            status="ready",
        )
        session_id = session.id
        store.update_batch_item(batch.id, item_id, owner_id, session_id=session_id)

    session = store.require_session(session_id, owner_id)
    if session.outline is None or not session.draft:
        # The original workflow saves immutable artifacts before updating the
        # session snapshot. Recover that commit if the process stopped between
        # those writes, instead of buying the same model output again.
        restored = False
        for artifact in reversed(store.list_artifacts(session_id, owner_id)):
            if session.outline is None and artifact.outline is not None:
                session.outline = artifact.outline
                restored = True
            if not session.draft and artifact.draft:
                session.draft = artifact.draft
                restored = True
        if restored:
            session = store.save_session(session)
    if session.outline is None:
        store.update_batch_item(batch.id, item_id, owner_id, stage="outline")
        model_rate_limiter.check(owner_id)
        await workflow.generate_outline(owner_id, session_id)

    session = store.require_session(session_id, owner_id)
    if not session.draft:
        store.update_batch_item(batch.id, item_id, owner_id, stage="draft")
        model_rate_limiter.check(owner_id)
        await workflow.generate_draft(
            owner_id,
            DraftRequest(session_id=session_id, tone=batch.tone),
        )
    store.update_batch_item(batch.id, item_id, owner_id, status="completed", stage="completed")


async def process_batch(owner_id: str, batch_id: str) -> None:
    """Atomically claim and run a persisted batch; safe to call more than once."""
    store = get_store()
    if not store.claim_batch(batch_id, owner_id):
        return
    batch = store.require_batch(batch_id, owner_id)
    for item in batch.items:
        if item.status != "pending":
            continue
        try:
            await _process_item(owner_id, batch, item.id)
        except Exception as exc:
            if isinstance(exc, NotFoundError) and store.get_batch(batch_id, owner_id) is None:
                # Clearing history removes profiles and all batch rows. Never
                # recreate work that the user has deleted while a model awaited.
                return
            if isinstance(exc, AppError):
                code, message = exc.code, exc.message
            else:
                logger.exception("Batch item failed: batch_id=%s item_id=%s", batch_id, item.id)
                code, message = "internal_error", "Generation failed. Please retry this item."
            try:
                store.update_batch_item(
                    batch_id, item.id, owner_id,
                    status="failed", stage="failed", error_code=code, error_message=message,
                )
            except NotFoundError:
                return
    store.finish_batch(batch_id, owner_id)


async def _worker_loop() -> None:
    needs_recovery = False
    while True:
        # Clear before reading the database so a submission during work cannot
        # be lost between the queue read and the next wait.
        assert _wake_event is not None
        _wake_event.clear()
        try:
            if needs_recovery:
                get_store().recover_batches()
                needs_recovery = False
            pending = get_store().pending_batches()
            if pending:
                for batch_id, owner_id in pending:
                    await process_batch(owner_id, batch_id)
                continue
        except Exception:
            logger.exception("Batch worker could not process queued work")
            # A transient storage failure must not strand a claimed batch until
            # the next server restart. Only this worker executes background work.
            needs_recovery = True
        try:
            await asyncio.wait_for(_wake_event.wait(), timeout=2)
        except asyncio.TimeoutError:
            pass


async def start_worker() -> None:
    global _worker_task, _wake_event
    if _worker_task is not None and not _worker_task.done():
        return
    get_store().recover_batches()
    _wake_event = asyncio.Event()
    _worker_task = asyncio.create_task(_worker_loop(), name="gradpilot-batch-worker")


async def stop_worker() -> None:
    global _worker_task, _wake_event
    if _worker_task is not None:
        _worker_task.cancel()
        with suppress(asyncio.CancelledError):
            await _worker_task
        _worker_task = None
    _wake_event = None
