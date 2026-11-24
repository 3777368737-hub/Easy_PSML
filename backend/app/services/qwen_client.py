from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterator,
    Dict,
    Generic,
    List,
    Optional,
    Tuple,
    Type,
    TypeVar,
)

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.errors import ModelOutputError, UpstreamServiceError


logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass
class ChatJsonStreamEvent(Generic[ModelT]):
    message_delta: str = ""
    reset_message: bool = False
    result: Optional[ModelT] = None


class QwenClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        payload = self._asr_payload(audio, media_type, stream=False)
        data = await self._post("/chat/completions", payload)
        transcript = self._extract_transcript(data)
        if not transcript:
            raise ModelOutputError("Qwen returned an empty speech transcript")
        return transcript

    async def stream_transcribe(
        self, audio: bytes, media_type: str
    ) -> AsyncIterator[str]:
        payload = self._asr_payload(audio, media_type, stream=True)
        transcript = ""
        async for data in self._stream_post("/chat/completions", payload):
            piece, is_incremental = self._extract_stream_text_update(data)
            if not piece:
                continue
            if is_incremental:
                delta = piece
            elif transcript and piece.startswith(transcript):
                delta = piece[len(transcript) :]
            elif piece == transcript:
                delta = ""
            else:
                delta = piece
            if delta:
                transcript += delta
                yield delta
        if not transcript:
            raise ModelOutputError("Qwen returned an empty speech transcript")

    async def ocr_image(self, image: bytes, media_type: str = "image/png") -> str:
        if not image:
            raise ModelOutputError("Qwen OCR received an empty image")
        encoded = base64.b64encode(image).decode("ascii")
        data_uri = f"data:{media_type};base64,{encoded}"
        data = await self._post(
            "/chat/completions",
            {
                "model": self.settings.qwen_ocr_model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": data_uri},
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Transcribe all text in this document image. "
                                    "Return plain text only, preserving line breaks. "
                                    "Do not add explanations or Markdown fences."
                                ),
                            },
                        ],
                    }
                ],
                "temperature": 0,
            },
        )
        try:
            message = data["choices"][0]["message"]
            text = self._normalize_content(message.get("content")).strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelOutputError(
                "Qwen OCR returned an unexpected response shape"
            ) from exc
        if not text:
            raise ModelOutputError("Qwen OCR returned empty text")
        return text

    def _asr_payload(
        self, audio: bytes, media_type: str, *, stream: bool
    ) -> Dict[str, Any]:
        encoded = base64.b64encode(audio).decode("ascii")
        data_uri = f"data:{media_type};base64,{encoded}"
        return {
            "model": self.settings.qwen_asr_file_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {"data": data_uri},
                        }
                    ],
                }
            ],
            "asr_options": {
                "language": self.settings.qwen_asr_language,
                "enable_itn": True,
            },
            "stream": stream,
        }

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[ModelT],
        *,
        max_tokens: int = 1800,
    ) -> ModelT:
        attempts = self.settings.qwen_max_retries + 1
        retry_messages = list(messages)
        payload = {
            "model": self.settings.qwen_intent_model,
            "messages": retry_messages,
            "temperature": self.settings.qwen_temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": False,
        }

        for attempt in range(attempts):
            data = await self._post("/chat/completions", payload)
            try:
                choice = data["choices"][0]
                message = choice["message"]
                content = self._normalize_content(message.get("content"))
                finish_reason = choice.get("finish_reason") or "stop"
            except (KeyError, IndexError, TypeError) as exc:
                raise ModelOutputError("Qwen returned an unexpected response shape") from exc

            if finish_reason == "length":
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The JSON response was truncated. Return one shorter complete object.",
                )
                payload = {**payload, "messages": retry_messages}
                continue

            try:
                parsed = self._parse_json_object(content)
                return response_model.model_validate(parsed)
            except (json.JSONDecodeError, ValueError):
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The previous response was not one valid JSON object. "
                    "Return only the complete corrected JSON object.",
                )
            except ValidationError as exc:
                errors = [
                    {
                        "loc": ".".join(str(part) for part in error["loc"]),
                        "msg": error["msg"],
                    }
                    for error in exc.errors()[:8]
                ]
                retry_messages = self._retry_messages(
                    retry_messages,
                    "Fix the schema validation errors and return the complete JSON object only: "
                    f"{json.dumps(errors, ensure_ascii=True)}",
                )
            payload = {**payload, "messages": retry_messages}

        raise ModelOutputError("Qwen did not return valid structured data after retrying")

    async def stream_chat_json(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[ModelT],
        *,
        max_tokens: int = 900,
    ) -> AsyncIterator[ChatJsonStreamEvent[ModelT]]:
        attempts = self.settings.qwen_max_retries + 1
        retry_messages = list(messages)
        payload = {
            "model": self.settings.qwen_intent_model,
            "messages": retry_messages,
            "temperature": self.settings.qwen_temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
            "stream": True,
        }

        for attempt in range(attempts):
            content = ""
            emitted_message = ""
            finish_reason = "stop"
            async for data in self._stream_post("/chat/completions", payload):
                try:
                    choice = data["choices"][0]
                except (KeyError, IndexError, TypeError):
                    continue
                delta = choice.get("delta") or {}
                chunk = self._normalize_content(delta.get("content"))
                if not chunk:
                    chunk = self._normalize_content(
                        (choice.get("message") or {}).get("content")
                    )
                if not chunk:
                    chunk = self._normalize_content(
                        (data.get("output") or {}).get("text")
                    )
                content += chunk
                finish_reason = choice.get("finish_reason") or finish_reason

                message_prefix = self._extract_json_string_prefix(content, "message")
                if message_prefix == emitted_message:
                    continue
                if not message_prefix.startswith(emitted_message):
                    emitted_message = ""
                    yield ChatJsonStreamEvent(reset_message=True)
                message_delta = message_prefix[len(emitted_message) :]
                emitted_message = message_prefix
                if message_delta:
                    yield ChatJsonStreamEvent(message_delta=message_delta)

            if finish_reason == "length":
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The JSON response was truncated. Return one shorter complete object.",
                )
            else:
                try:
                    parsed = self._parse_json_object(content)
                    result = response_model.model_validate(parsed)
                    yield ChatJsonStreamEvent(result=result)
                    return
                except (json.JSONDecodeError, ValueError):
                    retry_messages = self._retry_messages(
                        retry_messages,
                        "The previous response was not one valid JSON object. "
                        "Return only the complete corrected JSON object.",
                    )
                except ValidationError as exc:
                    errors = [
                        {
                            "loc": ".".join(str(part) for part in error["loc"]),
                            "msg": error["msg"],
                        }
                        for error in exc.errors()[:8]
                    ]
                    retry_messages = self._retry_messages(
                        retry_messages,
                        "Fix the schema validation errors and return the complete JSON object only: "
                        f"{json.dumps(errors, ensure_ascii=True)}",
                    )

            if attempt < attempts - 1:
                yield ChatJsonStreamEvent(reset_message=True)
            payload = {**payload, "messages": retry_messages}

        raise ModelOutputError("Qwen did not return valid structured data after retrying")

    async def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not self.settings.qwen_api_key:
            raise UpstreamServiceError(
                "QWEN_API_KEY is not configured",
                status_code=503,
                code="qwen_not_configured",
            )

        timeout = httpx.Timeout(self.settings.qwen_timeout_seconds)
        url = f"{self.settings.qwen_base_url.rstrip('/')}{path}"
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(self.settings.qwen_max_retries + 1):
                try:
                    response = await client.post(
                        url,
                        headers={
                            "Authorization": f"Bearer {self.settings.qwen_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    return response.json()
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status in {401, 403}:
                        raise UpstreamServiceError(
                            "Qwen authentication failed",
                            status_code=503,
                            code="qwen_auth_failed",
                        ) from exc
                    if status == 429 or status >= 500:
                        if attempt < self.settings.qwen_max_retries:
                            await asyncio.sleep(2**attempt)
                            continue
                    logger.error(
                        "Qwen request rejected: status=%s body=%s",
                        status,
                        exc.response.text[:500],
                    )
                    raise UpstreamServiceError(
                        "Qwen rejected the request",
                        code="qwen_request_rejected",
                    ) from exc
                except (httpx.RequestError, ValueError) as exc:
                    if attempt < self.settings.qwen_max_retries:
                        await asyncio.sleep(2**attempt)
                        continue
                    raise UpstreamServiceError(
                        "Could not reach the Qwen service",
                        code="qwen_service_unavailable",
                    ) from exc

        raise UpstreamServiceError(
            "Could not reach the Qwen service",
            code="qwen_service_unavailable",
        )

    async def _stream_post(
        self, path: str, payload: Dict[str, Any]
    ) -> AsyncIterator[Dict[str, Any]]:
        if not self.settings.qwen_api_key:
            raise UpstreamServiceError(
                "QWEN_API_KEY is not configured",
                status_code=503,
                code="qwen_not_configured",
            )

        timeout = httpx.Timeout(self.settings.qwen_timeout_seconds)
        url = f"{self.settings.qwen_base_url.rstrip('/')}{path}"
        attempts = self.settings.qwen_max_retries + 1
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(attempts):
                received = False
                try:
                    async with client.stream(
                        "POST",
                        url,
                        headers={
                            "Authorization": f"Bearer {self.settings.qwen_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    ) as response:
                        if response.status_code >= 400:
                            body = (await response.aread()).decode(
                                "utf-8", errors="replace"
                            )
                            if response.status_code in {401, 403}:
                                raise UpstreamServiceError(
                                    "Qwen authentication failed",
                                    status_code=503,
                                    code="qwen_auth_failed",
                                )
                            if (
                                response.status_code == 429
                                or response.status_code >= 500
                            ) and attempt < attempts - 1:
                                await asyncio.sleep(2**attempt)
                                continue
                            logger.error(
                                "Qwen streaming request rejected: status=%s body=%s",
                                response.status_code,
                                body[:500],
                            )
                            raise UpstreamServiceError(
                                "Qwen rejected the request",
                                code="qwen_request_rejected",
                            )

                        content_type = response.headers.get("content-type", "").lower()
                        if "text/event-stream" not in content_type:
                            raw = (await response.aread()).decode(
                                "utf-8", errors="replace"
                            )
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError as exc:
                                raise UpstreamServiceError(
                                    "Qwen returned malformed streaming data",
                                    code="qwen_service_unavailable",
                                ) from exc
                            if not isinstance(data, dict):
                                raise UpstreamServiceError(
                                    "Qwen returned unexpected streaming data",
                                    code="qwen_service_unavailable",
                                )
                            if data.get("error"):
                                raise UpstreamServiceError(
                                    "Qwen rejected the request",
                                    code="qwen_request_rejected",
                                )
                            yield data
                            return

                        async for line in response.aiter_lines():
                            stripped = line.strip()
                            if not stripped or stripped.startswith(":"):
                                continue
                            if not stripped.startswith("data:"):
                                continue
                            raw = stripped[5:].strip()
                            if raw == "[DONE]":
                                return
                            try:
                                data = json.loads(raw)
                            except json.JSONDecodeError as exc:
                                if received:
                                    raise UpstreamServiceError(
                                        "Qwen returned malformed streaming data",
                                        code="qwen_service_unavailable",
                                    ) from exc
                                raise
                            if not isinstance(data, dict):
                                continue
                            if data.get("error"):
                                raise UpstreamServiceError(
                                    "Qwen rejected the request",
                                    code="qwen_request_rejected",
                                )
                            received = True
                            yield data
                        return
                except UpstreamServiceError:
                    raise
                except (httpx.RequestError, ValueError) as exc:
                    if received or attempt >= attempts - 1:
                        raise UpstreamServiceError(
                            "Could not reach the Qwen service",
                            code="qwen_service_unavailable",
                        ) from exc
                    await asyncio.sleep(2**attempt)

        raise UpstreamServiceError(
            "Could not reach the Qwen service",
            code="qwen_service_unavailable",
        )

    @staticmethod
    def _extract_transcript(data: Dict[str, Any]) -> str:
        candidates: List[Any] = []
        try:
            candidates.append(data["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError):
            pass
        output = data.get("output")
        if isinstance(output, dict):
            candidates.append(output.get("text"))
            try:
                candidates.append(output["choices"][0]["message"]["content"])
            except (KeyError, IndexError, TypeError):
                pass
        candidates.append(data.get("text"))

        for candidate in candidates:
            normalized = QwenClient._normalize_content(candidate).strip()
            if normalized:
                return normalized
        return ""

    @staticmethod
    def _extract_stream_text(data: Dict[str, Any]) -> str:
        text, _ = QwenClient._extract_stream_text_update(data)
        return text

    @staticmethod
    def _extract_stream_text_update(
        data: Dict[str, Any],
    ) -> Tuple[str, bool]:
        try:
            choice = data["choices"][0]
            delta = choice.get("delta") or {}
            normalized_delta = QwenClient._normalize_content(delta.get("content"))
            if normalized_delta:
                return normalized_delta, True
        except (KeyError, IndexError, TypeError):
            pass

        candidates: List[Any] = []
        try:
            choice = data["choices"][0]
            message = choice.get("message") or {}
            candidates.append(message.get("content"))
        except (KeyError, IndexError, TypeError):
            pass
        output = data.get("output")
        if isinstance(output, dict):
            candidates.append(output.get("text"))
        candidates.append(data.get("text"))

        for candidate in candidates:
            normalized = QwenClient._normalize_content(candidate)
            if normalized:
                return normalized, False
        return "", False

    @staticmethod
    def _normalize_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: List[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            return "".join(parts)
        return ""

    @staticmethod
    def _retry_messages(
        messages: List[Dict[str, str]], instruction: str
    ) -> List[Dict[str, str]]:
        return [*messages, {"role": "user", "content": instruction}]

    @staticmethod
    def _extract_json_string_prefix(text: str, field: str) -> str:
        match = re.search(rf'"{re.escape(field)}"\s*:\s*"', text)
        if match is None:
            return ""

        tokens: List[str] = []
        index = match.end()
        while index < len(text):
            character = text[index]
            if character == '"':
                break
            if character != "\\":
                tokens.append(character)
                index += 1
                continue
            if index + 1 >= len(text):
                break
            escape = text[index + 1]
            if escape == "u":
                if index + 6 > len(text):
                    break
                tokens.append(text[index : index + 6])
                index += 6
            else:
                tokens.append(text[index : index + 2])
                index += 2

        try:
            return json.loads('"' + "".join(tokens) + '"')
        except json.JSONDecodeError:
            return ""

    @staticmethod
    def _parse_json_object(text: str) -> Dict[str, Any]:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        raise json.JSONDecodeError("No complete JSON object found", cleaned, 0)
