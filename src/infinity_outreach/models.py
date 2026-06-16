"""SQLAlchemy ORM models — the full data model of the outreach engine.

Tables
------
cities            Country/city worklist (with language for native-tongue email).
organizations     Discovered religious organizations / venues.
contacts          Public email addresses found for an organization.
email_drafts      Generated outreach drafts (bilingual: native + English).
sent_log          Immutable record of every email actually sent.
suppression_list  Addresses that must never be contacted (opt-out / bounce).
task_runs         Audit log of engine tasks (discover/enrich/draft/send).
campaign_settings Singleton row holding the live campaign config from the panel.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_utcnow, onupdate=_utcnow
    )


class City(Base, TimestampMixin):
    __tablename__ = "cities"
    __table_args__ = (UniqueConstraint("city", "country", name="uq_city_country"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    city: Mapped[str] = mapped_column(String(160), index=True)
    country: Mapped[str] = mapped_column(String(120), index=True)
    continent: Mapped[str | None] = mapped_column(String(40), default=None)
    language: Mapped[str | None] = mapped_column(String(60), default=None)
    language_code: Mapped[str | None] = mapped_column(String(8), default=None)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)
    osm_searched: Mapped[bool] = mapped_column(Boolean, default=False)
    google_searched: Mapped[bool] = mapped_column(Boolean, default=False)


class Organization(Base, TimestampMixin):
    __tablename__ = "organizations"
    __table_args__ = (
        UniqueConstraint("source", "source_id", name="uq_org_source"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(300), index=True)
    city: Mapped[str | None] = mapped_column(String(160), index=True)
    country: Mapped[str | None] = mapped_column(String(120), index=True)
    language_code: Mapped[str | None] = mapped_column(String(8), default=None)
    category: Mapped[str | None] = mapped_column(String(120), default=None)
    religion: Mapped[str | None] = mapped_column(String(60), index=True, default=None)
    religion_subtype: Mapped[str | None] = mapped_column(String(60), default=None)
    religion_guess: Mapped[str | None] = mapped_column(String(120), default=None)
    address: Mapped[str | None] = mapped_column(String(400), default=None)
    website: Mapped[str | None] = mapped_column(String(500), default=None)
    phone: Mapped[str | None] = mapped_column(String(60), default=None)
    source: Mapped[str] = mapped_column(String(60), default="manual")
    source_id: Mapped[str | None] = mapped_column(String(200), default=None)
    place_id: Mapped[str | None] = mapped_column(String(200), default=None)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    notes: Mapped[str | None] = mapped_column(Text, default=None)

    contacts: Mapped[list["Contact"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )
    drafts: Mapped[list["EmailDraft"]] = relationship(
        back_populates="organization", cascade="all, delete-orphan"
    )


class Contact(Base, TimestampMixin):
    __tablename__ = "contacts"
    __table_args__ = (UniqueConstraint("email", name="uq_contact_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    contact_page_url: Mapped[str | None] = mapped_column(String(500), default=None)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)

    organization: Mapped["Organization"] = relationship(back_populates="contacts")


class EmailDraft(Base, TimestampMixin):
    __tablename__ = "email_drafts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    contact_id: Mapped[int | None] = mapped_column(
        ForeignKey("contacts.id", ondelete="SET NULL"), default=None
    )
    language_code: Mapped[str | None] = mapped_column(String(8), default=None)
    subject: Mapped[str] = mapped_column(String(400))
    body: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    used_fallback: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, default=None)

    organization: Mapped["Organization"] = relationship(back_populates="drafts")
    contact: Mapped["Contact | None"] = relationship()


class SentLog(Base):
    __tablename__ = "sent_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    draft_id: Mapped[int | None] = mapped_column(
        ForeignKey("email_drafts.id", ondelete="SET NULL"), default=None
    )
    email: Mapped[str] = mapped_column(String(320), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    provider: Mapped[str | None] = mapped_column(String(60), default=None)
    provider_message_id: Mapped[str | None] = mapped_column(String(300), default=None)
    status: Mapped[str] = mapped_column(String(20), default="sent")


class Suppression(Base):
    __tablename__ = "suppression_list"
    __table_args__ = (UniqueConstraint("email", name="uq_suppression_email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    reason: Mapped[str | None] = mapped_column(String(200), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(60), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, default=None)
    details: Mapped[str | None] = mapped_column(Text, default=None)


class ApiCallLog(Base):
    """Lightweight log of every Google Places API call for budget guardrails."""

    __tablename__ = "api_call_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service: Mapped[str] = mapped_column(String(50), index=True)
    endpoint: Mapped[str] = mapped_column(String(100))
    called_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    response_status: Mapped[str | None] = mapped_column(String(20), default=None)


class CampaignSetting(Base, TimestampMixin):
    """Singleton (id=1) holding the live campaign configuration.

    The web panel writes this row; the engine reads it at the start of every
    run so a change you make in the browser is picked up automatically.
    """

    __tablename__ = "campaign_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)

    # Targeting
    religions: Mapped[list] = mapped_column(JSON, default=list)
    regions: Mapped[list] = mapped_column(JSON, default=list)  # continents, in REGION_ORDER
    countries: Mapped[list] = mapped_column(JSON, default=list)
    languages: Mapped[list] = mapped_column(JSON, default=list)

    # Sending policy (mirrors .env but lets you override live from the panel)
    daily_send_limit: Mapped[int] = mapped_column(Integer, default=200)
    email_mode: Mapped[str] = mapped_column(String(20), default="review")
    include_english: Mapped[bool] = mapped_column(Boolean, default=True)
    include_native: Mapped[bool] = mapped_column(Boolean, default=True)
    max_orgs_per_city: Mapped[int] = mapped_column(Integer, default=20)

    # Email content / identity
    sender_name: Mapped[str] = mapped_column(String(160), default="Infinity Faith Team")
    sender_email: Mapped[str] = mapped_column(String(320), default="")
    sender_org: Mapped[str] = mapped_column(String(160), default="Infinity Faith")
    app_name: Mapped[str] = mapped_column(String(160), default="Infinity Faith")
    app_url: Mapped[str] = mapped_column(String(300), default="https://infinityfaith.example")
    subject_hint: Mapped[str] = mapped_column(
        String(300), default="An invitation to try Infinity Faith"
    )
    pitch: Mapped[str] = mapped_column(
        Text,
        default=(
            "Infinity Faith is a multilingual interfaith community app that helps "
            "religious communities share events, discussions and local meetups."
        ),
    )
    extra_instructions: Mapped[str] = mapped_column(Text, default="")

    @staticmethod
    def defaults() -> dict:
        """Field defaults used when seeding the singleton row."""
        from .constants import DEFAULT_RELIGIONS, REGION_ORDER

        return {
            "id": 1,
            "religions": list(DEFAULT_RELIGIONS),
            # Whole world, in order — the loop works Europe first, then the rest.
            "regions": list(REGION_ORDER),
            "countries": [],
            "languages": [],
        }
