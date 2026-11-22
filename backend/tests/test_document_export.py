from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from docx import Document as WordDocument
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.errors import UpstreamServiceError
from app.main import app
from app.schemas import BasicProfile, ProfileData, ProgramContext
from app.services import document_export
from app.services.domain_store import get_domain_store
from app.services.store import configure_store

OWNER_A = "client-export-owner-0001"
OWNER_B = "client-export-owner-0002"


class DocumentExportApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        configure_store(Path(self.temp_dir.name) / "document-export.db")
        self.client = TestClient(app)
        self.headers = {"X-Client-Id": OWNER_A}

        domain = get_domain_store()
        person = domain.create_person(OWNER_A, "Export Applicant")
        background = domain.create_background(
            OWNER_A,
            person.id,
            "Application Resume",
            ProfileData(
                basic_profile=BasicProfile(
                    full_name="Export Applicant",
                    current_university="Example University",
                    major="Computer Science",
                    target_field="Artificial Intelligence",
                )
            ),
        )
        project = domain.create_project(
            OWNER_A,
            background.id,
            [],
            ProgramContext(
                school_name="Example University",
                program_name="MS Artificial Intelligence",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Describe your preparation and future goals.",
            ),
        )
        self.project = domain.save_project(
            OWNER_A,
            project.id,
            draft=(
                "I build useful systems from evidence.\n\n"
                "My research taught me to turn data into dependable decisions."
            ),
            status="drafted",
            current_step="draft",
        )
        self.empty_project = domain.create_project(
            OWNER_A,
            background.id,
            [],
            ProgramContext(
                school_name="Empty University",
                program_name="MSc Empty Draft",
                essay_type="Personal Statement",
                word_limit=800,
                prompt_text="Explain why this program matches your goals.",
            ),
        )

    def tearDown(self) -> None:
        self.client.close()
        self.temp_dir.cleanup()

    def test_project_export_returns_valid_docx_and_uses_glm_layout(self) -> None:
        formatted = document_export.FormattedDocument(
            title="Personal Statement",
            subtitle="Example University | MS Artificial Intelligence",
            paragraphs=self.project.draft.split("\n\n"),
        )
        with patch.object(
            document_export,
            "_format_with_glm",
            new=AsyncMock(return_value=formatted),
        ) as format_with_glm:
            response = self.client.post(
                f"/api/essay-projects/{self.project.id}/export",
                headers=self.headers,
                json={"format": "docx"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"],
            document_export.DOCX_MEDIA_TYPE,
        )
        self.assertEqual(
            response.headers["x-document-formatting"],
            "glm",
        )
        self.assertIn("attachment;", response.headers["content-disposition"])
        self.assertTrue(response.content.startswith(b"PK"))
        word_document = WordDocument(io.BytesIO(response.content))
        self.assertIn(
            "Personal Statement",
            [paragraph.text for paragraph in word_document.paragraphs],
        )
        format_with_glm.assert_awaited_once()

    def test_project_export_returns_valid_pdf(self) -> None:
        formatted = document_export.FormattedDocument(
            title="Personal Statement",
            subtitle="Example University | MS Artificial Intelligence",
            paragraphs=self.project.draft.split("\n\n"),
        )
        with patch.object(
            document_export,
            "_format_with_glm",
            new=AsyncMock(return_value=formatted),
        ):
            response = self.client.post(
                f"/api/essay-projects/{self.project.id}/export",
                headers=self.headers,
                json={"format": "pdf"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["content-type"],
            document_export.PDF_MEDIA_TYPE,
        )
        self.assertTrue(response.content.startswith(b"%PDF"))
        reader = PdfReader(io.BytesIO(response.content))
        self.assertGreaterEqual(len(reader.pages), 1)

    def test_export_falls_back_when_glm_is_unavailable(self) -> None:
        with patch.object(
            document_export,
            "_format_with_glm",
            new=AsyncMock(
                side_effect=UpstreamServiceError("model unavailable")
            ),
        ):
            response = self.client.post(
                f"/api/essay-projects/{self.project.id}/export",
                headers=self.headers,
                json={"format": "pdf"},
            )

        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(
            response.headers["x-document-formatting"],
            "fallback",
        )
        self.assertTrue(response.content.startswith(b"%PDF"))

    def test_export_enforces_owner_validation_and_draft_requirements(self) -> None:
        other_owner = self.client.post(
            f"/api/essay-projects/{self.project.id}/export",
            headers={"X-Client-Id": OWNER_B},
            json={"format": "docx"},
        )
        self.assertEqual(other_owner.status_code, 404)

        invalid_format = self.client.post(
            f"/api/essay-projects/{self.project.id}/export",
            headers=self.headers,
            json={"format": "txt"},
        )
        self.assertEqual(invalid_format.status_code, 422)
        self.assertEqual(
            invalid_format.json()["code"],
            "request_validation_failed",
        )

        missing_draft = self.client.post(
            f"/api/essay-projects/{self.empty_project.id}/export",
            headers=self.headers,
            json={"format": "docx"},
        )
        self.assertEqual(missing_draft.status_code, 409)
        self.assertEqual(missing_draft.json()["code"], "draft_required")
