"""Runtime settings. Everything is read from environment variables or backend/.env."""
from __future__ import annotations

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BACKEND_DIR / ".env"), extra="ignore")

    # Storage
    database_url: str = f"sqlite:///{BACKEND_DIR / 'data' / 'agent.db'}"
    data_dir: Path = BACKEND_DIR / "data"

    # Local auth: every API call must send this in the X-Agent-Token header.
    agent_token: str = "change-me-local-token"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    # LLM (optional; the app degrades to deterministic mode without it)
    anthropic_api_key: str | None = None
    llm_model: str = "claude-sonnet-5-5"
    llm_fast_model: str = "claude-haiku-5-5"
    anthropic_web_search_tool: str = "web_search_20250305"

    # Web search provider: auto | anthropic | tavily | brave | serper | none
    search_provider: str = "auto"
    tavily_api_key: str | None = None
    brave_api_key: str | None = None
    serper_api_key: str | None = None
    adzuna_app_id: str | None = None  # free key at developer.adzuna.com; aggregates US job boards legally
    adzuna_app_key: str | None = None

    # Polite fetching
    http_user_agent: str = "SECareerAgent/0.1 (personal job search assistant)"
    fetch_min_interval_s: float = 2.0
    fetch_timeout_s: float = 20.0

    # Career facts used across the engine
    expected_graduation: date = date(2027, 5, 15)
    timezone: str = "America/Phoenix"

    # Scheduler
    enable_scheduler: bool = True

    # Automation. Even when true, nothing with an unverified claim is auto-submitted.
    trusted_auto_submit: bool = False


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "resumes").mkdir(exist_ok=True)
(settings.data_dir / "screenshots").mkdir(exist_ok=True)


def save_env(key: str, value: str | None) -> None:
    """Set or remove one KEY=value line in backend/.env, keeping every other line as it is."""
    path = BACKEND_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out, done = [], False
    for line in lines:
        if line.strip().split("=", 1)[0].strip() == key:
            if value and not done:
                out.append(f"{key}={value}")
                done = True
            continue
        out.append(line)
    if value and not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
