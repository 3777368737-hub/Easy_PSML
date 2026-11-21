from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

import websockets
from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings, get_settings
from app.errors import UpstreamServiceError
from app.schemas import AgentConversationMessage, AgentPageContext


logger = logging.getLogger(__name__)
REALTIME_ASR_PATH = "/api-ws/v1/inference"
SESSION_FINISH_TIMEOUT_SECONDS = 8


def build_realtime_asr_url(settings: Settings) -> str:
    if settings.qwen_asr_ws_url.strip():
        return settings.qwen_asr_ws_url.strip()

    parsed = urlsplit(settings.qwen_base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, REALTIME_ASR_PATH, "", ""))


def _asr_context_messages(
    context: AgentPageContext,
    history: List[AgentConversationMessage],
) -> List[Dict[str, Any]]:
    domain_terms = [
        context.title,
        *[control.label for control in context.controls[:20]],
        *[step.title for step in context.workflow[:8]],
    ]
    domain_text = "GradPilot 当前页面及字段：" + "、".join(
        dict.fromkeys(term.strip() for term in domain_terms if term.strip())
    )
    messages: List[Dict[str, Any]] = [
        {
            "role": "user",
            "content": [
                {
                    "type": "input_text",
                    "text": domain_text[:400],
                }
            ],
        }
    ]

    for message in history[-4:]:
        if message.role not in {"user", "assistant"}:
            continue
        content_type = "input_text" if message.role == "user" else "text"
        messages.append(
            {
                "role": message.role,
                "content": [
                    {
                        "type": content_type,
                        "text": message.content.strip()[:400],
                    }
                ],
            }
        )
    return messages


def build_run_task_payload(
    task_id: str,
    sample_rate: int,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    settings: Settings,
) -> Dict[str, Any]:
    context_messages = _asr_context_messages(context, history)
    input_payload: Dict[str, Any] = {}
    if context_messages:
        input_payload["context"] = context_messages

    return {
        "header": {
            "action": "run-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {
            "task_group": "audio",
            "task": "asr",
            "function": "recognition",
            "model": settings.qwen_asr_model,
            "parameters": {
                "format": "pcm",
                "sample_rate": sample_rate,
                "vad_model": settings.qwen_asr_vad_model,
                "max_sentence_silence": settings.qwen_asr_max_sentence_silence_ms,
                "multi_threshold_mode_enabled": False,
                "language_hints": [settings.qwen_asr_language],
                "heartbeat": True,
            },
            "input": input_payload,
        },
    }


def build_finish_task_payload(task_id: str) -> Dict[str, Any]:
    return {
        "header": {
            "action": "finish-task",
            "task_id": task_id,
            "streaming": "duplex",
        },
        "payload": {"input": {}},
    }


def extract_sentence_event(message: Dict[str, Any]) -> Dict[str, Any] | None:
    try:
        header = message["header"]
        if header.get("event") != "result-generated":
            return None
        sentence = message["payload"]["output"]["sentence"]
    except (KeyError, TypeError):
        return None

    if sentence.get("heartbeat"):
        return None
    text = str(sentence.get("text") or "")
    if not text and not sentence.get("sentence_begin"):
        return None
    return {
        "type": "transcript",
        "sentence_id": int(sentence.get("sentence_id") or 0),
        "begin_time": sentence.get("begin_time"),
        "end_time": sentence.get("end_time"),
        "text": text,
        "sentence_begin": bool(sentence.get("sentence_begin")),
        "sentence_end": bool(sentence.get("sentence_end")),
    }


async def _send_browser_json(
    browser: WebSocket, payload: Dict[str, Any]
) -> None:
    try:
        await browser.send_json(payload)
    except (RuntimeError, WebSocketDisconnect):
        return


async def _wait_for_task_started(websocket: Any) -> None:
    while True:
        raw = await websocket.recv()
        if isinstance(raw, bytes):
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        header = message.get("header") or {}
        event = header.get("event")
        if event == "task-started":
            return
        if event == "task-failed":
            raise UpstreamServiceError(
                header.get("error_message") or "Qwen realtime ASR task failed",
                code=header.get("error_code") or "qwen_request_rejected",
            )


async def _pump_upstream_to_browser(
    upstream: Any,
    browser: WebSocket,
) -> None:
    while True:
        raw = await upstream.recv()
        if isinstance(raw, bytes):
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError:
            continue
        header = message.get("header") or {}
        event = header.get("event")
        if event == "result-generated":
            sentence_event = extract_sentence_event(message)
            if sentence_event is not None:
                await browser.send_json(sentence_event)
        elif event == "task-finished":
            await _send_browser_json(browser, {"type": "asr_finished"})
            return
        elif event == "task-failed":
            await _send_browser_json(
                browser,
                {
                    "type": "asr_error",
                    "code": header.get("error_code") or "qwen_request_rejected",
                    "message": header.get("error_message")
                    or "Qwen realtime ASR task failed",
                },
            )
            return


async def _pump_browser_to_upstream(
    browser: WebSocket,
    upstream: Any,
    task_id: str,
) -> None:
    while True:
        message = await browser.receive()
        message_type = message.get("type")
        if message_type == "websocket.disconnect":
            try:
                await upstream.send(json.dumps(build_finish_task_payload(task_id)))
            except websockets.WebSocketException:
                pass
            raise WebSocketDisconnect(message.get("code", 1000))
        if message_type == "websocket.receive":
            if message.get("bytes") is not None:
                await upstream.send(message["bytes"])
                continue
            raw_text = message.get("text")
            if not raw_text:
                continue
            try:
                command = json.loads(raw_text)
            except json.JSONDecodeError:
                continue
            if command.get("type") == "stop":
                await _send_browser_json(browser, {"type": "asr_finishing"})
                await upstream.send(json.dumps(build_finish_task_payload(task_id)))
                return


async def run_realtime_asr_session(
    browser: WebSocket,
    context: AgentPageContext,
    history: List[AgentConversationMessage],
    sample_rate: int,
) -> None:
    settings = get_settings()
    if not settings.qwen_api_key:
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": "qwen_not_configured",
                "message": "QWEN_API_KEY is not configured",
            },
        )
        return

    task_id = uuid.uuid4().hex
    upstream_url = build_realtime_asr_url(settings)
    try:
        async with websockets.connect(
            upstream_url,
            additional_headers={
                "Authorization": f"Bearer {settings.qwen_api_key}",
            },
            proxy=None,
            open_timeout=min(15, settings.qwen_timeout_seconds),
            close_timeout=5,
            max_size=None,
        ) as upstream:
            await upstream.send(
                json.dumps(
                    build_run_task_payload(
                        task_id,
                        sample_rate,
                        context,
                        history,
                        settings,
                    ),
                    ensure_ascii=False,
                )
            )
            await asyncio.wait_for(_wait_for_task_started(upstream), timeout=15)
            await _send_browser_json(
                browser,
                {
                    "type": "asr_ready",
                    "sample_rate": sample_rate,
                    "model": settings.qwen_asr_model,
                    "max_sentence_silence_ms": (
                        settings.qwen_asr_max_sentence_silence_ms
                    ),
                },
            )

            browser_task = asyncio.create_task(
                _pump_browser_to_upstream(browser, upstream, task_id)
            )
            upstream_task = asyncio.create_task(
                _pump_upstream_to_browser(upstream, browser)
            )
            done, pending = await asyncio.wait(
                {browser_task, upstream_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            if upstream_task in done:
                browser_task.cancel()
                await asyncio.gather(browser_task, return_exceptions=True)
            else:
                try:
                    await asyncio.wait_for(
                        upstream_task,
                        timeout=SESSION_FINISH_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    upstream_task.cancel()
                    await asyncio.gather(upstream_task, return_exceptions=True)

            for task in pending:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    except WebSocketDisconnect:
        return
    except asyncio.TimeoutError:
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": "qwen_service_unavailable",
                "message": "Qwen realtime ASR startup timed out",
            },
        )
    except websockets.InvalidStatus as exc:
        auth_failed = exc.response.status_code in {401, 403}
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": (
                    "qwen_auth_failed"
                    if auth_failed
                    else "qwen_request_rejected"
                ),
                "message": (
                    "Qwen realtime ASR authentication failed"
                    if auth_failed
                    else "Qwen rejected the realtime ASR connection"
                ),
            },
        )
    except websockets.WebSocketException as exc:
        logger.warning("Qwen realtime ASR connection failed: %s", exc)
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": "qwen_service_unavailable",
                "message": "Could not reach Qwen realtime ASR",
            },
        )
    except UpstreamServiceError as exc:
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": exc.code,
                "message": exc.message,
            },
        )
    except Exception:
        logger.exception("Unexpected realtime ASR session failure")
        await _send_browser_json(
            browser,
            {
                "type": "asr_error",
                "code": "internal_error",
                "message": "Realtime ASR session failed",
            },
        )
