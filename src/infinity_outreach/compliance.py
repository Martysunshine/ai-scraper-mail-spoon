"""Compliance gates: suppression list and daily send budget.

These checks sit in front of every send. They protect the recipient (no contact
after opt-out) and protect the sender's mailbox/domain reputation (hard daily
cap). Keeping them in one place makes the rules auditable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import SentLog, Suppression


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def is_suppressed(session: Session, email: str) -> bool:
    """True if the address is on the opt-out / suppression list."""
    addr = normalize_email(email)
    if not addr:
        return True  # empty address is never sendable
    stmt = select(Suppression.id).where(Suppression.email == addr).limit(1)
    return session.execute(stmt).first() is not None


def add_to_suppression(session: Session, email: str, reason: str = "manual") -> bool:
    """Add an address to the suppression list. Returns True if newly added."""
    addr = normalize_email(email)
    if not addr:
        return False
    if is_suppressed(session, addr):
        return False
    session.add(Suppression(email=addr, reason=reason))
    session.flush()
    return True


def sent_today_count(session: Session, *, now: datetime | None = None) -> int:
    """How many emails were sent since 00:00 UTC today."""
    now = now or datetime.now(timezone.utc)
    start_of_day = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    stmt = select(func.count(SentLog.id)).where(
        SentLog.sent_at >= start_of_day.replace(tzinfo=None),
        SentLog.status == "sent",
    )
    return int(session.execute(stmt).scalar_one())


def remaining_daily_budget(session: Session, daily_limit: int) -> int:
    """Sends still allowed today (never negative)."""
    return max(0, daily_limit - sent_today_count(session))


def can_send(session: Session, email: str, daily_limit: int) -> tuple[bool, str]:
    """Combined gate. Returns (allowed, reason_if_blocked)."""
    addr = normalize_email(email)
    if not addr:
        return False, "empty email"
    if is_suppressed(session, addr):
        return False, "suppressed/opted-out"
    if remaining_daily_budget(session, daily_limit) <= 0:
        return False, "daily limit reached"
    return True, "ok"
