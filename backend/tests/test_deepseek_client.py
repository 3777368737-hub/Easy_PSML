from __future__ import annotations

import unittest

from pydantic import BaseModel

from app.services.deepseek_client import ChatCompletion, DeepSeekClient


class ExampleModel(BaseModel):
    value: str


class ScriptedClient(DeepSeekClient):
    def __init__(self, completions):
        super().__init__()
        self.completions = list(completions)

    async def _chat(self, **kwargs):
        return self.completions.pop(0)


class DeepSeekClientTests(unittest.IsolatedAsyncioTestCase):
    def test_parser_accepts_fenced_json_and_surrounding_text(self) -> None:
        parsed = DeepSeekClient._parse_json_object(
            'Here is the result:\n```json\n{"value": "ok"}\n```'
        )
        self.assertEqual(parsed, {"value": "ok"})

    async def test_json_retries_after_truncation(self) -> None:
        client = ScriptedClient(
            [
                ChatCompletion(
                    content='{"value": "truncated',
                    finish_reason="length",
                ),
                ChatCompletion(
                    content='{"value": "complete"}',
                    finish_reason="stop",
                ),
            ]
        )
        result = await client.chat_json(
            [{"role": "user", "content": "Return JSON"}],
            ExampleModel,
        )
        self.assertEqual(result.value, "complete")

    async def test_json_retries_after_empty_content(self) -> None:
        client = ScriptedClient(
            [
                ChatCompletion(content="", finish_reason="stop"),
                ChatCompletion(
                    content='{"value": "recovered"}',
                    finish_reason="stop",
                ),
            ]
        )
        result = await client.chat_json(
            [{"role": "user", "content": "Return JSON"}],
            ExampleModel,
        )
        self.assertEqual(result.value, "recovered")
