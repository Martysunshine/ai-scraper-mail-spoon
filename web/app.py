"""FastAPI control panel for the Infinity Outreach Agent.

What you configure here is written to the ``campaign_settings`` table, which the
engine (and your Hermes/OpenClaw agents) read at the start of every run — so a
change you make in the browser is picked up automatically by the next run.

Run it with:   python -m infinity_outreach.cli web
Then open:     http://127.0.0.1:8000
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the engine importable when run from the project root.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
for p in (str(ROOT), str(SRC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

from fastapi import BackgroundTasks, FastAPI, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from infinity_outreach import campaign as campaign_mod
from infinity_outreach.compliance import add_to_suppression, sent_today_count
from infinity_outreach.config import get_settings
from infinity_outreach.constants import RELIGIONS
from infinity_outreach.db import init_db, session_scope
from infinity_outreach.models import (
    ApiCallLog,
    City,
    Contact,
    EmailDraft,
    Organization,
    SentLog,
    TaskRun,
)
from infinity_outreach.seed import country_language_index, seed_cities

@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Ensure tables + the singleton settings row exist before serving.
    init_db()
    with session_scope() as s:
        campaign_mod.get_campaign(s)
    yield


app = FastAPI(title="Infinity Outreach — Control Panel", lifespan=lifespan)
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")


def _redirect(path: str, msg: str = "") -> RedirectResponse:
    url = f"{path}?msg={msg}" if msg else path
    return RedirectResponse(url=url, status_code=303)


# ── Dashboard ───────────────────────────────────────────────────────────────
@app.get("/")
def dashboard(request: Request, msg: str = ""):
    settings = get_settings()
    with session_scope() as s:
        campaign = campaign_mod.get_campaign(s)
        metrics = {
            "cities_pending": s.query(City).filter(City.status == "pending").count(),
            "cities_done": s.query(City).filter(City.status == "done").count(),
            "cities_total": s.query(City).count(),
            "cities_osm": s.query(City).filter(City.osm_searched == True).count(),
            "cities_google": s.query(City).filter(City.google_searched == True).count(),
            "organizations": s.query(Organization).count(),
            "orgs_new": s.query(Organization).filter(Organization.status == "new").count(),
            "orgs_contacted": s.query(Organization).filter(Organization.status == "contacted").count(),
            "contacts": s.query(Contact).count(),
            "drafts": s.query(EmailDraft).count(),
            "approved": s.query(EmailDraft).filter(EmailDraft.status == "approved").count(),
            "sent_total": s.query(SentLog).filter(SentLog.status == "sent").count(),
            "sent_today": sent_today_count(s),
        }
        recent_runs = s.query(TaskRun).order_by(TaskRun.id.desc()).limit(8).all()
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        places_calls_today = s.query(ApiCallLog).filter(ApiCallLog.called_at >= today_start).count()
        ctx = {
            "request": request,
            "page": "dashboard",
            "msg": msg,
            "metrics": metrics,
            "campaign": campaign,
            "settings": settings,
            "recent_runs": recent_runs,
            "smtp_ok": settings.smtp_configured(),
            "places_ok": settings.places_configured(),
            "places_calls_today": places_calls_today,
            "places_daily_limit": settings.places_daily_limit,
        }
    return templates.TemplateResponse(request, "dashboard.html", ctx)


# ── Settings (campaign configuration) ───────────────────────────────────────
@app.get("/settings")
def settings_page(request: Request, msg: str = ""):
    with session_scope() as s:
        campaign = campaign_mod.get_campaign(s)
        ctx = {
            "request": request,
            "page": "settings",
            "msg": msg,
            "campaign": campaign,
            "religions": RELIGIONS,
            "countries": country_language_index(),
        }
    return templates.TemplateResponse(request, "settings.html", ctx)


@app.post("/settings")
async def settings_save(request: Request):
    form = await request.form()
    religions = form.getlist("religions")
    countries = form.getlist("countries")

    # Countries arrive as "Country||language" so we can also record languages.
    parsed_countries = []
    parsed_languages = set()
    for value in countries:
        name, _, lang = value.partition("||")
        parsed_countries.append(name)
        if lang:
            parsed_languages.add(lang)

    def _int(name: str, default: int) -> int:
        try:
            return int(form.get(name, default))
        except (TypeError, ValueError):
            return default

    with session_scope() as s:
        campaign_mod.update_campaign(
            s,
            religions=religions or None,
            countries=parsed_countries or [],
            languages=sorted(parsed_languages),
            daily_send_limit=_int("daily_send_limit", 200),
            max_orgs_per_city=_int("max_orgs_per_city", 20),
            email_mode=form.get("email_mode") or "review",
            include_native=form.get("include_native") == "on",
            include_english=form.get("include_english") == "on",
            sender_name=form.get("sender_name") or None,
            sender_email=form.get("sender_email") or None,
            sender_org=form.get("sender_org") or None,
            app_name=form.get("app_name") or None,
            app_url=form.get("app_url") or None,
            subject_hint=form.get("subject_hint") or None,
            pitch=form.get("pitch") or None,
            extra_instructions=form.get("extra_instructions") or "",
        )
    return _redirect("/settings", "Settings saved. The engine will use them on the next run.")


# ── Worklist actions ────────────────────────────────────────────────────────
@app.post("/actions/seed-cities")
def action_seed_cities():
    with session_scope() as s:
        campaign = campaign_mod.get_campaign(s)
        only = campaign.countries or None
        added = seed_cities(s, only_countries=only)
    return _redirect("/", f"Seeded {added} cities.")


def _bg_run(stage: str) -> None:
    """Background worker for long-running stages."""
    with session_scope() as s:
        if stage == "discover":
            campaign_mod.run_discovery(s, max_cities=5)
        elif stage == "enrich":
            campaign_mod.run_enrich(s, limit=20)
        elif stage == "draft":
            campaign_mod.run_draft(s, limit=20)
        elif stage == "send":
            campaign_mod.run_send(s, limit=50)
        elif stage == "pipeline":
            campaign_mod.run_pipeline(s, max_cities=3, do_send=False)


@app.post("/actions/{stage}")
def action_stage(stage: str, background: BackgroundTasks):
    valid = {"discover", "enrich", "draft", "send", "pipeline"}
    if stage not in valid:
        return _redirect("/", "Unknown action.")
    background.add_task(_bg_run, stage)
    return _redirect("/", f"Started '{stage}' in the background. Refresh to see results.")


# ── Organizations ───────────────────────────────────────────────────────────
@app.get("/organizations")
def organizations_page(request: Request, msg: str = ""):
    with session_scope() as s:
        orgs = s.query(Organization).order_by(Organization.id.desc()).limit(200).all()
        rows = [
            {
                "id": o.id,
                "name": o.name,
                "city": o.city,
                "country": o.country,
                "religion": o.religion,
                "website": o.website,
                "contacts": len(o.contacts),
            }
            for o in orgs
        ]
    return templates.TemplateResponse(
        request,
        "organizations.html",
        {"request": request, "page": "organizations", "msg": msg, "orgs": rows},
    )


# ── Drafts (review queue) ───────────────────────────────────────────────────
@app.get("/drafts")
def drafts_page(request: Request, msg: str = "", status: str = ""):
    with session_scope() as s:
        q = s.query(EmailDraft).order_by(EmailDraft.id.desc())
        if status:
            q = q.filter(EmailDraft.status == status)
        drafts = q.limit(200).all()
        rows = []
        for d in drafts:
            org = s.get(Organization, d.organization_id)
            contact = s.get(Contact, d.contact_id) if d.contact_id else None
            rows.append(
                {
                    "id": d.id,
                    "org": org.name if org else "?",
                    "email": contact.email if contact else "",
                    "subject": d.subject,
                    "body": d.body,
                    "status": d.status,
                    "fallback": d.used_fallback,
                }
            )
    return templates.TemplateResponse(
        request,
        "drafts.html",
        {"request": request, "page": "drafts", "msg": msg, "drafts": rows, "status": status},
    )


@app.post("/drafts/{draft_id}/{action}")
def draft_action(draft_id: int, action: str):
    mapping = {"approve": "approved", "reject": "rejected", "draft": "draft"}
    if action not in mapping:
        return _redirect("/drafts", "Unknown draft action.")
    with session_scope() as s:
        d = s.get(EmailDraft, draft_id)
        if d:
            d.status = mapping[action]
    return _redirect("/drafts", f"Draft {draft_id} -> {mapping[action]}.")


@app.post("/suppress")
def suppress(email: str = Form(...)):
    with session_scope() as s:
        add_to_suppression(s, email, reason="panel")
    return _redirect("/drafts", f"Suppressed {email}.")


# ── Logs ────────────────────────────────────────────────────────────────────
@app.get("/logs")
def logs_page(request: Request, msg: str = ""):
    with session_scope() as s:
        runs = s.query(TaskRun).order_by(TaskRun.id.desc()).limit(100).all()
        sent = s.query(SentLog).order_by(SentLog.id.desc()).limit(50).all()
        run_rows = [
            {
                "id": r.id,
                "task": r.task_name,
                "status": r.status,
                "started": r.started_at,
                "finished": r.finished_at,
                "details": r.details,
            }
            for r in runs
        ]
        sent_rows = [
            {"id": x.id, "email": x.email, "sent_at": x.sent_at, "status": x.status}
            for x in sent
        ]
    return templates.TemplateResponse(
        request,
        "logs.html",
        {"request": request, "page": "logs", "msg": msg, "runs": run_rows, "sent": sent_rows},
    )


# ── JSON status (handy for agents) ──────────────────────────────────────────
@app.get("/api/status")
def api_status():
    settings = get_settings()
    with session_scope() as s:
        campaign = campaign_mod.get_campaign(s)
        today_start = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
        places_calls_today = s.query(ApiCallLog).filter(ApiCallLog.called_at >= today_start).count()
        return {
            "app": settings.app_name,
            "email_mode": campaign.email_mode,
            "daily_send_limit": campaign.daily_send_limit,
            "sent_today": sent_today_count(s),
            "religions": campaign.religions,
            "countries": campaign.countries,
            "organizations": s.query(Organization).count(),
            "orgs_contacted": s.query(Organization).filter(Organization.status == "contacted").count(),
            "cities_done": s.query(City).filter(City.status == "done").count(),
            "cities_osm_searched": s.query(City).filter(City.osm_searched == True).count(),
            "cities_google_searched": s.query(City).filter(City.google_searched == True).count(),
            "drafts": s.query(EmailDraft).count(),
            "smtp_configured": settings.smtp_configured(),
            "places_configured": settings.places_configured(),
            "places_calls_today": places_calls_today,
            "places_daily_limit": settings.places_daily_limit,
            "places_calls_remaining": max(0, settings.places_daily_limit - places_calls_today),
        }
