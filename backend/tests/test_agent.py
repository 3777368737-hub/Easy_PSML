from __future__ import annotations

import asyncio
import copy
import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.errors import UpstreamServiceError
from app.main import app
from app.schemas import (
    AgentCapabilityCall,
    AgentPlan,
    AgentUiAction,
    ProfileData,
)
from app.services import agent, realtime_asr
from app.services.agent_capabilities import capability_catalog, infer_capability
from app.services.qwen_client import ChatJsonStreamEvent, QwenClient
from app.services.store import configure_store
from tests.test_workflow import OWNER_A


CONTEXT = {
    "path": "/program",
    "title": "项目分析",
    "stage": "program",
    "summary": "填写目标项目并开始分析。",
    "controls": [
        {
            "id": "agent-0",
            "key": "program-school_name",
            "kind": "text",
            "label": "学校名称",
            "scope": "目标项目",
            "value": "",
            "required": True,
            "risk": "safe",
        },
        {
            "id": "agent-1",
            "key": "program-submit",
            "kind": "button",
            "label": "开始项目分析",
            "scope": "目标项目",
            "value": "",
            "required": False,
            "risk": "confirm",
            "capability": "program.analyze",
        },
    ],
    "workflow": [
        {
            "key": "program",
            "path": "/program",
            "title": "项目分析",
            "summary": "填写学校、项目、文书类型和题目。",
            "fields": ["program-school_name", "program-program_name"],
        }
    ],
    "boundaries": ["提交前必须由用户确认。"],
    "state": {},
    "ids": {
        "profile_id": "",
        "analysis_id": "",
        "session_id": "",
        "batch_id": "",
    },
    "page_data": {},
}


class FakeQwenClient:
    def __init__(self, plan=None):
        self.plan = plan or AgentPlan(
            message="需要补充项目信息。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="program.analyze",
                arguments={},
            ),
            ui_actions=[
                AgentUiAction(
                    type="fill",
                    target_key="program-school_name",
                    value="香港科技大学",
                    reason="填写学校",
                ),
                AgentUiAction(
                    type="fill",
                    target_key="missing",
                    value="不应执行",
                    reason="无效目标",
                ),
            ],
        )

    async def transcribe(self, audio: bytes, media_type: str) -> str:
        return "把学校填成香港科技大学"

    async def chat_json(self, messages, response_model, *, max_tokens=1800):
        return self.plan


class FakeStreamingQwenClient(FakeQwenClient):
    async def stream_transcribe(self, audio: bytes, media_type: str):
        yield "open"
        yield " project"

    async def stream_chat_json(self, messages, response_model, *, max_tokens=900):
        yield ChatJsonStreamEvent(message_delta="Opened")
        yield ChatJsonStreamEvent(message_delta=" project.")
        yield ChatJsonStreamEvent(
            result=AgentPlan(
                message="Opened project.",
                intent="navigate",
                capability=AgentCapabilityCall(
                    name="app.navigate",
                    arguments={"path": "/program"},
                ),
            )
        )


class FailingQwenClient(FakeQwenClient):
    async def chat_json(self, messages, response_model, *, max_tokens=1800):
        raise UpstreamServiceError("not configured")

    async def stream_chat_json(self, messages, response_model, *, max_tokens=900):
        raise UpstreamServiceError("not configured")
        yield


class ScriptedStreamingQwenClient(QwenClient):
    def __init__(self, streams):
        super().__init__()
        self.streams = list(streams)

    async def _stream_post(self, path, payload):
        for item in self.streams.pop(0):
            yield item


class FakeRealtimeUpstream:
    def __init__(self) -> None:
        self.messages = asyncio.Queue()
        self.audio_chunks = []

    async def send(self, value):
        if isinstance(value, bytes):
            self.audio_chunks.append(value)
            self.messages.put_nowait(
                json.dumps(
                    {
                        "header": {"event": "result-generated"},
                        "payload": {
                            "output": {
                                "sentence": {
                                    "sentence_id": 1,
                                    "begin_time": 0,
                                    "end_time": None,
                                    "text": "open",
                                    "sentence_begin": True,
                                    "sentence_end": False,
                                }
                            }
                        },
                    }
                )
            )
            self.messages.put_nowait(
                json.dumps(
                    {
                        "header": {"event": "result-generated"},
                        "payload": {
                            "output": {
                                "sentence": {
                                    "sentence_id": 1,
                                    "begin_time": 0,
                                    "end_time": 900,
                                    "text": "open project",
                                    "sentence_begin": False,
                                    "sentence_end": True,
                                }
                            }
                        },
                    }
                )
            )
            return

        payload = json.loads(value)
        action = payload.get("header", {}).get("action")
        if action == "run-task":
            self.messages.put_nowait(
                json.dumps(
                    {
                        "header": {"event": "task-started"},
                        "payload": {},
                    }
                )
            )
        elif action == "finish-task":
            self.messages.put_nowait(
                json.dumps(
                    {
                        "header": {"event": "task-finished"},
                        "payload": {},
                    }
                )
            )

    async def recv(self):
        return await self.messages.get()


class FakeRealtimeConnection:
    def __init__(self, upstream):
        self.upstream = upstream

    async def __aenter__(self):
        return self.upstream

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class AgentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "agent.db")
        self.original_qwen = agent.qwen_client
        agent.qwen_client = FakeQwenClient()
        self.client = TestClient(app)
        self.headers = {"X-Client-Id": OWNER_A}

    def tearDown(self) -> None:
        agent.qwen_client = self.original_qwen
        self.client.close()
        self.temp_dir.cleanup()

    def complete_program_context(self, profile_id: str) -> dict:
        context = copy.deepcopy(CONTEXT)
        context["ids"]["profile_id"] = profile_id
        context["page_data"] = {
            "program_form": {
                "school_name": "香港科技大学",
                "program_name": "MSc Data Science",
                "essay_type": "Personal Statement",
                "word_limit": "800",
                "prompt_text": "Explain why this program fits your career goal.",
                "program_details": "",
            }
        }
        return context

    def empty_program_context(self, profile_id: str) -> dict:
        context = copy.deepcopy(CONTEXT)
        context["ids"]["profile_id"] = profile_id
        context["focused_control_key"] = "program-school_name"
        context["controls"] = [
            {
                "id": "agent-0",
                "key": "program-school_name",
                "kind": "text",
                "label": "学校名称",
                "scope": "目标项目",
                "value": "",
                "required": True,
                "risk": "safe",
                "options": [],
            },
            {
                "id": "agent-1",
                "key": "program-program_name",
                "kind": "text",
                "label": "项目名称",
                "scope": "目标项目",
                "value": "",
                "required": True,
                "risk": "safe",
                "options": [],
            },
            {
                "id": "agent-2",
                "key": "program-essay_type",
                "kind": "select",
                "label": "文书类型",
                "scope": "目标项目",
                "value": "Personal Statement",
                "required": True,
                "risk": "safe",
                "options": [
                    {
                        "value": "Personal Statement",
                        "label": "Personal Statement",
                    },
                    {
                        "value": "Motivation Letter",
                        "label": "Motivation Letter",
                    },
                ],
            },
            {
                "id": "agent-3",
                "key": "program-word_limit",
                "kind": "number",
                "label": "字数上限",
                "scope": "目标项目",
                "value": "800",
                "required": True,
                "risk": "safe",
                "min_value": 100,
                "max_value": 5000,
                "options": [],
            },
            {
                "id": "agent-4",
                "key": "program-prompt_text",
                "kind": "textarea",
                "label": "文书题目 / 具体要求",
                "scope": "目标项目",
                "value": "",
                "required": True,
                "risk": "safe",
                "options": [],
            },
            {
                "id": "agent-5",
                "key": "program-submit",
                "kind": "button",
                "label": "开始项目分析",
                "scope": "目标项目",
                "value": "",
                "required": False,
                "risk": "confirm",
                "capability": "program.analyze",
                "options": [],
            },
        ]
        context["page_data"] = {
            "program_form": {
                "school_name": "",
                "program_name": "",
                "essay_type": "Personal Statement",
                "word_limit": "800",
                "prompt_text": "",
                "program_details": "",
            }
        }
        return context

    def test_text_agent_filters_ui_targets_and_blocks_incomplete_capability(self) -> None:
        response = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "把学校填成香港科技大学，然后开始分析",
                "context": CONTEXT,
                "history": [
                    {
                        "role": "system",
                        "content": "上一次语音命令已取消。",
                    }
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "text")
        self.assertEqual(body["status"], "needs_input")
        self.assertFalse(body["needs_confirmation"])
        self.assertEqual(body["capability"]["name"], "program.analyze")
        self.assertEqual(len(body["ui_actions"]), 2)
        fill_action = next(
            action for action in body["ui_actions"] if action["type"] == "fill"
        )
        self.assertEqual(fill_action["target_key"], "program-school_name")
        self.assertEqual(fill_action["value"], "香港科技大学")
        self.assertEqual(body["ui_actions"][-1]["type"], "focus")
        self.assertTrue(body["missing_fields"])
        self.assertEqual(body["pending_action"]["status"], "collecting")

    def test_voice_agent_uses_transcript_and_same_safe_action_pipeline(self) -> None:
        response = self.client.post(
            "/api/agent/voice",
            headers=self.headers,
            data={
                "context": json.dumps(CONTEXT, ensure_ascii=False),
                "history": "[]",
            },
            files={"audio": ("command.webm", b"fake-webm", "audio/webm")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["source"], "voice")
        self.assertEqual(body["transcript"], "把学校填成香港科技大学")
        self.assertEqual(body["capability"]["name"], "program.analyze")
        self.assertEqual(body["status"], "needs_input")

    def test_capability_catalog_covers_the_full_user_workflow(self) -> None:
        names = {item["name"] for item in capability_catalog()}
        self.assertIn("profile.continue_program", names)
        self.assertIn("program.analyze", names)
        self.assertIn("story.answer", names)
        self.assertIn("essay.outline", names)
        self.assertIn("essay.draft", names)
        self.assertIn("batch.create", names)
        self.assertIn("history.clear", names)
        self.assertIn("library.person.create", names)
        self.assertIn("library.application_project.create", names)
        self.assertIn("library.story.create", names)
        self.assertIn("agent.undo_last_edit", names)

    def test_clear_action_request_falls_back_to_workflow_capability(self) -> None:
        context = agent.AgentPageContext.model_validate(CONTEXT)
        call = infer_capability("帮我开始分析这个项目", context)
        self.assertIsNotNone(call)
        self.assertEqual(call.name, "program.analyze")

    def test_confirmation_token_is_context_validated_and_single_use(self) -> None:
        profile = agent.get_store().save_profile(OWNER_A, ProfileData())
        context = self.complete_program_context(profile.id)
        agent.qwen_client = FakeQwenClient(
            AgentPlan(
                message="请确认项目分析。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="program.analyze",
                    arguments={},
                ),
            )
        )
        response = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析香港科技大学的项目",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "confirmation_required")
        self.assertTrue(body["needs_confirmation"])
        self.assertEqual(body["pending_action"]["status"], "prepared")
        action_id = body["pending_action"]["id"]
        current = self.client.get(
            "/api/agent/actions/current",
            headers=self.headers,
        )
        self.assertEqual(current.status_code, 200, current.text)
        self.assertEqual(current.json()["id"], action_id)

        commit = self.client.post(
            f"/api/agent/actions/{action_id}/commit",
            headers=self.headers,
            json={"context": context},
        )
        self.assertEqual(commit.status_code, 200, commit.text)
        self.assertEqual(commit.json()["status"], "ready")
        self.assertEqual(commit.json()["capability"], "program.analyze")

        second = self.client.post(
            f"/api/agent/actions/{action_id}/commit",
            headers=self.headers,
            json={"context": context},
        )
        self.assertEqual(second.status_code, 404, second.text)

    def test_voice_confirmation_returns_pending_action_commit_call(self) -> None:
        profile = agent.get_store().save_profile(OWNER_A, ProfileData())
        context = self.complete_program_context(profile.id)
        ready_plan = AgentPlan(
            message="请确认项目分析。",
            intent="operate",
            capability=AgentCapabilityCall(
                name="program.analyze",
                arguments={},
            ),
        )
        agent.qwen_client = FakeQwenClient(ready_plan)
        prepared = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析项目",
                "context": context,
                "history": [],
            },
        ).json()
        action_id = prepared["pending_action"]["id"]

        agent.qwen_client = FakeQwenClient(
            AgentPlan(
                message="确认执行。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="agent.confirm_pending",
                    arguments={},
                ),
            )
        )
        confirmed = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "确认执行",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        body = confirmed.json()
        self.assertEqual(body["status"], "ready")
        self.assertEqual(body["capability"]["name"], "agent.confirm_pending")
        self.assertEqual(
            body["capability"]["arguments"]["action_id"],
            action_id,
        )

    def test_offline_slot_answer_continues_without_repeating_full_command(self) -> None:
        profile = agent.get_store().save_profile(OWNER_A, ProfileData())
        context = self.empty_program_context(profile.id)
        agent.qwen_client = FailingQwenClient()

        started = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析项目",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(started.status_code, 200, started.text)
        started_body = started.json()
        self.assertEqual(started_body["status"], "needs_input")
        self.assertEqual(
            started_body["pending_action"]["status"],
            "collecting",
        )

        answered = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "香港科技大学",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(answered.status_code, 200, answered.text)
        body = answered.json()
        fill = next(
            action
            for action in body["ui_actions"]
            if action["type"] == "fill"
        )
        self.assertEqual(fill["target_key"], "program-school_name")
        self.assertEqual(fill["value"], "香港科技大学")
        self.assertEqual(body["status"], "needs_input")
        self.assertEqual(body["next_field"], "program-program_name")
        self.assertEqual(
            body["pending_action"]["capability"],
            "program.analyze",
        )

    def test_offline_confirmation_and_repeat_controls_are_deterministic(self) -> None:
        profile = agent.get_store().save_profile(OWNER_A, ProfileData())
        context = self.complete_program_context(profile.id)
        agent.qwen_client = FailingQwenClient()
        prepared = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析项目",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertEqual(
            prepared.json()["status"],
            "confirmation_required",
        )

        repeated = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "再说一遍",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(repeated.status_code, 200, repeated.text)
        self.assertIn("请确认", repeated.json()["message"])

        confirmed = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "好的",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(confirmed.status_code, 200, confirmed.text)
        self.assertEqual(confirmed.json()["status"], "ready")
        self.assertEqual(
            confirmed.json()["capability"]["name"],
            "agent.confirm_pending",
        )

    def test_offline_ordinal_choice_and_undo_controls_work(self) -> None:
        context = self.empty_program_context("profile-test")
        context["focused_control_key"] = "program-essay_type"
        agent.qwen_client = FailingQwenClient()

        selected = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "第二个",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        fill = next(
            action
            for action in selected.json()["ui_actions"]
            if action["type"] == "fill"
        )
        self.assertEqual(fill["target_key"], "program-essay_type")
        self.assertEqual(fill["value"], "Motivation Letter")

        undo = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "撤销",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(undo.status_code, 200, undo.text)
        self.assertEqual(undo.json()["status"], "ready")
        self.assertEqual(
            undo.json()["capability"]["name"],
            "agent.undo_last_edit",
        )

    def test_offline_unknown_input_returns_safe_clarification(self) -> None:
        agent.qwen_client = FailingQwenClient()
        response = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "帮我看看这个",
                "context": CONTEXT,
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["intent"], "clarify")
        self.assertIn("没有理解", body["message"])

    def test_offline_library_form_open_uses_semantic_section(self) -> None:
        context = copy.deepcopy(CONTEXT)
        context.update(
            {
                "path": "/library",
                "title": "申请项目",
                "stage": "library",
                "summary": "管理申请项目。",
                "controls": [
                    {
                        "id": "agent-0",
                        "key": "background-source-form",
                        "kind": "button",
                        "label": "新建人物与简历背景",
                        "scope": "人物背景信息",
                        "value": "",
                        "required": False,
                        "risk": "safe",
                        "options": [],
                    }
                ],
                "page_data": {},
            }
        )
        agent.qwen_client = FailingQwenClient()
        response = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "新建人物背景",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        action = body["ui_actions"][0]
        self.assertEqual(action["type"], "open_section")
        self.assertEqual(action["section"], "background-source-form")

    def test_slot_guidance_does_not_jump_between_library_cards(self) -> None:
        context = {
            "path": "/library",
            "title": "申请项目",
            "stage": "library",
            "summary": "管理申请项目。",
            "focused_control_key": "new-person-name",
            "controls": [
                {
                    "id": "agent-0",
                    "key": "new-person-name",
                    "kind": "text",
                    "label": "新人物姓名",
                    "scope": "人物背景信息",
                    "value": "",
                    "required": True,
                    "risk": "safe",
                    "options": [],
                },
                {
                    "id": "agent-1",
                    "key": "library-person-create",
                    "kind": "button",
                    "label": "新增人物",
                    "scope": "人物背景信息",
                    "value": "",
                    "required": False,
                    "risk": "confirm",
                    "capability": "library.person.create",
                    "options": [],
                },
                {
                    "id": "agent-2",
                    "key": "workbench-school",
                    "kind": "text",
                    "label": "学校",
                    "scope": "已记录项目",
                    "value": "",
                    "required": True,
                    "risk": "safe",
                    "options": [],
                },
            ],
            "workflow": [],
            "boundaries": [],
            "state": {},
            "ids": {},
            "page_data": {},
        }
        agent.qwen_client = FailingQwenClient()
        prepared = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "提交新增人物",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(prepared.status_code, 200, prepared.text)
        self.assertEqual(prepared.json()["status"], "needs_input")

        filled = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "张三",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(filled.status_code, 200, filled.text)
        body = filled.json()
        self.assertEqual(body["status"], "confirmation_required")
        self.assertFalse(
            any(
                action.get("target_key") == "workbench-school"
                for action in body["ui_actions"]
                if action["type"] == "focus"
            )
        )

    def test_file_input_falls_back_to_explicit_manual_prompt(self) -> None:
        context = copy.deepcopy(CONTEXT)
        context.update(
            {
                "path": "/profile",
                "title": "背景资料",
                "stage": "profile",
                "summary": "填写背景资料。",
                "controls": [
                    {
                        "id": "agent-0",
                        "key": "resume-file",
                        "kind": "file",
                        "label": "选择简历",
                        "scope": "从一份简历开始",
                        "value": "",
                        "required": False,
                        "risk": "safe",
                        "options": [],
                    },
                    {
                        "id": "agent-1",
                        "key": "profile-parse-resume",
                        "kind": "button",
                        "label": "一键解析简历并回填",
                        "scope": "从一份简历开始",
                        "value": "",
                        "required": False,
                        "disabled": True,
                        "risk": "confirm",
                        "capability": "profile.parse_resume",
                        "options": [],
                    },
                ],
                "page_data": {
                    "resume_selected": False,
                    "resume_name": "",
                },
            }
        )
        agent.qwen_client = FailingQwenClient()
        first = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "解析简历",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(first.json()["status"], "needs_input")

        second = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "这是我的简历",
                "context": context,
                "history": [],
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertIn("不能通过语音选择本地文件", second.json()["message"])

    def test_streaming_agent_falls_back_when_intent_model_fails(self) -> None:
        agent.qwen_client = FailingQwenClient()
        response = self.client.post(
            "/api/agent/text/stream",
            headers=self.headers,
            json={
                "transcript": "帮我看看这个",
                "context": CONTEXT,
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: final", response.text)
        self.assertIn("没有理解", response.text)

    def test_commit_revalidates_changed_page_state(self) -> None:
        profile = agent.get_store().save_profile(OWNER_A, ProfileData())
        context = self.complete_program_context(profile.id)
        agent.qwen_client = FakeQwenClient(
            AgentPlan(
                message="请确认。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="program.analyze",
                    arguments={},
                ),
            )
        )
        prepared = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析项目",
                "context": context,
                "history": [],
            },
        ).json()
        changed = copy.deepcopy(context)
        changed["page_data"]["program_form"]["prompt_text"] = ""
        commit = self.client.post(
            f"/api/agent/actions/{prepared['pending_action']['id']}/commit",
            headers=self.headers,
            json={"context": changed},
        )
        self.assertEqual(commit.status_code, 200, commit.text)
        self.assertEqual(commit.json()["status"], "needs_input")
        self.assertEqual(
            commit.json()["missing_fields"][0]["key"],
            "prompt_text",
        )

    def test_confirmation_word_does_not_confirm_incomplete_pending_action(self) -> None:
        first = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "开始分析项目",
                "context": CONTEXT,
                "history": [],
            },
        ).json()
        self.assertEqual(first["pending_action"]["status"], "collecting")

        agent.qwen_client = FakeQwenClient(
            AgentPlan(
                message="确认执行。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="agent.confirm_pending",
                    arguments={},
                ),
            )
        )
        second = self.client.post(
            "/api/agent/text",
            headers=self.headers,
            json={
                "transcript": "继续",
                "context": CONTEXT,
                "history": [],
            },
        )
        self.assertEqual(second.status_code, 200, second.text)
        body = second.json()
        self.assertEqual(body["status"], "needs_input")
        self.assertEqual(body["capability"]["name"], "program.analyze")
        self.assertEqual(body["pending_action"]["status"], "collecting")

    def test_asr_response_parser_accepts_standard_chat_shape(self) -> None:
        transcript = QwenClient._extract_transcript(
            {
                "choices": [
                    {
                        "message": {
                            "content": [{"text": "打开项目分析页面"}],
                        }
                    }
                ]
            }
        )
        self.assertEqual(transcript, "打开项目分析页面")


    def test_streaming_text_agent_emits_deltas_and_final_response(self) -> None:
        agent.qwen_client = FakeStreamingQwenClient()
        response = self.client.post(
            "/api/agent/text/stream",
            headers=self.headers,
            json={
                "transcript": "open project",
                "context": CONTEXT,
                "history": [],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(
            response.headers["content-type"].startswith("text/event-stream")
        )
        self.assertIn("event: message_delta", response.text)
        self.assertIn("Opened", response.text)
        self.assertIn("event: final", response.text)

    def test_streaming_voice_agent_emits_transcript_and_reply_deltas(self) -> None:
        agent.qwen_client = FakeStreamingQwenClient()
        response = self.client.post(
            "/api/agent/voice/stream",
            headers=self.headers,
            data={
                "context": json.dumps(CONTEXT, ensure_ascii=False),
                "history": "[]",
            },
            files={"audio": ("command.webm", b"fake-webm", "audio/webm")},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("event: transcript_delta", response.text)
        self.assertIn("open", response.text)
        self.assertIn("event: message_delta", response.text)
        self.assertIn("event: final", response.text)

    def test_json_string_prefix_handles_partial_and_escaped_values(self) -> None:
        self.assertEqual(
            QwenClient._extract_json_string_prefix('{"message":"Hel', "message"),
            "Hel",
        )
        self.assertEqual(
            QwenClient._extract_json_string_prefix(
                '{"message":"line\\nnext"}',
                "message",
            ),
            "line\nnext",
        )

    def test_qwen_stream_transcription_emits_incremental_text(self) -> None:
        client = ScriptedStreamingQwenClient(
            [
                [
                    {"choices": [{"delta": {"content": "open"}}]},
                    {"choices": [{"delta": {"content": " project"}}]},
                ]
            ]
        )

        async def collect():
            return [part async for part in client.stream_transcribe(b"audio", "audio/webm")]

        self.assertEqual(asyncio.run(collect()), ["open", " project"])

    def test_qwen_stream_json_extracts_message_before_final_plan(self) -> None:
        content = (
            '{"message":"Hel'
            'lo","intent":"navigate","actions":[{"type":"navigate",'
            '"path":"/program","reason":"","risk":"safe"}],'
            '"needs_confirmation":false}'
        )
        client = ScriptedStreamingQwenClient(
            [
                [
                    {"choices": [{"delta": {"content": content[:24]}}]},
                    {"choices": [{"delta": {"content": content[24:]}}]},
                ]
            ]
        )

        async def collect():
            return [
                event
                async for event in client.stream_chat_json(
                    [{"role": "user", "content": "open project"}],
                    AgentPlan,
                )
            ]

        events = asyncio.run(collect())
        self.assertEqual("".join(event.message_delta for event in events), "Hello")
        self.assertIsNotNone(events[-1].result)
        self.assertEqual(events[-1].result.intent, "navigate")

    def test_realtime_asr_run_task_uses_streaming_model_and_vad(self) -> None:
        settings = realtime_asr.get_settings()
        context = agent.AgentPageContext.model_validate(CONTEXT)
        payload = realtime_asr.build_run_task_payload(
            "task-id",
            16000,
            context,
            [],
            settings,
        )
        parameters = payload["payload"]["parameters"]
        self.assertEqual(
            payload["payload"]["model"],
            "qwen-audio-3.1-asr-flash-streaming",
        )
        self.assertEqual(parameters["format"], "pcm")
        self.assertEqual(parameters["sample_rate"], 16000)
        self.assertEqual(parameters["vad_model"], "near_meeting_16k")
        self.assertTrue(parameters["heartbeat"])
        self.assertGreaterEqual(parameters["max_sentence_silence"], 200)

    def test_realtime_websocket_bridges_audio_and_sentence_events(self) -> None:
        upstream = FakeRealtimeUpstream()
        original_connect = realtime_asr.websockets.connect
        realtime_asr.websockets.connect = lambda *args, **kwargs: (
            FakeRealtimeConnection(upstream)
        )
        try:
            with self.client.websocket_connect(
                f"/api/agent/voice/realtime?client_id={OWNER_A}"
            ) as websocket:
                websocket.send_json(
                    {
                        "type": "start",
                        "context": CONTEXT,
                        "history": [],
                        "sample_rate": 16000,
                    }
                )
                ready = websocket.receive_json()
                self.assertEqual(ready["type"], "asr_ready")
                websocket.send_bytes(b"pcm-frame")
                first = websocket.receive_json()
                final = websocket.receive_json()
                self.assertEqual(first["type"], "transcript")
                self.assertEqual(first["text"], "open")
                self.assertFalse(first["sentence_end"])
                self.assertEqual(final["text"], "open project")
                self.assertTrue(final["sentence_end"])
                websocket.send_json({"type": "stop"})
                self.assertEqual(
                    websocket.receive_json(),
                    {"type": "asr_finishing"},
                )
                self.assertEqual(
                    websocket.receive_json(),
                    {"type": "asr_finished"},
                )
            self.assertEqual(upstream.audio_chunks, [b"pcm-frame"])
        finally:
            realtime_asr.websockets.connect = original_connect


if __name__ == "__main__":
    unittest.main()
