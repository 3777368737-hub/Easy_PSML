from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import BaseModel, Field


BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")


class Settings(BaseModel):
    deepseek_api_key: str = Field(default=os.getenv("DEEPSEEK_API_KEY", ""))
    deepseek_base_url: str = Field(
        default=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    )
    deepseek_model: str = Field(
        default=os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    )
    deepseek_temperature: float = Field(
        default=float(os.getenv("DEEPSEEK_TEMPERATURE", "0.25")),
        ge=0,
        le=1,
    )
    deepseek_timeout_seconds: float = Field(
        default=float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS", "120")),
        ge=10,
        le=300,
    )
    deepseek_max_retries: int = Field(
        default=int(os.getenv("DEEPSEEK_MAX_RETRIES", "2")),
        ge=0,
        le=4,
    )
    qwen_api_key: str = Field(
        default=os.getenv("QWEN_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    )
    qwen_base_url: str = Field(
        default=os.getenv(
            "QWEN_BASE_URL",
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )
    )
    qwen_intent_model: str = Field(
        default=os.getenv("QWEN_INTENT_MODEL", "qwen-plus-latest")
    )
    qwen_asr_model: str = Field(
        default=os.getenv(
            "QWEN_ASR_MODEL",
            "qwen-audio-3.1-asr-flash-streaming",
        )
    )
    qwen_asr_file_model: str = Field(
        default=os.getenv(
            "QWEN_ASR_FILE_MODEL",
            "qwen-audio-3.1-asr-flash",
        )
    )
    qwen_asr_ws_url: str = Field(
        default=os.getenv("QWEN_ASR_WS_URL", "")
    )
    qwen_asr_vad_model: str = Field(
        default=os.getenv("QWEN_ASR_VAD_MODEL", "near_meeting_16k")
    )
    qwen_asr_max_sentence_silence_ms: int = Field(
        default=int(os.getenv("QWEN_ASR_MAX_SENTENCE_SILENCE_MS", "1200")),
        ge=200,
        le=6000,
    )
    qwen_temperature: float = Field(
        default=float(os.getenv("QWEN_TEMPERATURE", "0.1")),
        ge=0,
        le=1,
    )
    qwen_timeout_seconds: float = Field(
        default=float(os.getenv("QWEN_TIMEOUT_SECONDS", "90")),
        ge=10,
        le=300,
    )
    qwen_max_retries: int = Field(
        default=int(os.getenv("QWEN_MAX_RETRIES", "2")),
        ge=0,
        le=4,
    )
    document_export_model: str = Field(
        default=os.getenv(
            "DOCUMENT_EXPORT_MODEL",
            "ZHIPU/GLM-5.3-Flash",
        )
    )
    document_export_base_url: str = Field(
        default=os.getenv(
            "DOCUMENT_EXPORT_BASE_URL",
            os.getenv(
                "QWEN_BASE_URL",
                "https://dashscope.aliyuncs.com/compatible-mode/v1",
            ),
        )
    )
    document_export_timeout_seconds: float = Field(
        default=float(os.getenv("DOCUMENT_EXPORT_TIMEOUT_SECONDS", "120")),
        ge=10,
        le=300,
    )
    document_export_max_retries: int = Field(
        default=int(os.getenv("DOCUMENT_EXPORT_MAX_RETRIES", "1")),
        ge=0,
        le=3,
    )
    document_export_max_tokens: int = Field(
        default=int(os.getenv("DOCUMENT_EXPORT_MAX_TOKENS", "7000")),
        ge=512,
        le=12000,
    )
    qwen_asr_language: str = Field(
        default=os.getenv("QWEN_ASR_LANGUAGE", "zh"),
        max_length=16,
    )
    voice_max_audio_bytes: int = Field(
        default=int(os.getenv("VOICE_MAX_AUDIO_BYTES", str(6 * 1024 * 1024))),
        ge=64 * 1024,
        le=10 * 1024 * 1024,
    )
    database_path: str = Field(
        default=os.getenv(
            "DATABASE_PATH",
            str(BACKEND_DIR / "data" / "gradpilot.db"),
        )
    )
    cors_origins: List[str] = Field(
        default_factory=lambda: list(
            dict.fromkeys(
                [
                    "http://localhost:3000",
                    "http://127.0.0.1:3000",
                    *[
                        origin.strip()
                        for origin in os.getenv("APP_CORS_ORIGINS", "").split(",")
                        if origin.strip()
                    ],
                ]
            )
        )
    )
    max_upload_bytes: int = Field(
        default=int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))),
        ge=1024,
    )
    max_resume_text_chars: int = Field(
        default=int(os.getenv("MAX_RESUME_TEXT_CHARS", "60000")),
        ge=1000,
    )
    max_resume_pages: int = Field(
        default=int(os.getenv("MAX_RESUME_PAGES", "30")),
        ge=1,
        le=200,
    )
    model_calls_per_window: int = Field(
        default=int(os.getenv("MODEL_CALLS_PER_WINDOW", "40")),
        ge=1,
    )
    model_rate_window_seconds: int = Field(
        default=int(os.getenv("MODEL_RATE_WINDOW_SECONDS", "600")),
        ge=60,
    )

    @property
    def resolved_database_path(self) -> Path:
        path = Path(self.database_path)
        if not path.is_absolute():
            path = BACKEND_DIR / path
        return path.resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
