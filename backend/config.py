"""Application configuration loaded from environment variables."""

import os
import logging
from dotenv import load_dotenv

load_dotenv(override=True)

logger = logging.getLogger(__name__)


class Settings:
    """Centralised configuration. Reads from .env / process environment."""

    # --- Xunfei ASR ---
    XUNFEI_APP_ID: str = os.getenv("XUNFEI_APP_ID", "")
    XUNFEI_API_KEY: str = os.getenv("XUNFEI_API_KEY", "")
    XUNFEI_API_SECRET: str = os.getenv("XUNFEI_API_SECRET", "")

    # --- AI Model ---
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_BASE_URL: str = os.getenv("OPENAI_BASE_URL", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "mimo-v2-pro")
    XIAOMI_OMNI_MODEL: str = os.getenv("XIAOMI_OMNI_MODEL", "mimo-v2-omni")

    # --- ASR Selection ---
    ASR_ENGINE: str = os.getenv("ASR_ENGINE", "whisper")  # options: "xiaomi", "whisper", "xunfei"
    WHISPER_MODEL_SIZE: str = os.getenv("WHISPER_MODEL_SIZE", "base")

    # --- Feishu ---
    FEISHU_APP_ID: str = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET: str = os.getenv("FEISHU_APP_SECRET", "")

    # --- Knowledge Base sync ---
    # Base URL of the KB system (e.g. https://kb.tokenwave.cloud), no trailing /api.
    KB_BASE_URL: str = os.getenv("KNOWLEDGE_BASE_BASE_URL", "").rstrip("/")
    KB_USERNAME: str = os.getenv("KNOWLEDGE_BASE_USERNAME", "")
    KB_PASSWORD: str = os.getenv("KNOWLEDGE_BASE_PASSWORD", "")
    KB_DEFAULT_DOC_TYPE: str = os.getenv("KNOWLEDGE_BASE_DEFAULT_DOC_TYPE", "meeting_notes")

    @property
    def kb_enabled(self) -> bool:
        """KB sync is available only when all credentials are configured."""
        return bool(self.KB_BASE_URL and self.KB_USERNAME and self.KB_PASSWORD)

    # --- Database ---
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./meeting_ai.db")

    # --- WebSocket ---
    WS_AUTH_TOKEN: str = os.getenv("WS_AUTH_TOKEN", "")

    # --- CORS ---
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
        if origin.strip()
    ]

    # --- Storage ---
    BASE_DIR: str = os.path.dirname(os.path.abspath(__file__))
    UPLOAD_DIR: str = os.path.join(BASE_DIR, "uploads")

    def validate(self) -> None:
        """Log warnings for missing critical env vars."""
        required = [
            ("XUNFEI_APP_ID", self.XUNFEI_APP_ID),
            ("XUNFEI_API_KEY", self.XUNFEI_API_KEY),
            ("XUNFEI_API_SECRET", self.XUNFEI_API_SECRET),
            ("WS_AUTH_TOKEN", self.WS_AUTH_TOKEN),
        ]
        for name, value in required:
            if not value:
                logger.warning("Environment variable %s is not set", name)


settings = Settings()
