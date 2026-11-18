from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Optional

from docx import Document
from pypdf import PdfReader

from app.config import get_settings
from app.errors import InputError


ALLOWED_SUFFIXES = {".txt", ".md", ".pdf", ".docx"}


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

    text = text.strip()
    if not text:
        raise InputError(
            "No readable text was found in the resume. Scanned PDFs are not supported.",
            code="resume_text_empty",
        )
    if len(text) > settings.max_resume_text_chars:
        raise InputError(
            f"Resume text exceeds the {settings.max_resume_text_chars}-character limit",
            status_code=413,
            code="resume_text_too_long",
        )
    return text
