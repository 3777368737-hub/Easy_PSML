from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.services import workflow
from app.services.store import configure_store
from tests.test_workflow import OWNER_A, FakeDeepSeekClient


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "api.db")
        self.original_client = workflow.client
        workflow.client = FakeDeepSeekClient()
        self.client = TestClient(app)
        self.headers = {"X-Client-Id": OWNER_A}

    def tearDown(self) -> None:
        workflow.client = self.original_client
        self.client.close()
        self.temp_dir.cleanup()

    def create_profile(self) -> dict:
        response = self.client.post(
            "/api/profile/extract",
            headers=self.headers,
            data={
                "full_name": "API Applicant",
                "target_field": "Artificial Intelligence",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_api_requires_client_id_and_returns_safe_validation_errors(self) -> None:
        response = self.client.post("/api/program/analyze", json={})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "client_id_required")

        response = self.client.post(
            "/api/program/analyze",
            headers=self.headers,
            json={
                "profile_id": "missing-profile",
                "school_name": "",
                "program_name": "",
                "word_limit": -1,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "request_validation_failed")

    def test_health_does_not_require_owner(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "database": "ok", "version": "1.1.0"},
        )

    def test_loopback_frontend_origin_is_allowed_by_cors(self) -> None:
        response = self.client.options(
            "/api/agent/text/stream",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": (
                    "content-type,x-client-id,x-request-id"
                ),
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers.get("access-control-allow-origin"),
            "http://127.0.0.1:3000",
        )
        patch_response = self.client.options(
            "/api/backgrounds/example/profile",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "PATCH",
                "Access-Control-Request-Headers": (
                    "content-type,x-client-id,x-request-id"
                ),
            },
        )
        self.assertEqual(patch_response.status_code, 200, patch_response.text)
        self.assertIn(
            "PATCH",
            patch_response.headers.get("access-control-allow-methods", ""),
        )

    def test_profile_endpoint_does_not_return_raw_resume(self) -> None:
        response = self.client.post(
            "/api/profile/extract",
            headers=self.headers,
            data={
                "full_name": "API Applicant",
                "target_field": "Artificial Intelligence",
            },
            files={
                "resume_file": (
                    "resume.txt",
                    b"Computer science student with project experience.",
                    "text/plain",
                )
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertNotIn("raw_resume_text", body)
        self.assertIn("profile_id", body)

    def test_strict_profile_validation_rejects_incomplete_background(self) -> None:
        response = self.client.post(
            "/api/profile/extract",
            headers=self.headers,
            data={
                "full_name": "Incomplete Applicant",
                "target_field": "Computer Science",
                "strict_profile": "true",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["code"], "required_profile_fields_missing")

        response = self.client.post(
            "/api/profile/extract",
            headers=self.headers,
            data={
                "full_name": "Complete Applicant",
                "current_university": "Example University",
                "major": "Computer Science",
                "target_degree": "Master's",
                "target_field": "Artificial Intelligence",
                "target_country": "United States",
                "project_experience": "Built a recommendation system.",
                "strict_profile": "true",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_other_client_cannot_read_created_profile_session(self) -> None:
        profile = self.create_profile()
        response = self.client.post(
            "/api/program/analyze",
            headers=self.headers,
            json={
                "profile_id": profile["profile_id"],
                "school_name": "Example University",
                "program_name": "MS AI",
                "word_limit": 800,
                "prompt_text": "Describe your preparation and career goals.",
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        analysis = response.json()

        response = self.client.post(
            "/api/story/start",
            headers=self.headers,
            json={
                "profile_id": profile["profile_id"],
                "analysis_id": analysis["analysis_id"],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        session_id = response.json()["session_id"]

        other_headers = {"X-Client-Id": "client-cccccccccccccccc"}
        response = self.client.get(f"/api/session/{session_id}", headers=other_headers)
        self.assertEqual(response.status_code, 404)
