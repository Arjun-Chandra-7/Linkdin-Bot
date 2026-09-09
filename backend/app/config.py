"""Environment-level configuration.

Only infrastructure and secrets live here. Anything the user should be able to
change from the Android app (posting times, category mix, thresholds) lives in
the ``settings`` database table instead - see ``app.core.settings_store``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- App ----
    app_env: str = "development"
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"
    log_json: bool = False

    # ---- Database ----
    database_url: str = f"sqlite:///{DATA_DIR / 'copilot.db'}"

    # ---- Security ----
    # Used to derive the pairing-code pepper and to sign nothing else; device
    # tokens are random secrets stored only as Argon2 hashes.
    secret_key: str = Field(default="dev-only-insecure-change-me")
    pairing_code_ttl_seconds: int = 600
    token_bytes: int = 32
    # Refuse to boot with the default secret outside development.
    allow_insecure_secret: bool = False

    # ---- LLM ----
    llm_provider: str = "mock"  # mock | anthropic | openai
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 120.0

    # ---- LinkedIn publishing ----
    # manual  -> system prepares copy-ready content + reminder, user posts.
    # api     -> official LinkedIn REST API (requires an authorised token).
    # Browser automation is deliberately not an option.
    linkedin_publish_mode: str = "manual"
    linkedin_access_token: str = ""
    linkedin_author_urn: str = ""  # e.g. urn:li:person:XXXX
    linkedin_api_version: str = "202405"

    # ---- Jobs / scheduler ----
    job_tick_seconds: int = 20
    job_max_attempts: int = 5
    scheduler_enabled: bool = True

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return settings
