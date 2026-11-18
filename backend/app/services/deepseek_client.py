from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.errors import ModelOutputError, UpstreamServiceError


logger = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


@dataclass(frozen=True)
class ChatCompletion:
    content: str
    finish_reason: str
    response_id: str = ""


class DeepSeekClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def chat_json(
        self,
        messages: List[Dict[str, str]],
        response_model: Type[ModelT],
        *,
        model: Optional[str] = None,
        max_tokens: int = 3000,
    ) -> ModelT:
        attempts = self.settings.deepseek_max_retries + 1
        retry_messages = list(messages)
        last_reason = "invalid_json"
        current_max_tokens = max_tokens

        for attempt in range(attempts):
            try:
                completion = await self._chat(
                    messages=retry_messages,
                    model=model,
                    max_tokens=current_max_tokens,
                    response_format={"type": "json_object"},
                )
            except ModelOutputError:
                last_reason = "empty_response"
                if attempt + 1 >= attempts:
                    raise
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The previous response had no usable content. Return one complete JSON "
                    "object that matches the requested schema.",
                )
                continue
            if completion.finish_reason == "length":
                last_reason = "length"
                logger.warning(
                    "Model JSON output was truncated: response_id=%s chars=%s attempt=%s",
                    completion.response_id,
                    len(completion.content),
                    attempt + 1,
                )
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The response was truncated. Return a shorter complete JSON object. "
                    "Use at most 4 concise items per list and no extra explanation.",
                )
                current_max_tokens = min(current_max_tokens + 1000, 8000)
                continue

            try:
                payload = self._parse_json_object(completion.content)
            except (json.JSONDecodeError, ValueError):
                last_reason = "invalid_json"
                logger.warning(
                    "Model returned invalid JSON: response_id=%s chars=%s attempt=%s",
                    completion.response_id,
                    len(completion.content),
                    attempt + 1,
                )
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The previous response was not valid JSON. Return only one complete "
                    "JSON object that matches the requested schema.",
                )
                continue

            try:
                return response_model.model_validate(payload)
            except ValidationError as exc:
                last_reason = "schema_validation"
                errors = [
                    {
                        "loc": ".".join(str(part) for part in error["loc"]),
                        "msg": error["msg"],
                    }
                    for error in exc.errors()[:8]
                ]
                logger.warning(
                    "Model JSON failed schema validation: response_id=%s errors=%s",
                    completion.response_id,
                    errors,
                )
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The previous JSON did not match the required schema. "
                    f"Fix these validation errors: {json.dumps(errors, ensure_ascii=True)}. "
                    "Return the complete corrected JSON object only.",
                )

        if last_reason == "length":
            raise ModelOutputError(
                "The model response exceeded the output limit. Please retry with a shorter prompt."
            )
        raise ModelOutputError(
            "The model did not return valid structured data after retrying."
        )

    async def chat_text(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 3000,
    ) -> str:
        attempts = self.settings.deepseek_max_retries + 1
        retry_messages = list(messages)
        current_max_tokens = max_tokens

        for attempt in range(attempts):
            try:
                completion = await self._chat(
                    messages=retry_messages,
                    model=model,
                    max_tokens=current_max_tokens,
                )
            except ModelOutputError:
                if attempt + 1 >= attempts:
                    raise
                retry_messages = self._retry_messages(
                    retry_messages,
                    "The previous response had no usable content. Return the complete "
                    "requested text.",
                )
                continue
            if completion.finish_reason != "length":
                return completion.content.strip()

            logger.warning(
                "Model text output was truncated: response_id=%s chars=%s attempt=%s",
                completion.response_id,
                len(completion.content),
                attempt + 1,
            )
            retry_messages = self._retry_messages(
                retry_messages,
                "The previous response was truncated. Produce a complete response within "
                "the requested word limit. Do not restart with a preamble.",
            )
            current_max_tokens = min(current_max_tokens + 1000, 8000)

        raise ModelOutputError(
            "The generated draft exceeded the output limit. Please retry with a shorter target length."
        )

    async def _chat(
        self,
        messages: List[Dict[str, str]],
        *,
        model: Optional[str],
        max_tokens: int,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> ChatCompletion:
        if not self.settings.deepseek_api_key:
            raise UpstreamServiceError(
                "DEEPSEEK_API_KEY is not configured",
                status_code=503,
                code="model_not_configured",
            )

        payload: Dict[str, Any] = {
            "model": model or self.settings.deepseek_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": self.settings.deepseek_temperature,
        }
        if response_format:
            payload["response_format"] = response_format

        timeout = httpx.Timeout(self.settings.deepseek_timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(self.settings.deepseek_max_retries + 1):
                try:
                    response = await client.post(
                        f"{self.settings.deepseek_base_url.rstrip('/')}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.settings.deepseek_api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    if status in {401, 403}:
                        raise UpstreamServiceError(
                            "Model service authentication failed",
                            status_code=503,
                            code="model_auth_failed",
                        ) from exc
                    if status != 429 and status < 500:
                        logger.error(
                            "Model request rejected: status=%s body=%s",
                            status,
                            exc.response.text[:500],
                        )
                        raise UpstreamServiceError(
                            "The model request was rejected",
                            code="model_request_rejected",
                        ) from exc
                    if attempt >= self.settings.deepseek_max_retries:
                        raise UpstreamServiceError() from exc
                    await asyncio.sleep(2**attempt)
                except httpx.RequestError as exc:
                    if attempt >= self.settings.deepseek_max_retries:
                        raise UpstreamServiceError(
                            "Could not reach the model service",
                        ) from exc
                    await asyncio.sleep(2**attempt)

        try:
            data = response.json()
            choice = data["choices"][0]
            message = choice["message"]
            content = self._normalize_content(message.get("content"))
            finish_reason = choice.get("finish_reason") or "stop"
            response_id = str(data.get("id", ""))
            if not content.strip():
                logger.warning(
                    "Model response had empty content: response_id=%s finish_reason=%s "
                    "message_keys=%s content_type=%s",
                    response_id,
                    finish_reason,
                    sorted(message.keys()),
                    type(message.get("content")).__name__,
                )
                return ChatCompletion(
                    content="",
                    finish_reason=finish_reason,
                    response_id=response_id,
                )
            return ChatCompletion(
                content=content,
                finish_reason=finish_reason,
                response_id=response_id,
            )
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.error("Unexpected model response shape: %s", type(exc).__name__)
            raise ModelOutputError() from exc

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
