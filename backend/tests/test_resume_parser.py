from __future__ import annotations

import unittest
from io import BytesIO
from unittest.mock import AsyncMock, patch

from reportlab.pdfgen import canvas

from app.errors import InputError
from app.services import resume_parser


def make_pdf(text: str | None = None) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer)
    if text:
        y = 800
        for line in text.splitlines():
            pdf.drawString(72, y, line)
            y -= 20
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


class ResumeParserTests(unittest.IsolatedAsyncioTestCase):
    def test_text_quality_rejects_replacement_glyphs(self) -> None:
        self.assertTrue(
            resume_parser.is_usable_resume_text(
                "Alex Chen\nComputer Science\nResearch experience"
            )
        )
        self.assertFalse(resume_parser.is_usable_resume_text("?\n?????????????"))

    async def test_text_pdf_uses_local_extraction_before_ocr(self) -> None:
        content = make_pdf(
            "Alex Chen\nComputer Science\nResearch experience in retrieval."
        )
        with patch.object(
            resume_parser.qwen_ocr_client,
            "ocr_image",
            new=AsyncMock(return_value="unexpected OCR"),
        ) as ocr:
            text = await resume_parser.extract_resume_text_from_upload(
                "resume.pdf",
                content,
            )

        self.assertIn("Alex Chen", text)
        ocr.assert_not_awaited()

    async def test_blank_pdf_falls_back_to_ocr(self) -> None:
        ocr_text = (
            "Alex Chen\n"
            "Current University: Example University\n"
            "Major: Computer Science\n"
            "Research experience in information retrieval."
        )
        with patch.object(
            resume_parser.qwen_ocr_client,
            "ocr_image",
            new=AsyncMock(return_value=ocr_text),
        ) as ocr:
            text = await resume_parser.extract_resume_text_from_upload(
                "scanned.pdf",
                make_pdf(),
            )

        self.assertEqual(text, ocr_text)
        ocr.assert_awaited_once()

    async def test_unreadable_ocr_output_returns_clear_error(self) -> None:
        with patch.object(
            resume_parser.qwen_ocr_client,
            "ocr_image",
            new=AsyncMock(return_value="????????????????????"),
        ):
            with self.assertRaises(InputError) as raised:
                await resume_parser.extract_resume_text_from_upload(
                    "scanned.pdf",
                    make_pdf(),
                )

        self.assertEqual(raised.exception.code, "resume_text_unreadable")
