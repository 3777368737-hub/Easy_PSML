from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.errors import UpstreamServiceError
from app.schemas import (
    AgentCapabilityCall,
    AgentConversationMessage,
    AgentPlan,
    BasicProfile,
    DomainAgentRequest,
    ProfileData,
)
from app.services import domain_agent, workflow
from app.services.domain_store import get_domain_store
from app.services.store import configure_store
from tests.test_workflow import FakeDeepSeekClient, OWNER_A


class FakeDomainQwen:
    def __init__(self, plan: AgentPlan) -> None:
        self.plan = plan

    async def chat_json(self, messages, response_model, **kwargs):
        return self.plan


class FailingDomainQwen:
    async def chat_json(self, messages, response_model, **kwargs):
        raise UpstreamServiceError("not configured")


class DomainAgentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "agent.db")
        self.domain = get_domain_store()
        self.person = self.domain.create_person(OWNER_A, "张三", ["小张"])
        self.background = self.domain.create_background(
            OWNER_A,
            self.person.id,
            "科研简历",
            ProfileData(
                basic_profile=BasicProfile(
                    full_name="张三",
                    current_university="原学校",
                    major="计算机",
                )
            ),
        )
        self.original_client = domain_agent.domain_qwen
        self.original_flow_client = workflow.client
        workflow.client = FakeDeepSeekClient()

    def tearDown(self) -> None:
        domain_agent.domain_qwen = self.original_client
        workflow.client = self.original_flow_client
        self.temp_dir.cleanup()

    async def test_domain_agent_resolves_person_resume_and_patches_profile(self) -> None:
        domain_agent.domain_qwen = FakeDomainQwen(
            AgentPlan(
                message="请确认修改背景。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="background.patch",
                    arguments={
                        "person_query": "小张",
                        "resume_name": "科研简历",
                        "operations": [
                            {
                                "op": "set",
                                "path": "basic_profile.current_university",
                                "value": "新学校",
                            }
                        ],
                    },
                ),
                needs_confirmation=True,
            )
        )
        request = DomainAgentRequest(
            transcript="把张三科研简历的学校改成新学校",
            active_background_id="",
            history=[
                AgentConversationMessage(
                    role="user",
                    content="先查看张三的科研简历",
                )
            ],
        )
        preview = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(preview.status, "confirmation_required")
        self.assertEqual(preview.resolved["person_id"], self.person.id)
        self.assertEqual(preview.resolved["background_id"], self.background.id)

        executed = await domain_agent.run_domain_command(
            OWNER_A,
            request.model_copy(update={"confirmed": True}),
        )
        self.assertEqual(executed.status, "executed")
        updated = self.domain.get_background(OWNER_A, self.background.id)
        self.assertEqual(
            updated.profile.basic_profile.current_university,
            "新学校",
        )
        self.assertEqual(updated.version, 2)

    async def test_domain_agent_has_safe_offline_create_fallback(self) -> None:
        domain_agent.domain_qwen = FailingDomainQwen()
        request = DomainAgentRequest(transcript="新建人物叫李四")
        preview = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(preview.status, "confirmation_required")
        executed = await domain_agent.run_domain_command(
            OWNER_A,
            request.model_copy(update={"confirmed": True}),
        )
        self.assertEqual(executed.status, "executed")
        self.assertEqual(executed.result["person"]["display_name"], "李四")

    async def test_domain_agent_creates_project_bound_story(self) -> None:
        domain_agent.domain_qwen = FakeDomainQwen(
            AgentPlan(
                message="请确认记录申请项目。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="application_project.create",
                    arguments={
                        "person_query": "张三",
                        "resume_name": "科研简历",
                        "school_name": "香港大学",
                        "program_name": "MSc Data Science",
                        "program_details": "项目官网资料",
                    },
                ),
                needs_confirmation=True,
            )
        )
        project_request = DomainAgentRequest(
            transcript="给张三科研简历记录香港大学数据科学项目",
        )
        preview = await domain_agent.run_domain_command(
            OWNER_A,
            project_request,
        )
        self.assertEqual(preview.status, "confirmation_required")
        created = await domain_agent.run_domain_command(
            OWNER_A,
            project_request.model_copy(update={"confirmed": True}),
        )
        self.assertEqual(created.status, "executed")
        application_project_id = created.resolved["application_project_id"]

        domain_agent.domain_qwen = FakeDomainQwen(
            AgentPlan(
                message="请确认开始故事。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="story.create",
                    arguments={
                        "person_query": "张三",
                        "resume_name": "科研简历",
                        "application_project_query": "MSc Data Science",
                        "title": "数据项目故事",
                        "focus": "项目匹配",
                    },
                ),
                needs_confirmation=True,
            )
        )
        story_request = DomainAgentRequest(
            transcript="在港大数据科学项目下挖掘数据项目故事",
            active_application_project_id=application_project_id,
        )
        story_preview = await domain_agent.run_domain_command(
            OWNER_A,
            story_request,
        )
        self.assertEqual(story_preview.status, "confirmation_required")
        story = await domain_agent.run_domain_command(
            OWNER_A,
            story_request.model_copy(update={"confirmed": True}),
        )
        self.assertEqual(story.status, "executed", story.message)
        self.assertEqual(
            story.result["story"]["application_project_id"],
            application_project_id,
        )
