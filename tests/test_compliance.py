"""Tests for the compliance gates and configuration defaults."""

from __future__ import annotations

from datetime import datetime, timezone

from infinity_outreach.compliance import (
    add_to_suppression,
    can_send,
    is_suppressed,
    remaining_daily_budget,
    sent_today_count,
)
from infinity_outreach.config import Settings
from infinity_outreach.models import SentLog


def test_suppression_blocks_email(session):
    add_to_suppression(session, "opted.out@church.org", reason="test")
    session.commit()

    assert is_suppressed(session, "opted.out@church.org") is True
    assert is_suppressed(session, "OPTED.OUT@CHURCH.ORG") is True  # case-insensitive
    assert is_suppressed(session, "fresh@church.org") is False

    allowed, reason = can_send(session, "opted.out@church.org", daily_limit=100)
    assert allowed is False
    assert reason == "suppressed/opted-out"


def test_empty_email_is_never_sendable(session):
    assert is_suppressed(session, "") is True
    allowed, reason = can_send(session, "", daily_limit=100)
    assert allowed is False


def test_suppression_is_idempotent(session):
    assert add_to_suppression(session, "x@y.org") is True
    assert add_to_suppression(session, "x@y.org") is False  # already there


def test_daily_limit_blocks_when_reached(session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for i in range(3):
        session.add(SentLog(email=f"a{i}@b.org", sent_at=now, status="sent"))
    session.commit()

    assert sent_today_count(session) == 3
    assert remaining_daily_budget(session, daily_limit=3) == 0

    allowed, reason = can_send(session, "new@b.org", daily_limit=3)
    assert allowed is False
    assert reason == "daily limit reached"

    # Raising the limit frees up budget again.
    assert remaining_daily_budget(session, daily_limit=5) == 2
    allowed, _ = can_send(session, "new@b.org", daily_limit=5)
    assert allowed is True


def test_draft_only_mode_is_a_valid_default():
    # The shipped default for safety is "review" (never auto-send raw drafts).
    s = Settings(_env_file=None)
    assert s.email_mode in ("draft", "review")
    assert s.require_human_approval is True


def test_daily_limit_value_loads_from_env(monkeypatch):
    monkeypatch.setenv("DAILY_SEND_LIMIT", "777")
    s = Settings(_env_file=None)
    assert s.daily_send_limit == 777
