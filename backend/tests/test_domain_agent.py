from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.errors import UpstreamServiceError
from app.schemas import (
    AgentCapabilityCall,
    AgentConversationMessage,
    AgentMissingField,
    AgentPlan,
    BasicProfile,
    DomainAgentRequest,
    ProfileData,
    ProgramContext,
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

    async def test_new_essay_intent_uses_create_flow_not_existing_patch(self) -> None:
        domain_agent.domain_qwen = FakeDomainQwen(
            AgentPlan(
                message="更新现有文书。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="project.patch",
                    arguments={"project_query": "DDM"},
                ),
            )
        )
        application_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "香港科技大学",
            "DDM",
            "",
        )
        existing_project = self.domain.create_project(
            OWNER_A,
            self.background.id,
            [],
            ProgramContext(
                school_name="香港科技大学",
                program_name="DDM",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and goals.",
                program_details="",
            ),
            application_project_id=application_project.id,
        )
        request = DomainAgentRequest(
            transcript="我要从头创建一篇新文书",
            active_person_id=self.person.id,
            active_background_id=self.background.id,
            active_application_project_id=application_project.id,
            active_project_id=existing_project.id,
        )
        response = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(response.status, "needs_input")
        self.assertEqual(
            response.capability.name,
            "essay_branch.create",
        )
        self.assertNotEqual(response.capability.name, "project.patch")
        self.assertIn("已完成故事", response.message)

    async def test_new_essay_requires_explicit_background_selection(self) -> None:
        domain_agent.domain_qwen = FailingDomainQwen()
        request = DomainAgentRequest(transcript="创建新文书")
        response = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(response.status, "needs_input")
        self.assertEqual(
            response.capability.name,
            "essay_branch.create",
        )
        self.assertIn("选择人物背景", response.message)
        self.assertIn("科研简历", response.message)

    async def test_stored_active_background_requires_verified_selection(self) -> None:
        domain_agent.domain_qwen = FailingDomainQwen()
        unverified = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="创建新文书",
                active_person_id=self.person.id,
                active_background_id=self.background.id,
                allow_stored_background=False,
            ),
        )
        self.assertEqual(unverified.next_field, "background")

        verified = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="创建新文书",
                active_person_id=self.person.id,
                active_background_id=self.background.id,
                allow_stored_person=True,
                allow_stored_background=True,
            ),
        )
        self.assertNotEqual(verified.next_field, "background")
        self.assertEqual(verified.resolved["background_id"], self.background.id)

    async def test_pending_essay_flow_keeps_selected_background(self) -> None:
        domain_agent.domain_qwen = FailingDomainQwen()
        first = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(transcript="创建新文书"),
        )
        self.assertEqual(first.next_field, "background")
        self.assertEqual(
            first.missing_fields[0].key,
            "background",
        )
        second = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="科研简历",
                pending_capability=first.capability.name,
                pending_arguments=first.arguments,
                pending_resolved=first.resolved,
            ),
        )
        self.assertEqual(second.status, "needs_input")
        self.assertEqual(
            second.capability.name,
            "essay_branch.create",
        )
        self.assertEqual(second.arguments["background_query"], "科研简历")
        self.assertEqual(second.resolved["background_id"], self.background.id)
        self.assertEqual(second.next_field, "application_project")
        self.assertNotIn("选择人物背景", second.message)
        self.assertIn("申请项目", second.message)

    async def test_ambiguous_story_correction_replaces_story_slot(self) -> None:
        plan = domain_agent._pending_plan(
            DomainAgentRequest(
                transcript="港科大 DDM 科研故事",
                pending_capability="essay_branch.create",
                pending_arguments={
                    "background_query": "科研简历",
                    "application_project_query": "DDM",
                    "story_titles": ["科研故事"],
                },
                pending_next_field="story",
                pending_missing_fields=[
                    AgentMissingField(
                        key="story",
                        label="唯一匹配的已完成故事",
                    )
                ],
            )
        )
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan.capability.arguments["story_titles"],
            ["港科大 DDM 科研故事"],
        )
        self.assertNotIn("essay_type", plan.capability.arguments)

    async def test_slot_value_starting_with_command_word_is_not_confirmation(self) -> None:
        plan = domain_agent._pending_plan(
            DomainAgentRequest(
                transcript="继续教育项目",
                pending_capability="essay_branch.create",
                pending_arguments={},
                pending_next_field="background",
            )
        )
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan.capability.arguments["background_query"],
            "继续教育项目",
        )

    async def test_pending_background_correction_keeps_person_and_resume(self) -> None:
        domain_agent.domain_qwen = FakeDomainQwen(
            AgentPlan(
                message="请确认更新。",
                intent="operate",
                capability=AgentCapabilityCall(
                    name="background.patch",
                    arguments={
                        "operations": [
                            {
                                "op": "set",
                                "path": "basic_profile.current_university",
                                "value": "新学校",
                            }
                        ]
                    },
                ),
                needs_confirmation=True,
            )
        )
        response = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="改成新学校",
                pending_capability="background.patch",
                pending_arguments={
                    "person_query": "张三",
                    "resume_name": "科研简历",
                    "operations": [
                        {
                            "op": "set",
                            "path": "basic_profile.current_university",
                            "value": "旧学校",
                        }
                    ],
                },
                active_person_id=self.person.id,
                active_background_id=self.background.id,
            ),
        )
        self.assertEqual(response.status, "confirmation_required")
        self.assertEqual(
            response.arguments["person_query"],
            "张三",
        )
        self.assertEqual(
            response.arguments["resume_name"],
            "科研简历",
        )
        self.assertEqual(
            response.arguments["operations"][0]["value"],
            "新学校",
        )

    async def test_create_and_generate_essay_keeps_generation_goal(self) -> None:
        plan = domain_agent._new_essay_plan(
            "从头创建一篇新文书并直接生成结果"
        )
        self.assertIsNotNone(plan)
        self.assertEqual(
            plan.capability.name,
            "essay_branch.create",
        )
        self.assertTrue(
            plan.capability.arguments["generate_after_create"]
        )

    async def test_negated_phrases_do_not_reverse_user_intent(self) -> None:
        self.assertTrue(
            domain_agent._is_new_essay_intent(
                "创建一篇新文书，不要修改旧文书"
            )
        )
        create_only = domain_agent._new_essay_plan(
            "只创建新文书，不要生成草稿"
        )
        self.assertIsNotNone(create_only)
        self.assertFalse(
            create_only.capability.arguments["generate_after_create"]
        )
        self.assertFalse(
            domain_agent._is_new_essay_intent(
                "不要创建新文书，只修改现有文书"
            )
        )

    async def test_existing_essay_branch_offers_open_instead_of_retry_loop(self) -> None:
        application_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "香港科技大学",
            "DDM",
            "",
        )
        story = self.domain.create_story(
            OWNER_A,
            self.background.id,
            "科研故事",
            application_project_id=application_project.id,
            status="ready",
            round_no=3,
        )
        existing = self.domain.create_project(
            OWNER_A,
            self.background.id,
            [story.id],
            ProgramContext(
                school_name="香港科技大学",
                program_name="DDM",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and goals.",
                program_details="",
            ),
            application_project_id=application_project.id,
        )
        domain_agent.domain_qwen = FailingDomainQwen()
        arguments = {
            "background_instance_id": self.background.id,
            "application_project_id": application_project.id,
            "story_titles": ["科研故事"],
            "essay_type": "Personal Statement",
            "prompt_text": "Describe your preparation and goals.",
        }
        first = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="Describe your preparation and goals.",
                pending_capability="essay_branch.create",
                pending_arguments=arguments,
                pending_next_field="prompt_text",
            ),
        )
        self.assertEqual(first.status, "needs_input")
        self.assertEqual(
            first.next_field,
            "existing_branch_choice",
        )
        self.assertEqual(first.resolved["project_id"], existing.id)

        opened = await domain_agent.run_domain_command(
            OWNER_A,
            DomainAgentRequest(
                transcript="打开现有",
                pending_capability="essay_branch.create",
                pending_arguments=first.arguments,
                pending_resolved=first.resolved,
                pending_next_field=first.next_field,
            ),
        )
        self.assertEqual(opened.status, "executed")
        self.assertEqual(opened.capability.name, "project.open")
        self.assertEqual(opened.resolved["project_id"], existing.id)

    async def test_partial_generation_resumes_existing_branch(self) -> None:
        application_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "香港科技大学",
            "DDM",
            "",
        )
        project = self.domain.create_project(
            OWNER_A,
            self.background.id,
            [],
            ProgramContext(
                school_name="香港科技大学",
                program_name="DDM",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and goals.",
                program_details="",
            ),
            application_project_id=application_project.id,
        )
        arguments = {
            "existing_project_id": project.id,
            "generate_after_create": True,
        }
        request = DomainAgentRequest(
            transcript="继续",
            pending_capability="essay_branch.create",
            pending_arguments=arguments,
            pending_resolved={
                "background_id": self.background.id,
                "project_id": project.id,
            },
            confirmed=True,
        )
        with patch.object(
            domain_agent,
            "_complete_created_essay",
            new=AsyncMock(side_effect=UpstreamServiceError("temporary")),
        ):
            failed = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(failed.status, "needs_input")
        self.assertEqual(failed.next_field, "resume_generation")
        self.assertEqual(
            failed.arguments["existing_project_id"],
            project.id,
        )

        with patch.object(
            domain_agent,
            "_complete_created_essay",
            new=AsyncMock(return_value=project),
        ):
            resumed = await domain_agent.run_domain_command(OWNER_A, request)
        self.assertEqual(resumed.status, "executed")
        self.assertEqual(resumed.resolved["project_id"], project.id)

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
