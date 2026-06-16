"""Send approved drafts through your own mailbox (Gmail / Workspace via SMTP).

Hard rules enforced here, every single send:
  * never send to a suppressed / opted-out address (compliance.can_send)
  * never exceed the configured daily limit
  * record every send in sent_log
  * one message at a time, with a polite delay between sends

Gmail / Google Workspace: use an *App Password* (Account > Security > App
passwords), not your normal login password. Free Gmail allows ~500 sends/day;
Workspace ~2000/day — keep DAILY_SEND_LIMIT under your real cap.
"""

from __future__ import annotations

import re
import smtplib
import ssl
import time
import uuid
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .compliance import can_send
from .config import get_settings
from .models import Contact, EmailDraft, Organization, SentLog


class SenderNotConfigured(RuntimeError):
    pass


@dataclass
class SendOutcome:
    draft_id: int
    email: str
    sent: bool
    reason: str
    message_id: str | None = None


def _html_to_text(html: str) -> str:
    """Best-effort plain-text fallback from the HTML body (for the text/plain part)."""
    text = re.sub(r"(?i)<br\s*/?>", "\n", html)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)<hr\s*/?>", "\n----------\n", text)
    text = re.sub(r"<[^>]+>", "", text)            # drop remaining tags
    text = re.sub(r"\n{3,}", "\n\n", text)          # collapse blank runs
    return text.strip()


def _build_message(
    *, subject: str, body: str, to_email: str, from_name: str, from_email: str
) -> MIMEMultipart:
    """Build a multipart/alternative message. ``body`` is HTML (template output)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email))
    msg["To"] = to_email
    msg["Message-ID"] = make_msgid()
    # Order matters: text/plain first, then the HTML the recipient actually sees.
    msg.attach(MIMEText(_html_to_text(body), "plain", "utf-8"))
    msg.attach(MIMEText(f"<html><body>{body}</body></html>", "html", "utf-8"))
    return msg


class SmtpSender:
    """Reusable SMTP connection wrapper (SSL or STARTTLS)."""

    def __init__(self) -> None:
        s = get_settings()
        if not s.smtp_configured():
            raise SenderNotConfigured(
                "SMTP is not configured. Set SMTP_HOST, SMTP_USER and "
                "SMTP_PASSWORD (use a Gmail App Password) in .env."
            )
        self._s = s
        self._server: smtplib.SMTP | smtplib.SMTP_SSL | None = None

    def __enter__(self) -> "SmtpSender":
        ctx = ssl.create_default_context()
        if self._s.smtp_port == 465:
            self._server = smtplib.SMTP_SSL(
                self._s.smtp_host, self._s.smtp_port, context=ctx, timeout=30
            )
        else:
            self._server = smtplib.SMTP(self._s.smtp_host, self._s.smtp_port, timeout=30)
            self._server.starttls(context=ctx)
        self._server.login(self._s.smtp_user, self._s.smtp_password)
        return self

    def __exit__(self, *exc) -> None:
        if self._server is not None:
            try:
                self._server.quit()
            except Exception:
                pass
            self._server = None

    def send(self, msg: MIMEMultipart, to_email: str) -> str:
        assert self._server is not None
        from_email = self._s.effective_sender_email or self._s.smtp_user
        self._server.sendmail(from_email, [to_email], msg.as_string())
        return msg["Message-ID"] or f"<{uuid.uuid4()}@local>"


def _record_send(
    session: Session, *, draft: EmailDraft, email: str, message_id: str | None, status: str
) -> None:
    session.add(
        SentLog(
            draft_id=draft.id,
            email=email,
            provider="smtp",
            provider_message_id=message_id,
            status=status,
        )
    )


def send_draft(
    session: Session,
    draft: EmailDraft,
    *,
    daily_limit: int,
    sender: SmtpSender,
) -> SendOutcome:
    """Send one draft if compliance allows. Updates the draft + sent_log."""
    settings = get_settings()
    contact = None
    if draft.contact_id is not None:
        contact = session.get(Contact, draft.contact_id)
    if contact is None:
        contact = session.execute(
            select(Contact).where(Contact.organization_id == draft.organization_id)
        ).scalars().first()

    if contact is None or not contact.email:
        draft.status = "failed"
        draft.error = "no contact email"
        return SendOutcome(draft.id, "", False, "no contact email")

    email = contact.email
    allowed, reason = can_send(session, email, daily_limit)
    if not allowed:
        return SendOutcome(draft.id, email, False, reason)

    msg = _build_message(
        subject=draft.subject,
        body=draft.body,
        to_email=email,
        from_name=settings.sender_name,
        from_email=settings.effective_sender_email or settings.smtp_user,
    )
    try:
        message_id = sender.send(msg, email)
    except Exception as exc:  # noqa: BLE001
        draft.status = "failed"
        draft.error = f"send error: {exc}"
        _record_send(session, draft=draft, email=email, message_id=None, status="failed")
        return SendOutcome(draft.id, email, False, f"send error: {exc}")

    draft.status = "sent"
    draft.error = None
    _record_send(session, draft=draft, email=email, message_id=message_id, status="sent")
    org = session.get(Organization, draft.organization_id)
    if org is not None:
        org.status = "contacted"
    return SendOutcome(draft.id, email, True, "sent", message_id=message_id)


def send_pending(
    session: Session,
    *,
    statuses: tuple[str, ...],
    daily_limit: int,
    limit: int,
    delay_seconds: float | None = None,
) -> list[SendOutcome]:
    """Send up to ``limit`` drafts whose status is in ``statuses``.

    ``statuses`` is typically ("approved",) in review mode or
    ("draft", "approved") in auto_send mode.
    """
    settings = get_settings()
    delay = settings.send_delay_seconds if delay_seconds is None else delay_seconds

    drafts = session.execute(
        select(EmailDraft).where(EmailDraft.status.in_(statuses)).order_by(EmailDraft.id)
    ).scalars().all()

    outcomes: list[SendOutcome] = []
    sent = 0
    with SmtpSender() as sender:
        for draft in drafts:
            if sent >= limit:
                break
            outcome = send_draft(session, draft, daily_limit=daily_limit, sender=sender)
            outcomes.append(outcome)
            session.commit()  # persist each send immediately (crash-safe)
            if outcome.sent:
                sent += 1
                if delay > 0:
                    time.sleep(delay)
            elif outcome.reason == "daily limit reached":
                break
    return outcomes
