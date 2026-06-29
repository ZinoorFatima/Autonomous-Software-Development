"""Centralised configuration, loaded from environment / `.env`.

All secrets and tunables live here so nothing is hard-coded elsewhere.
"""
from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Project root = two levels up from this file (src/agent/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Autonomy(str, Enum):
    """How much the agent does without pausing for a human."""

    CHECKPOINT = "checkpoint"  # pause for approval after plan / before commit / before PR
    AUTO = "auto"  # run the whole pipeline end-to-end


class Settings(BaseSettings):
    """Application settings sourced from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Secrets ---
    gemini_api_key: str = Field(default="", description="Google AI Studio API key")
    github_token: str = Field(default="", description="GitHub fine-grained PAT")

    # --- Models ---
    gemini_model_pro: str = Field(default="gemini-2.5-pro")
    gemini_model_flash: str = Field(default="gemini-2.5-flash")

    # --- Behaviour ---
    max_debug_retries: int = Field(default=3, ge=0, le=10)
    autonomy: Autonomy = Field(default=Autonomy.CHECKPOINT)

    # --- Workspace ---
    workspace_root: str = Field(default="workspaces")

    @property
    def workspace_path(self) -> Path:
        """Absolute path under which per-run repo clones are created."""
        root = Path(self.workspace_root)
        if not root.is_absolute():
            root = PROJECT_ROOT / root
        return root

    def require_gemini(self) -> str:
        if not self.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Copy .env.example to .env and add your key "
                "(https://aistudio.google.com/apikey)."
            )
        return self.gemini_api_key

    def require_github(self) -> str:
        if not self.github_token:
            raise RuntimeError(
                "GITHUB_TOKEN is not set. Copy .env.example to .env and add a fine-grained "
                "PAT with Contents/PRs/Issues read-write."
            )
        return self.github_token


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
