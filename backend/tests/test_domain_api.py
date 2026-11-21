from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import AgentCapabilityCall, AgentPlan
from app.services import domain_agent, workflow
from app.services.store import configure_store
from tests.test_workflow import FakeDeepSeekClient, OWNER_A


class DomainApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "domain-api.db")
        self.original_client = workflow.client
        workflow.client = FakeDeepSeekClient()
        self.headers = {"X-Client-Id": OWNER_A}
        self.client = TestClient(app)

    def tearDown(self) -> None:
        workflow.client = self.original_client
        self.client.close()
        self.temp_dir.cleanup()

    def test_instance_api_supports_background_story_and_resume_download(self) -> None:
        person = self.client.post(
            "/api/persons",
            headers=self.headers,
            json={"display_name": "API Applicant"},
        )
        self.assertEqual(person.status_code, 201, person.text)
        person_id = person.json()["id"]

        profile = self.client.post(
            "/api/profile/extract",
            headers=self.headers,
            data={
                "full_name": "API Applicant",
                "current_university": "Example University",
                "major": "Computer Science",
                "target_field": "Artificial Intelligence",
                "person_id": person_id,
                "resume_name": "Research Resume",
                "strict_profile": "false",
            },
            files={
                "resume_file": (
                    "resume.txt",
                    io.BytesIO(b"API Applicant resume"),
                    "text/plain",
                )
            },
        )
        self.assertEqual(profile.status_code, 200, profile.text)
        background_id = profile.json()["background_instance_id"]
        self.assertTrue(background_id)

        application_project = self.client.post(
            "/api/application-projects",
            headers=self.headers,
            json={
                "background_instance_id": background_id,
                "school_name": "Example University",
                "program_name": "MS AI",
                "program_details": "Verified AI curriculum",
            },
        )
        self.assertEqual(
            application_project.status_code,
            201,
            application_project.text,
        )
        application_project_id = application_project.json()["id"]

        story = self.client.post(
            "/api/story-instances/start",
            headers=self.headers,
            json={
                "background_instance_id": background_id,
                "application_project_id": application_project_id,
                "title": "Research Story",
                "focus": "Research evidence",
            },
        )
        self.assertEqual(story.status_code, 201, story.text)
        story_id = story.json()["id"]
        for answer in ("A", "B", "C"):
            reply = self.client.post(
                f"/api/story-instances/{story_id}/reply",
                headers=self.headers,
                json={"user_message": answer},
            )
            self.assertEqual(reply.status_code, 200, reply.text)

        project = self.client.post(
            f"/api/application-projects/{application_project_id}/essays",
            headers=self.headers,
            json={
                "application_project_id": application_project_id,
                "essay_type": "Personal Statement",
                "word_limit": 800,
                "prompt_text": "Describe your preparation and future goals.",
                "story_instance_ids": [story_id],
                "tone": "authentic",
            },
        )
        self.assertEqual(project.status_code, 201, project.text)
        self.assertEqual(project.json()["story_instance_ids"], [story_id])
        self.assertEqual(
            project.json()["application_project_id"],
            application_project_id,
        )

        workspace = self.client.get("/api/workspace", headers=self.headers)
        self.assertEqual(workspace.status_code, 200, workspace.text)
        self.assertEqual(len(workspace.json()["persons"]), 1)
        self.assertEqual(len(workspace.json()["backgrounds"]), 1)
        self.assertEqual(len(workspace.json()["application_projects"]), 1)
        self.assertEqual(len(workspace.json()["stories"]), 1)
        self.assertEqual(len(workspace.json()["projects"]), 1)

        plan = AgentPlan(
            message="已定位背景。",
            intent="navigate",
            capability=AgentCapabilityCall(
                name="background.select",
                arguments={
                    "person_query": "API Applicant",
                    "resume_name": "Research Resume",
                },
            ),
        )
        with patch.object(
            domain_agent.domain_qwen,
            "chat_json",
            return_value=plan,
        ):
            command = self.client.post(
                "/api/agent/domain",
                headers=self.headers,
                json={
                    "transcript": "打开 API Applicant 的科研简历",
                    "history": [
                        {
                            "role": "user",
                            "content": "先看看 API Applicant 的背景",
                        }
                    ],
                    "source": "text",
                },
            )
        self.assertEqual(command.status_code, 200, command.text)
        self.assertEqual(command.json()["status"], "executed")
        self.assertEqual(
            command.json()["resolved"]["background_id"],
            background_id,
        )

        resume = self.client.get(
            f"/api/backgrounds/{background_id}/resume",
            headers=self.headers,
        )
        self.assertEqual(resume.status_code, 200, resume.text)
        self.assertEqual(resume.content, b"API Applicant resume")

        other = self.client.get(
            f"/api/backgrounds/{background_id}/resume",
            headers={"X-Client-Id": "client-bbbbbbbbbbbbbbbb"},
        )
        self.assertEqual(other.status_code, 404)
