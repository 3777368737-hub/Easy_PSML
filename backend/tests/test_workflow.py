from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.errors import ConflictError, NotFoundError
from app.schemas import (
    BasicProfile,
    DraftRequest,
    DraftReview,
    EssayOutline,
    ExperienceItem,
    OutlineParagraph,
    ProgramAnalysis,
    ProgramAnalyzeRequest,
    ProfileData,
    StoryCards,
    StoryCardsUpdate,
    StoryTurnOutput,
)
from app.services import workflow
from app.services.store import configure_store, get_store


OWNER_A = "client-aaaaaaaaaaaaaaaa"
OWNER_B = "client-bbbbbbbbbbbbbbbb"


class FakeDeepSeekClient:
    async def chat_json(self, messages, response_model, **kwargs):
        if response_model is ProfileData:
            return ProfileData(
                basic_profile=BasicProfile(
                    full_name="Test Applicant",
                    major="Computer Science",
                    target_field="Artificial Intelligence",
                ),
                career_goal="Build useful AI products",
                projects=[
                    ExperienceItem(
                        title="Course project",
                        summary="Built a small recommendation system",
                        impact="Improved ranking accuracy",
                    )
                ],
                top_strengths=["Product thinking", "Technical execution"],
            )
        if response_model is ProgramAnalysis:
            return ProgramAnalysis(
                program_focus=["Applied machine learning", "Product impact"],
                matched_strengths=["Technical execution", "Product thinking"],
                potential_gaps=["Research depth"],
                writing_suggestions=["Use one concrete project", "Connect goals to the program"],
                recommended_structure=["Motivation", "Evidence", "Program fit", "Career goal"],
                avoid_phrases=["passionate about technology"],
            )
        if response_model is StoryTurnOutput:
            return StoryTurnOutput(
                assistant_message="你的经历可以形成一条清晰的产品与技术叙事。",
                questions=[
                    "这个项目解决了什么问题？",
                    "你做的核心技术决定是什么？",
                    "结果如何衡量？",
                ],
                cards=StoryCards(
                    motivation=["Build useful AI products"],
                    core_experience=["Built a recommendation system"],
                    contribution_impact=["Improved ranking accuracy"],
                    strengths=["Product thinking"],
                    career_goal=["Build useful AI products"],
                    program_fit=["Applied machine learning"],
                ),
            )
        if response_model is StoryCardsUpdate:
            return StoryCardsUpdate(
                cards=StoryCards(
                    motivation=["Build useful AI products"],
                    core_experience=["Built a recommendation system"],
                    contribution_impact=["Improved ranking accuracy"],
                    strengths=["Product thinking"],
                    career_goal=["Solve search quality"],
                    program_fit=["Applied machine learning"],
                )
            )
        if response_model is EssayOutline:
            return EssayOutline(
                title="申请文书大纲",
                paragraphs=[
                    OutlineParagraph(
                        heading=f"第 {index} 段",
                        goal="推进叙事",
                        key_content="使用已提供的项目事实",
                        use_this_experience="推荐系统项目",
                        what_to_highlight="行动与影响",
                    )
                    for index in range(1, 5)
                ],
            )
        if response_model is DraftReview:
            return DraftReview(
                strengths=["Concrete project evidence"],
                weaknesses=["Program fit could be more specific"],
                template_like_phrases=[],
                suggested_details_to_add=["Explain one technical tradeoff"],
                adaptation_tip="Use verified program details.",
            )
        raise AssertionError(f"Unexpected response model: {response_model}")

    async def chat_text(self, messages, **kwargs):
        return " ".join(["word"] * 800)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "test.db")
        self.original_client = workflow.client
        workflow.client = FakeDeepSeekClient()

    def tearDown(self) -> None:
        workflow.client = self.original_client
        self.temp_dir.cleanup()

    async def create_profile(self, owner_id: str = OWNER_A):
        return await workflow.extract_profile_from_input(
            owner_id,
            {
                "full_name": "Test Applicant",
                "target_field": "Artificial Intelligence",
                "resume_text": "Computer science student",
            },
        )

    async def create_analysis(self, profile_id: str, owner_id: str = OWNER_A):
        return await workflow.analyze_program(
            owner_id,
            ProgramAnalyzeRequest(
                profile_id=profile_id,
                school_name="Example University",
                program_name="MS AI",
                word_limit=600,
                prompt_text="Describe your preparation and goals.",
            ),
        )

    async def test_full_workflow_persists_context_and_versions(self) -> None:
        profile = await self.create_profile()
        analysis = await self.create_analysis(profile.id)
        self.assertEqual(analysis.program.word_limit, 600)

        story = await workflow.start_story_session(
            OWNER_A,
            profile.id,
            analysis.analysis_id,
        )
        self.assertEqual(len(story.questions), 3)

        story = await workflow.continue_story_session(OWNER_A, story.session_id, "I built a ranking model.")
        self.assertEqual(story.round_no, 2)
        story = await workflow.continue_story_session(OWNER_A, story.session_id, "The result improved by 10%.")
        self.assertEqual(story.round_no, 3)
        story = await workflow.continue_story_session(OWNER_A, story.session_id, "I want to solve search quality.")
        self.assertEqual(story.status, "ready")

        outline_one = await workflow.generate_outline(OWNER_A, story.session_id)
        outline_two = await workflow.generate_outline(OWNER_A, story.session_id)
        self.assertEqual(outline_one.version, 1)
        self.assertEqual(outline_two.version, 2)

        draft = await workflow.generate_draft(
            OWNER_A,
            DraftRequest(session_id=story.session_id),
        )
        self.assertEqual(draft.target_length, 600)
        self.assertEqual(draft.version, 1)

        review = await workflow.review_draft(OWNER_A, story.session_id)
        self.assertEqual(review.review.strengths[0], "Concrete project evidence")

        snapshot = get_store().session_snapshot(story.session_id, OWNER_A)
        self.assertEqual(snapshot.program.school_name, "Example University")
        self.assertEqual(len(snapshot.versions), 3)
        self.assertEqual(snapshot.status, "ready")

        history = get_store().list_history(OWNER_A)
        self.assertEqual(len(history), 1)
        self.assertTrue(history[0].has_draft)

        with self.assertRaises(NotFoundError):
            get_store().session_snapshot(story.session_id, OWNER_B)

    async def test_mismatched_profile_and_analysis_are_rejected(self) -> None:
        profile_one = await self.create_profile()
        profile_two = await self.create_profile()
        analysis_two = await self.create_analysis(profile_two.id)

        with self.assertRaises(ConflictError):
            await workflow.start_story_session(
                OWNER_A,
                profile_one.id,
                analysis_two.analysis_id,
            )

    async def test_story_generation_requires_completed_interview(self) -> None:
        profile = await self.create_profile()
        analysis = await self.create_analysis(profile.id)
        story = await workflow.start_story_session(
            OWNER_A,
            profile.id,
            analysis.analysis_id,
        )

        with self.assertRaises(ConflictError):
            await workflow.generate_outline(OWNER_A, story.session_id)
