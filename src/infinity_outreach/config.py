"""Centralised configuration loaded from the environment / .env file.

Everything tunable lives here so the engine, the CLI and the web panel all read
the same values. Nothing here contains secrets by default — secrets come from a
local, git-ignored ``.env``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Make Python's TLS trust the OS certificate store (Windows/macOS). Corporate
# proxies and antivirus HTTPS scanners inject their own root CA into the OS
# store but not into certifi, which otherwise breaks every outbound HTTPS call
# (OSM, Google Places, website enrichment, SMTP) with CERTIFICATE_VERIFY_FAILED.
# This trusts the OS store — it does NOT disable verification. Optional import.
try:
    import truststore as _truststore

    _truststore.inject_into_ssl()
except Exception:  # noqa: BLE001 — truststore is optional; fall back to certifi
    pass

# Repository root = three levels up from this file:
#   src/infinity_outreach/config.py -> src/infinity_outreach -> src -> ROOT
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
PROMPTS_DIR = PROJECT_ROOT / "prompts"
EXPORTS_DIR = DATA_DIR / "exports"

# Load .env from the project root before Settings reads the environment.
load_dotenv(PROJECT_ROOT / ".env")


class Settings(BaseSettings):
    """Strongly-typed view over the environment."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_name: str = Field(default="Infinity Outreach Agent", alias="APP_NAME")

    # Database
    database_url: str = Field(
        default="sqlite:///data/outreach.sqlite", alias="DATABASE_URL"
    )

    # Local LLM (Ollama, OpenAI-compatible)
    ollama_base_url: str = Field(
        default="http://127.0.0.1:11434/v1", alias="OLLAMA_BASE_URL"
    )
    ollama_model: str = Field(default="hermes3", alias="OLLAMA_MODEL")
    ollama_api_key: str = Field(default="ollama", alias="OLLAMA_API_KEY")

    # Sending behaviour
    # draft -> never send (dry run); review -> only approved; auto_send -> send new drafts.
    email_mode: str = Field(default="draft", alias="EMAIL_MODE")
    require_human_approval: bool = Field(default=True, alias="REQUIRE_HUMAN_APPROVAL")
    daily_send_limit: int = Field(default=200, alias="DAILY_SEND_LIMIT")
    send_delay_seconds: float = Field(default=20.0, alias="SEND_DELAY_SECONDS")

    # Automatic domain warm-up: ramp the effective daily limit from WARMUP_START
    # up to DAILY_SEND_LIMIT, multiplying by WARMUP_MULTIPLIER every
    # WARMUP_EVERY_DAYS days. Anchored to WARMUP_START_DATE, else the first send.
    warmup_enabled: bool = Field(default=False, alias="WARMUP_ENABLED")
    warmup_start: int = Field(default=50, alias="WARMUP_START")
    warmup_multiplier: float = Field(default=1.25, alias="WARMUP_MULTIPLIER")
    warmup_every_days: int = Field(default=3, alias="WARMUP_EVERY_DAYS")
    warmup_start_date: str = Field(default="", alias="WARMUP_START_DATE")

    # Email content (the body comes from email_templates/, only the subject is here)
    email_subject: str = Field(
        default="An invitation to try Infinity Faith", alias="EMAIL_SUBJECT"
    )
    email_template_dir: str = Field(default="email_templates", alias="EMAIL_TEMPLATE_DIR")

    # Autonomous loop (`cli auto`)
    auto_cycle_seconds: float = Field(default=60.0, alias="AUTO_CYCLE_SECONDS")
    auto_discover_batch: int = Field(default=3, alias="AUTO_DISCOVER_BATCH")
    # Share of each discovery batch reserved for re-visiting OSM-fallback cities
    # with Google (the rest goes to new cities) — splits the daily Google budget.
    auto_revisit_ratio: float = Field(default=0.30, alias="AUTO_REVISIT_RATIO")

    # Discovery
    google_places_api_key: str = Field(default="", alias="GOOGLE_PLACES_API_KEY")
    search_provider: str = Field(default="google_places", alias="SEARCH_PROVIDER")
    places_daily_limit: int = Field(default=300, alias="PLACES_DAILY_LIMIT")

    # Website enrichment
    request_timeout: int = Field(default=15, alias="REQUEST_TIMEOUT")
    request_delay_seconds: float = Field(default=2.0, alias="REQUEST_DELAY_SECONDS")
    user_agent: str = Field(
        default="InfinityOutreachBot/0.2 (+https://infinityfaith.example)",
        alias="USER_AGENT",
    )

    # Outbound mailbox
    smtp_host: str = Field(default="smtp.gmail.com", alias="SMTP_HOST")
    smtp_port: int = Field(default=465, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    sender_name: str = Field(default="Infinity Faith Team", alias="SENDER_NAME")
    sender_email: str = Field(default="", alias="SENDER_EMAIL")
    sender_org: str = Field(default="Infinity Faith", alias="SENDER_ORG")
    app_url: str = Field(default="https://infinityfaith.example", alias="APP_URL")

    # Opt-out scanner (IMAP)
    imap_host: str = Field(default="imap.gmail.com", alias="IMAP_HOST")
    imap_port: int = Field(default=993, alias="IMAP_PORT")
    imap_user: str = Field(default="", alias="IMAP_USER")
    imap_password: str = Field(default="", alias="IMAP_PASSWORD")

    # ── Derived helpers ────────────────────────────────────────────────────
    @property
    def effective_sender_email(self) -> str:
        """The address mail is actually sent from (falls back to SMTP user)."""
        return self.sender_email or self.smtp_user

    @property
    def sqlite_path(self) -> Path | None:
        """Absolute path of the SQLite file, if the DB is SQLite."""
        prefix = "sqlite:///"
        if self.database_url.startswith(prefix):
            raw = self.database_url[len(prefix):]
            p = Path(raw)
            return p if p.is_absolute() else (PROJECT_ROOT / p)
        return None

    def smtp_configured(self) -> bool:
        return bool(self.smtp_host and self.smtp_user and self.smtp_password)

    def places_configured(self) -> bool:
        return bool(self.google_places_api_key)


def ensure_runtime_dirs() -> None:
    """Create the directories the engine writes to (idempotent)."""
    for d in (DATA_DIR, LOGS_DIR, EXPORTS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def template_dir() -> Path:
    """Absolute path to the email-templates folder (from EMAIL_TEMPLATE_DIR)."""
    raw = Path(get_settings().email_template_dir)
    return raw if raw.is_absolute() else (PROJECT_ROOT / raw)


# Sentinel file the autonomous loop watches for a graceful stop request.
STOP_FILE = DATA_DIR / "STOP"
# The deliverable the agent regenerates: every org + what was sent.
ORGS_EXPORT = EXPORTS_DIR / "organizations.csv"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton."""
    ensure_runtime_dirs()
    return Settings()


def reload_settings() -> Settings:
    """Drop the cache and re-read the environment (used after the panel writes)."""
    get_settings.cache_clear()
    return get_settings()
