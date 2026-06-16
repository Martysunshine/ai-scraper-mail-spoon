"""The deliverable table: every organization + what was sent.

``write_orgs_report`` regenerates ``data/exports/organizations.csv`` from the
database. The autonomous loop refreshes it each cycle, and the CLI exposes it as
``export-orgs`` so an operator (or the agent) always has an up-to-date table of
who was found and who was contacted.
"""

from __future__ import annotations

import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import ORGS_EXPORT
from .models import Contact, EmailDraft, Organization, SentLog

_COLUMNS = [
    "id",
    "name",
    "religion",
    "city",
    "country",
    "language_code",
    "website",
    "email",
    "status",        # new | contacted
    "drafted",       # yes | ""
    "sent_at",       # ISO timestamp of the send, if any
    "source",        # osm | google_places | manual_import | ...
]


def write_orgs_report(session: Session, path: Path | None = None) -> Path:
    """Write one row per organization to CSV. Returns the path written."""
    out = path or ORGS_EXPORT
    out.parent.mkdir(parents=True, exist_ok=True)

    orgs = session.execute(select(Organization).order_by(Organization.id)).scalars().all()
    with out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(_COLUMNS)
        for o in orgs:
            contact = session.execute(
                select(Contact).where(Contact.organization_id == o.id).order_by(Contact.id)
            ).scalars().first()
            draft = session.execute(
                select(EmailDraft).where(EmailDraft.organization_id == o.id).order_by(EmailDraft.id)
            ).scalars().first()
            sent_at = ""
            if draft is not None:
                sent = session.execute(
                    select(SentLog)
                    .where(SentLog.draft_id == draft.id, SentLog.status == "sent")
                    .order_by(SentLog.id.desc())
                ).scalars().first()
                if sent is not None and sent.sent_at is not None:
                    sent_at = sent.sent_at.isoformat(timespec="seconds")
            writer.writerow([
                o.id,
                o.name,
                o.religion or "",
                o.city or "",
                o.country or "",
                o.language_code or "",
                o.website or "",
                contact.email if contact else "",
                o.status,
                "yes" if draft is not None else "",
                sent_at,
                o.source,
            ])
    return out
