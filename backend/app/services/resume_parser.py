from __future__ import annotations

import asyncio
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

import pymupdf
from docx import Document
from pypdf import PdfReader

from app.config import get_settings
from app.errors import InputError
from app.services.qwen_client import QwenClient


ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}
OCR_FALLBACK_CODES = {"resume_text_empty", "resume_text_unreadable"}
logger = logging.getLogger(__name__)
qwen_ocr_client = QwenClient()


def is_usable_resume_text(text: str) -> bool:
    visible = "".join(character for character in text if not character.isspace())
    if len(visible) < 12:
        return False
    suspicious = sum(
        character in {"?", "\ufffd", "\u25a1", "\u25a0", "\x00"}
        or not character.isprintable()
        for character in visible
    )
    if suspicious / len(visible) > 0.2:
        return False
    meaningful = sum(
        character.isalnum()
        or character in ".,:;/-+@()[]_%#&!"
        for character in visible
    )
    if meaningful / len(visible) < 0.35:
        return False
    compact = re.sub(r"\s+", "", text)
    if len(compact) >= 20:
        most_common = max(compact.count(character) for character in set(compact))
        if most_common / len(compact) > 0.75:
            return False
    return True


def _validate_resume_text(text: str) -> str:
    cleaned = text.strip()
    if not cleaned:
        raise InputError(
            "No readable text was found in the resume.",
            code="resume_text_empty",
        )
    if not is_usable_resume_text(cleaned):
        raise InputError(
            "The extracted resume text is unreadable. OCR is required.",
            code="resume_text_unreadable",
        )
    settings = get_settings()
    if len(cleaned) > settings.max_resume_text_chars:
        raise InputError(
            f"Resume text exceeds the {settings.max_resume_text_chars}-character limit",
            status_code=413,
            code="resume_text_too_long",
        )
    return cleaned


def extract_resume_text(filename: Optional[str], content: bytes) -> str:
    if not filename or not content:
        raise InputError("A non-empty resume file is required")

    settings = get_settings()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise InputError(
            "Unsupported resume format. Use txt, md, pdf, or docx.",
            code="unsupported_resume_format",
        )

    try:
        if suffix in {".txt", ".md"}:
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                text = content.decode("gb18030")
        elif suffix == ".pdf":
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted:
                raise InputError(
                    "Password-protected PDF resumes are not supported",
                    code="encrypted_resume",
                )
            if len(reader.pages) > settings.max_resume_pages:
                raise InputError(
                    f"Resume exceeds the {settings.max_resume_pages}-page limit",
                    status_code=413,
                    code="resume_too_long",
                )
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            document = Document(BytesIO(content))
            paragraphs = [paragraph.text for paragraph in document.paragraphs]
            for table in document.tables:
                for row in table.rows:
                    paragraphs.append(" | ".join(cell.text for cell in row.cells))
            text = "\n".join(paragraphs)
    except InputError:
        raise
    except Exception as exc:
        raise InputError(
            "The resume file could not be parsed. Check that it is not corrupted.",
            code="resume_parse_failed",
        ) from exc

    return _validate_resume_text(text)


async def extract_resume_text_from_upload(
    filename: Optional[str],
    content: bytes,
) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix != ".pdf":
        return await asyncio.to_thread(extract_resume_text, filename, content)

    try:
        return await asyncio.to_thread(extract_resume_text, filename, content)
    except InputError as exc:
        if exc.code not in OCR_FALLBACK_CODES:
            raise

    logger.info("PDF text layer is unusable; falling back to Qwen OCR")
    ocr_text = await _ocr_pdf_pages(content)
    return _validate_resume_text(ocr_text)


def _render_pdf_pages(content: bytes) -> list[bytes]:
    settings = get_settings()
    try:
        with pymupdf.open(stream=content, filetype="pdf") as document:
            if document.needs_pass:
                raise InputError(
                    "Password-protected PDF resumes are not supported",
                    code="encrypted_resume",
                )
            if document.page_count > settings.max_resume_ocr_pages:
                raise InputError(
                    "Scanned resume exceeds the OCR page limit",
                    status_code=413,
                    code="resume_ocr_too_long",
                )
            pages: list[bytes] = []
            for page in document:
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(2, 2),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                pages.append(pixmap.tobytes("png"))
            return pages
    except InputError:
        raise
    except Exception as exc:
        raise InputError(
            "The resume PDF could not be rendered for OCR.",
            code="resume_parse_failed",
        ) from exc


async def _ocr_pdf_pages(content: bytes) -> str:
    pages = await asyncio.to_thread(_render_pdf_pages, content)
    if not pages:
        raise InputError(
            "No readable text was found in the resume.",
            code="resume_text_empty",
        )
    page_texts = []
    for page in pages:
        page_text = await qwen_ocr_client.ocr_image(page)
        if page_text.strip():
            page_texts.append(page_text.strip())
    if not page_texts:
        raise InputError(
            "OCR did not find readable text in the resume.",
            code="resume_text_unreadable",
        )
    return "\n\n".join(page_texts)
