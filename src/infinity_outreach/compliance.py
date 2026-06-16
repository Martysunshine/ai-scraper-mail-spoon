"""Compliance gates: suppression list and daily send budget.

These checks sit in front of every send. They protect the recipient (no contact
after opt-out) and protect the sender's mailbox/domain reputation (hard daily
cap). Keeping them in one place makes the rules auditable.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
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


# ── Domain warm-up ──────────────────────────────────────────────────────────
def _warmup_start_date(session: Session, settings) -> date | None:
    """Date the ramp is anchored to: explicit WARMUP_START_DATE, else the date of
    the first email ever sent. None means nothing has been sent yet (day 0)."""
    raw = (settings.warmup_start_date or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    first = session.execute(
        select(func.min(SentLog.sent_at)).where(SentLog.status == "sent")
    ).scalar_one_or_none()
    return first.date() if first else None


def current_daily_limit(session: Session) -> int:
    """Effective daily send cap for today.

    With warm-up off, this is simply DAILY_SEND_LIMIT. With it on, the limit ramps
    from WARMUP_START, multiplying by WARMUP_MULTIPLIER every WARMUP_EVERY_DAYS
    days, never exceeding DAILY_SEND_LIMIT (the ceiling).
    """
    s = get_settings()
    cap = s.daily_send_limit
    if not s.warmup_enabled:
        return cap
    start = _warmup_start_date(session, s)
    steps = 0
    if start is not None:
        days = max(0, (date.today() - start).days)
        steps = days // max(1, s.warmup_every_days)
    value = s.warmup_start * (s.warmup_multiplier ** steps)
    return int(min(cap, round(value)))


def warmup_status(session: Session) -> dict:
    """Human-readable warm-up state for dashboards / stats."""
    s = get_settings()
    out: dict = {
        "enabled": s.warmup_enabled,
        "current": current_daily_limit(session),
        "cap": s.daily_send_limit,
    }
    if not s.warmup_enabled:
        return out
    start = _warmup_start_date(session, s)
    if start is None:  # not sending yet — clock starts at the first send
        nv = int(min(s.daily_send_limit, round(s.warmup_start * s.warmup_multiplier)))
        out.update({"day": 0, "next_bump_in_days": s.warmup_every_days, "next_value": nv, "start_date": None})
        return out
    days = max(0, (date.today() - start).days)
    steps = days // max(1, s.warmup_every_days)
    next_val = int(min(s.daily_send_limit, round(s.warmup_start * s.warmup_multiplier ** (steps + 1))))
    out.update({
        "day": days,
        "start_date": start.isoformat(),
        "next_bump_in_days": s.warmup_every_days - (days % s.warmup_every_days),
        "next_value": next_val,
    })
    return out


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
