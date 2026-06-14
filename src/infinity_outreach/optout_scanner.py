"""Optional IMAP opt-out scanner.

Scans the configured mailbox for replies that say "unsubscribe" / "stop" /
"remove me" and automatically adds those senders to the suppression list, so
the agent honours opt-outs without a human in the loop. Entirely optional — if
IMAP credentials are not set, this no-ops.
"""

from __future__ import annotations

import email
import imaplib
import re
from email.utils import parseaddr

from sqlalchemy.orm import Session

from .compliance import add_to_suppression
from .config import get_settings

_OPT_OUT_RE = re.compile(
    r"\b(unsubscribe|opt[\s-]?out|remove me|stop|no more email|do not contact)\b",
    re.IGNORECASE,
)


def imap_configured() -> bool:
    s = get_settings()
    return bool(s.imap_host and s.imap_user and s.imap_password)


def _body_text(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    return part.get_payload(decode=True).decode(errors="ignore")
                except Exception:
                    continue
        return ""
    try:
        return msg.get_payload(decode=True).decode(errors="ignore")
    except Exception:
        return str(msg.get_payload())


def scan_opt_outs(session: Session, *, since_days: int = 14, max_messages: int = 200) -> int:
    """Scan recent unread mail for opt-out language. Returns count suppressed."""
    if not imap_configured():
        return 0
    s = get_settings()
    added = 0
    try:
        conn = imaplib.IMAP4_SSL(s.imap_host, s.imap_port)
        conn.login(s.imap_user, s.imap_password)
        conn.select("INBOX")
        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK":
            conn.logout()
            return 0
        ids = data[0].split()[-max_messages:]
        for num in ids:
            typ, msg_data = conn.fetch(num, "(RFC822)")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            subject = str(msg.get("Subject", ""))
            sender = parseaddr(str(msg.get("From", "")))[1]
            text = f"{subject}\n{_body_text(msg)}"
            if sender and _OPT_OUT_RE.search(text):
                if add_to_suppression(session, sender, reason="email opt-out"):
                    added += 1
        session.commit()
        conn.logout()
    except Exception:
        # Never let a mailbox hiccup crash the pipeline.
        return added
    return added
