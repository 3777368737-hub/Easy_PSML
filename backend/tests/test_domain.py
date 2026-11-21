from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.errors import ConflictError, NotFoundError
from app.schemas import (
    BasicProfile,
    BatchCreateRequest,
    EssayBranchCreateRequest,
    EssayProjectCreateRequest,
    ExperienceItem,
    ProfileData,
    ProfilePatchOperation,
    ProgramAnalysis,
    ProgramContext,
    StoryCards,
    StoryMessage,
    StoryInstanceReplyRequest,
    StoryInstanceStartRequest,
)
from app.services import batch, domain_workflow, workflow
from app.services.domain_store import get_domain_store
from app.services.store import configure_store, get_store
from tests.test_workflow import FakeDeepSeekClient, OWNER_A, OWNER_B


class DomainTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "domain.db")
        self.domain = get_domain_store()
        self.original_client = workflow.client
        workflow.client = FakeDeepSeekClient()
        self.person = self.domain.create_person(OWNER_A, "Test Applicant")
        self.background = self.domain.create_background(
            OWNER_A,
            self.person.id,
            "Research Resume",
            ProfileData(
                basic_profile=BasicProfile(
                    full_name="Test Applicant",
                    current_university="Example University",
                    major="Computer Science",
                    target_field="Artificial Intelligence",
                ),
                career_goal="Build useful AI products",
                projects=[
                    ExperienceItem(
                        title="Recommendation system",
                        summary="Built a recommendation prototype",
                        impact="Improved ranking quality",
                    )
                ],
            ),
        )

    def tearDown(self) -> None:
        workflow.client = self.original_client
        self.temp_dir.cleanup()

    async def complete_story(self, application_project_id: str | None = None):
        if application_project_id is None:
            application_project_id = self.domain.create_application_project(
                OWNER_A,
                self.background.id,
                "Story University",
                "MSc Story Mining",
            ).id
        story = await domain_workflow.start_story(
            OWNER_A,
            domain_workflow.StoryInstanceStartRequest(
                background_instance_id=self.background.id,
                application_project_id=application_project_id,
                title="Technical story",
                focus="Technical decisions and impact",
            ),
        )
        for answer in (
            "I built a recommendation prototype.",
            "I owned data preparation and model comparison.",
            "The team used the reproducible analysis report.",
        ):
            story = await domain_workflow.continue_story(
                OWNER_A,
                story.id,
                StoryInstanceReplyRequest(user_message=answer),
            )
        self.assertEqual(story.status, "ready")
        return story

    async def test_background_story_and_project_are_instance_scoped(self) -> None:
        story = await self.complete_story()
        self.assertEqual(story.background_instance_id, self.background.id)
        self.assertEqual(story.round_no, 3)
        self.assertEqual(len(story.messages), 7)
        self.assertGreater(self.domain.get_background(OWNER_A, self.background.id).version, 0)
        with self.assertRaises(NotFoundError):
            self.domain.get_story(OWNER_B, story.id)
        with self.assertRaises(ConflictError):
            self.domain.create_story(
                OWNER_A,
                self.background.id,
                "Technical story",
                application_project_id=story.application_project_id,
            )

        project = await domain_workflow.build_project(
            OWNER_A,
            EssayProjectCreateRequest(
                background_instance_id=self.background.id,
                story_instance_ids=[story.id],
                school_name="Example University",
                program_name="MS AI",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and future goals.",
            ),
        )
        self.assertEqual(project.story_instance_ids, [story.id])
        self.assertEqual(project.status, "drafted")
        self.assertIsNotNone(project.analysis)
        self.assertIsNotNone(project.outline)
        self.assertTrue(project.draft)
        self.assertEqual(
            {item.artifact_type for item in project.versions},
            {"outline", "draft"},
        )
        project = self.domain.patch_project(
            OWNER_A,
            project.id,
            changes={"word_limit": 900},
        )
        self.assertEqual(project.program.word_limit, 900)
        self.assertEqual(project.status, "stale")
        project = await domain_workflow.build_project(
            OWNER_A,
            EssayProjectCreateRequest(
                background_instance_id=self.background.id,
                story_instance_ids=[story.id],
                school_name="Example University",
                program_name="MS AI",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and future goals.",
            ),
        )
        item_id = self.background.profile.projects[0].id
        patched = self.domain.patch_background(
            OWNER_A,
            self.background.id,
            [
                ProfilePatchOperation(
                    op="set",
                    path="projects.impact",
                    item_id=item_id,
                    value="A directly evidenced improvement",
                ),
                ProfilePatchOperation(
                    op="set",
                    path="basic_profile.current_university",
                    value="Updated University",
                ),
            ],
            base_version=self.background.version,
        )
        self.assertEqual(
            patched.profile.basic_profile.current_university,
            "Updated University",
        )
        self.assertEqual(
            patched.profile.projects[0].impact,
            "A directly evidenced improvement",
        )
        stale = self.domain.get_project(OWNER_A, project.id)
        self.assertEqual(stale.status, "stale")
        self.assertIsNone(stale.analysis)
        self.assertIsNone(stale.outline)
        self.assertIsNone(stale.draft)

    async def test_domain_story_can_drive_instance_batch_generation(self) -> None:
        application_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "Example University",
            "MS AI",
        )
        story = await self.complete_story(application_project.id)
        request = BatchCreateRequest.model_validate(
            {
                "background_instance_id": self.background.id,
                "request_id": "domain-batch-request-0001",
                "tone": "balanced",
                "directions": [
                    {
                        "school_name": "Example University",
                        "program_name": "MS AI",
                        "application_project_id": application_project.id,
                        "story_instance_ids": [story.id],
                        "essays": [
                            {
                                "essay_type": "Personal Statement",
                                "word_limit": 800,
                                "tone": "academic",
                                "prompt_text": "Describe your preparation and future goals.",
                            },
                            {
                                "essay_type": "Motivation Letter",
                                "word_limit": 600,
                                "tone": "concise",
                                "prompt_text": "Explain your motivation for this program.",
                            },
                        ],
                    }
                ],
            }
        )
        with patch.object(batch.model_rate_limiter, "check"):
            created = batch.create_batch(OWNER_A, request)
            await batch.process_batch(OWNER_A, created.id)
        completed = self.domain.workspace_snapshot(OWNER_A)
        self.assertEqual(len(completed.projects), 2)
        self.assertTrue(
            all(
                project.application_project_id == application_project.id
                for project in completed.projects
            )
        )
        draft_tones = {
            project.versions[0].metadata.get("tone")
            for project in completed.projects
        }
        self.assertEqual(draft_tones, {"academic", "concise"})
        batch_snapshot = get_store().require_batch(created.id, OWNER_A)
        self.assertEqual(batch_snapshot.execution_mode, "instance")
        self.assertTrue(all(item.project_id for item in batch_snapshot.items))
        self.assertTrue(all(item.draft for item in batch_snapshot.items))

    async def test_resume_file_is_owner_scoped_and_removed_with_workspace(self) -> None:
        saved = self.domain.save_resume_file(
            OWNER_A,
            self.background.id,
            "research-resume.txt",
            b"resume content",
        )
        self.assertEqual(len(saved.source_sha256), 64)
        path, filename = self.domain.get_resume_file(
            OWNER_A,
            self.background.id,
        )
        self.assertEqual(filename, "research-resume.txt")
        self.assertEqual(path.read_bytes(), b"resume content")
        with self.assertRaises(NotFoundError):
            self.domain.get_resume_file(OWNER_B, self.background.id)
        self.domain.delete_workspace_data(OWNER_A)
        self.assertFalse(path.exists())

    async def test_legacy_sessions_are_visible_in_instance_workspace(self) -> None:
        store = get_store()
        profile = store.save_profile(
            OWNER_A,
            ProfileData(
                basic_profile=BasicProfile(
                    full_name="Legacy Applicant",
                    target_field="Computer Science",
                )
            ),
        )
        analysis = store.save_analysis(
            OWNER_A,
            profile.id,
            ProgramContext(
                school_name="Legacy University",
                program_name="MSc Computing",
                prompt_text="Describe your preparation and goals.",
            ),
            ProgramAnalysis(
                program_focus=["Computing"],
                matched_strengths=["Technical work"],
                potential_gaps=["Research depth"],
                writing_suggestions=["Use concrete evidence"],
                recommended_structure=[
                    "Motivation",
                    "Evidence",
                    "Fit",
                    "Goals",
                ],
            ),
        )
        store.create_session(
            OWNER_A,
            profile.id,
            analysis.id,
            messages=[
                StoryMessage(role="assistant", content="Legacy question"),
            ],
            cards=StoryCards(core_experience=["Built a project"]),
            status="ready",
        )
        workspace = self.domain.workspace_snapshot(OWNER_A)
        self.assertTrue(
            any(
                person.display_name == "Legacy Applicant"
                for person in workspace.persons
            )
        )
        self.assertTrue(
            any(story.title.startswith("Legacy ·") for story in workspace.stories)
        )
        self.assertTrue(
            any(
                project.program.school_name == "Legacy University"
                for project in workspace.projects
            )
        )

    async def test_story_and_essay_branch_stay_on_matching_application_project(
        self,
    ) -> None:
        application_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "Example University",
            "MS AI",
            "Verified AI curriculum",
        )
        story = await domain_workflow.start_story(
            OWNER_A,
            StoryInstanceStartRequest(
                background_instance_id=self.background.id,
                application_project_id=application_project.id,
                title="AI project story",
                focus="Technical evidence",
            ),
        )
        for answer in ("A", "B", "C"):
            story = await domain_workflow.continue_story(
                OWNER_A,
                story.id,
                StoryInstanceReplyRequest(user_message=answer),
            )
        self.assertEqual(
            story.application_project_id,
            application_project.id,
        )
        branch = await domain_workflow.create_application_essay_branch(
            OWNER_A,
            EssayBranchCreateRequest(
                application_project_id=application_project.id,
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your AI preparation and future goals.",
                story_instance_ids=[story.id],
                tone="authentic",
            ),
            store=self.domain,
        )
        self.assertEqual(
            branch.application_project_id,
            application_project.id,
        )
        self.assertEqual(branch.story_instance_ids, [story.id])

        other_project = self.domain.create_application_project(
            OWNER_A,
            self.background.id,
            "Other University",
            "MSc Data Science",
        )
        other_story = await domain_workflow.start_story(
            OWNER_A,
            StoryInstanceStartRequest(
                background_instance_id=self.background.id,
                application_project_id=other_project.id,
                title="AI project story",
                focus="Data science evidence",
            ),
        )
        self.assertNotEqual(other_story.id, story.id)
        with self.assertRaises(ConflictError):
            self.domain.create_project(
                OWNER_A,
                self.background.id,
                [story.id],
                ProgramContext(
                    school_name=other_project.school_name,
                    program_name=other_project.program_name,
                    prompt_text="Describe your preparation and goals.",
                ),
                application_project_id=other_project.id,
            )
