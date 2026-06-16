"""Campaign settings + end-to-end orchestration.

This module is the single entry point an agent (Hermes/OpenClaw) or the web
panel calls. It reads the live campaign configuration (written by the panel),
then runs the pipeline:

    discover  ->  enrich  ->  draft  ->  (send)

Each stage is also exposed on its own so you can run them independently from
the CLI. Every run is recorded in ``task_runs``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import discovery, email_sender, email_writer
from .compliance import current_daily_limit, is_suppressed, remaining_daily_budget
from .config import get_settings
from .constants import DEFAULT_RELIGIONS, region_rank
from .email_verify import verify_email
from .models import (
    CampaignSetting,
    City,
    Contact,
    EmailDraft,
    Organization,
    TaskRun,
)
from .optout_scanner import scan_opt_outs
from .website_enricher import enrich_website


# ── Campaign settings (the singleton the panel edits) ───────────────────────
def get_campaign(session: Session) -> CampaignSetting:
    """Fetch the singleton settings row, creating it from env defaults once."""
    row = session.get(CampaignSetting, 1)
    if row is None:
        s = get_settings()
        row = CampaignSetting(
            **CampaignSetting.defaults(),
            daily_send_limit=s.daily_send_limit,
            email_mode=s.email_mode,
            sender_name=s.sender_name,
            sender_email=s.effective_sender_email,
            sender_org=s.sender_org,
            app_url=s.app_url,
        )
        session.add(row)
        session.flush()
    if not row.regions:  # NULL on rows created before the regions column existed
        from .constants import REGION_ORDER

        row.regions = list(REGION_ORDER)
        session.flush()
    return row


def update_campaign(session: Session, **fields) -> CampaignSetting:
    row = get_campaign(session)
    for key, value in fields.items():
        if value is not None and hasattr(row, key):
            setattr(row, key, value)
    session.flush()
    return row


# ── Task-run bookkeeping ────────────────────────────────────────────────────
def _start_task(session: Session, name: str) -> TaskRun:
    run = TaskRun(task_name=name, status="running")
    session.add(run)
    session.flush()
    return run


def _finish_task(session: Session, run: TaskRun, status: str, details: str) -> None:
    run.status = status
    run.finished_at = datetime.now(timezone.utc)
    run.details = details
    session.flush()


@dataclass
class StageStats:
    discovered: int = 0
    enriched_orgs: int = 0
    emails_found: int = 0
    drafted: int = 0
    sent: int = 0
    skipped: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "discovered": self.discovered,
            "enriched_orgs": self.enriched_orgs,
            "emails_found": self.emails_found,
            "drafted": self.drafted,
            "sent": self.sent,
            "skipped": self.skipped,
            "notes": self.notes,
        }


# ── Stage: discovery ────────────────────────────────────────────────────────
def run_discovery(
    session: Session, *, max_cities: int = 5, campaign: CampaignSetting | None = None
) -> StageStats:
    """Discover organizations for pending cities matching the campaign targets."""
    campaign = campaign or get_campaign(session)
    stats = StageStats()
    run = _start_task(session, "discover")

    religion_keys = list(campaign.religions) or list(DEFAULT_RELIGIONS)
    query = select(City).where(City.status == "pending")
    if campaign.regions:
        query = query.where(City.continent.in_(list(campaign.regions)))
    if campaign.countries:
        query = query.where(City.country.in_(list(campaign.countries)))
    # Work the world in region order (Europe first, then NA, Asia, ...), then by id.
    pending = session.execute(query).scalars().all()
    pending.sort(key=lambda c: (region_rank(c.continent), c.id))
    cities = pending[:max_cities]

    if not cities:
        stats.notes.append("No pending cities matched the campaign (seed cities first?).")
        _finish_task(session, run, "done", "no cities")
        return stats

    for city in cities:
        city.status = "processing"
        session.flush()
        try:
            new, osm_done, google_done = discovery.discover_city_hybrid(
                session,
                city=city.city,
                country=city.country,
                language_code=city.language_code,
                religion_keys=religion_keys,
                max_orgs_per_city=campaign.max_orgs_per_city,
            )
            stats.discovered += new
            city.status = "done"
            city.osm_searched = osm_done
            city.google_searched = google_done
        except discovery.DiscoveryUnavailable as exc:
            city.status = "pending"
            stats.notes.append(str(exc))
            _finish_task(session, run, "error", str(exc))
            return stats
        session.commit()

    _finish_task(session, run, "done", f"discovered={stats.discovered}")
    return stats


# ── Stage: enrichment ───────────────────────────────────────────────────────
def run_enrich(session: Session, *, limit: int = 10) -> StageStats:
    """Find public emails for organizations that have a website but no contact."""
    stats = StageStats()
    run = _start_task(session, "enrich")

    orgs = session.execute(
        select(Organization)
        .where(Organization.website.isnot(None), Organization.website != "")
        .where(~Organization.contacts.any())
        .order_by(Organization.id)
        .limit(limit)
    ).scalars().all()

    for org in orgs:
        result = enrich_website(org.website)
        stats.enriched_orgs += 1
        if result.error and not result.emails:
            org.notes = (org.notes or "") + f" [enrich: {result.error}]"
            continue
        for addr in result.emails:
            # Skip undeliverable addresses up front so they never get drafted or
            # sent (dead emails bounce and damage the domain's reputation).
            deliverable, _ = verify_email(addr)
            if not deliverable:
                continue
            contact = Contact(
                organization_id=org.id,
                email=addr,
                contact_page_url=result.contact_page_url,
                confidence=0.6,
                status="new",
            )
            session.add(contact)
            try:
                session.flush()
                stats.emails_found += 1
            except IntegrityError:
                session.rollback()  # email already exists somewhere — skip
        session.commit()

    _finish_task(session, run, "done", f"emails_found={stats.emails_found}")
    return stats


# ── Stage: drafting ─────────────────────────────────────────────────────────
def _pick_contact(session: Session, org: Organization) -> Contact | None:
    contacts = session.execute(
        select(Contact).where(Contact.organization_id == org.id).order_by(Contact.confidence.desc())
    ).scalars().all()
    for c in contacts:
        if c.status != "opted_out" and not is_suppressed(session, c.email):
            return c
    return None


def run_draft(
    session: Session, *, limit: int = 10, campaign: CampaignSetting | None = None
) -> StageStats:
    """Generate a bilingual draft for organizations that have a usable contact."""
    campaign = campaign or get_campaign(session)
    stats = StageStats()
    run = _start_task(session, "draft")

    orgs = session.execute(
        select(Organization)
        .where(Organization.contacts.any())
        .where(~Organization.drafts.any(EmailDraft.status.in_(("draft", "approved", "sent"))))
        .order_by(Organization.id)
        .limit(limit)
    ).scalars().all()

    for org in orgs:
        contact = _pick_contact(session, org)
        if contact is None:
            stats.skipped += 1
            continue
        content = email_writer.build_email(
            org_name=org.name,
            language_code=org.language_code,
        )
        session.add(
            EmailDraft(
                organization_id=org.id,
                contact_id=contact.id,
                language_code=org.language_code,
                subject=content.subject,
                body=content.body,
                status="draft",
                used_fallback=content.used_fallback,
                error=content.error,
            )
        )
        stats.drafted += 1
        if content.used_fallback:
            stats.notes.append(f"org {org.id}: LLM fallback used")
        session.commit()

    _finish_task(session, run, "done", f"drafted={stats.drafted}")
    return stats


# ── Stage: sending ──────────────────────────────────────────────────────────
def run_send(
    session: Session, *, limit: int = 50, campaign: CampaignSetting | None = None
) -> StageStats:
    """Send drafts according to the campaign's email_mode and daily limit."""
    campaign = campaign or get_campaign(session)
    stats = StageStats()
    run = _start_task(session, "send")

    # Sending policy lives in .env (set from VS Code), not the campaign row.
    settings = get_settings()
    mode = settings.email_mode
    daily_limit = current_daily_limit(session)  # warm-up aware

    # First, honour any opt-out replies that arrived.
    suppressed = scan_opt_outs(session)
    if suppressed:
        stats.notes.append(f"auto-suppressed {suppressed} opt-out replies")

    if mode == "draft":
        stats.notes.append("email_mode=draft: nothing is sent automatically.")
        _finish_task(session, run, "done", "draft mode, no send")
        return stats

    statuses = ("approved",) if mode == "review" else ("draft", "approved")
    budget = remaining_daily_budget(session, daily_limit)
    send_limit = min(limit, budget)
    if send_limit <= 0:
        stats.notes.append("daily limit already reached.")
        _finish_task(session, run, "done", "daily limit reached")
        return stats

    try:
        outcomes = email_sender.send_pending(
            session,
            statuses=statuses,
            daily_limit=daily_limit,
            limit=send_limit,
        )
    except email_sender.SenderNotConfigured as exc:
        stats.notes.append(str(exc))
        _finish_task(session, run, "error", str(exc))
        return stats

    stats.sent = sum(1 for o in outcomes if o.sent)
    stats.skipped = sum(1 for o in outcomes if not o.sent)
    _finish_task(session, run, "done", f"sent={stats.sent}")
    return stats


# ── Full pipeline ───────────────────────────────────────────────────────────
def run_pipeline(
    session: Session,
    *,
    max_cities: int = 3,
    enrich_limit: int = 20,
    draft_limit: int = 20,
    send_limit: int = 50,
    do_send: bool = False,
) -> StageStats:
    """Run discover -> enrich -> draft (-> send) once. The agent's main loop."""
    campaign = get_campaign(session)
    total = StageStats()

    d = run_discovery(session, max_cities=max_cities, campaign=campaign)
    e = run_enrich(session, limit=enrich_limit)
    dr = run_draft(session, limit=draft_limit, campaign=campaign)

    total.discovered = d.discovered
    total.enriched_orgs = e.enriched_orgs
    total.emails_found = e.emails_found
    total.drafted = dr.drafted
    total.notes = d.notes + e.notes + dr.notes

    if do_send or get_settings().email_mode == "auto_send":
        s = run_send(session, limit=send_limit, campaign=campaign)
        total.sent = s.sent
        total.notes += s.notes

    return total


# ── Region seeding + work tracking (used by the autonomous loop) ─────────────
def seed_active_region(session: Session, campaign: CampaignSetting | None = None) -> str | None:
    """Ensure the next region in order has its cities seeded.

    Walks ``REGION_ORDER`` restricted to the campaign's selected regions, finds
    the first that still has no cities in the DB, and seeds it. Returns the name
    of the region seeded, or None if every selected region is already seeded.
    """
    from . import seed as seed_mod
    from .constants import REGION_ORDER

    campaign = campaign or get_campaign(session)
    selected = [r for r in REGION_ORDER if r in (campaign.regions or [])]
    seeded_continents = {
        c for (c,) in session.execute(select(City.continent).distinct()).all() if c
    }
    for region in selected:
        if region not in seeded_continents:
            seed_mod.seed_cities(session, only_continents=[region])
            session.commit()
            return region
    return None


def work_summary(session: Session, campaign: CampaignSetting | None = None) -> dict:
    """Counts of remaining work, for the autonomous loop's progress + stop logic."""
    campaign = campaign or get_campaign(session)

    city_q = select(City).where(City.status == "pending")
    if campaign.regions:
        city_q = city_q.where(City.continent.in_(list(campaign.regions)))
    pending_list = session.execute(city_q).scalars().all()
    pending_cities = len(pending_list)
    pending_continents = {c.continent for c in pending_list if c.continent}

    enrich_pending = len(
        session.execute(
            select(Organization)
            .where(Organization.website.isnot(None), Organization.website != "")
            .where(~Organization.contacts.any())
        ).scalars().all()
    )
    draft_pending = len(
        session.execute(
            select(Organization)
            .where(Organization.contacts.any())
            .where(~Organization.drafts.any(EmailDraft.status.in_(("draft", "approved", "sent"))))
        ).scalars().all()
    )
    sendable = len(
        session.execute(
            select(EmailDraft).where(EmailDraft.status.in_(("draft", "approved")))
        ).scalars().all()
    )

    from .constants import REGION_ORDER

    selected = [r for r in REGION_ORDER if r in (campaign.regions or [])]
    seeded_continents = {
        c for (c,) in session.execute(select(City.continent).distinct()).all() if c
    }
    unseeded_regions = [r for r in selected if r not in seeded_continents]

    # The region currently being worked = first selected region (in order) that
    # still has work: either not yet seeded, or with cities still pending.
    active_region = next(
        (r for r in selected if r in unseeded_regions or r in pending_continents),
        None,
    )

    return {
        "pending_cities": pending_cities,
        "enrich_pending": enrich_pending,
        "draft_pending": draft_pending,
        "sendable": sendable,
        "unseeded_regions": unseeded_regions,
        "active_region": active_region,
    }
