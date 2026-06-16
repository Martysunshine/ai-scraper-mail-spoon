"""Command-line interface for the Infinity Outreach Agent.

Run as a module:           python -m infinity_outreach.cli --help
Or (if package complex):   python src/infinity_outreach/cli.py --help
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

# Ensure src/ is always on the path regardless of how the script is invoked.
_src = str(Path(__file__).resolve().parents[1])
if _src not in sys.path:
    sys.path.insert(0, _src)

import typer
from rich.console import Console
from rich.table import Table

from infinity_outreach import campaign as campaign_mod
from infinity_outreach import seed as seed_mod
from infinity_outreach.compliance import (
    add_to_suppression,
    current_daily_limit,
    sent_today_count,
    warmup_status,
)
from infinity_outreach.config import EXPORTS_DIR, get_settings
from infinity_outreach.db import init_db, session_scope
from infinity_outreach.models import (
    CampaignSetting,
    City,
    Contact,
    EmailDraft,
    Organization,
    SentLog,
)
from infinity_outreach.ollama_client import OllamaUnavailable, check_connection

app = typer.Typer(
    add_completion=False,
    help="Infinity Outreach Agent — discover, enrich, draft and send respectful outreach.",
    no_args_is_help=True,
)
console = Console()


# ── Setup / data ────────────────────────────────────────────────────────────
@app.command("init-db")
def cmd_init_db() -> None:
    """Create all database tables."""
    init_db()
    with session_scope() as s:
        campaign_mod.get_campaign(s)  # seed singleton settings row
    console.print("[green]Database initialised.[/green]")


@app.command("seed-cities")
def cmd_seed_cities(
    countries: str = typer.Option(
        "", "--countries", help="Comma-separated country names to limit seeding."
    ),
) -> None:
    """Seed the cities worklist from official_languages_by_country.csv."""
    only = [c.strip() for c in countries.split(",") if c.strip()] or None
    with session_scope() as s:
        added = seed_mod.seed_cities(s, only_countries=only)
    console.print(f"[green]Seeded {added} new cities.[/green]")


@app.command("write-cities-csv")
def cmd_write_cities_csv() -> None:
    """Generate data/cities.csv from the languages CSV."""
    path = seed_mod.write_cities_csv()
    console.print(f"[green]Wrote {path}[/green]")


@app.command("import-cities")
def cmd_import_cities(csv_path: str) -> None:
    """Import cities from a CSV (columns: city,country[,language,language_code])."""
    path = Path(csv_path)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)
    added = 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh, session_scope() as s:
        reader = csv.DictReader(fh)
        existing = {(c.city, c.country) for c in s.query(City).all()}
        for row in reader:
            city = (row.get("city") or "").strip()
            country = (row.get("country") or "").strip()
            if not city or not country or (city, country) in existing:
                continue
            s.add(
                City(
                    city=city,
                    country=country,
                    language=(row.get("language") or "").strip() or None,
                    language_code=(row.get("language_code") or "").strip() or None,
                    status="pending",
                )
            )
            existing.add((city, country))
            added += 1
    console.print(f"[green]Imported {added} cities.[/green]")


@app.command("import-orgs")
def cmd_import_orgs(csv_path: str) -> None:
    """Import organizations from a CSV (see data/sample_organizations.csv)."""
    path = Path(csv_path)
    if not path.exists():
        console.print(f"[red]File not found: {path}[/red]")
        raise typer.Exit(1)
    added = 0
    with path.open("r", encoding="utf-8-sig", newline="") as fh, session_scope() as s:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            s.add(
                Organization(
                    name=name,
                    city=(row.get("city") or "").strip() or None,
                    country=(row.get("country") or "").strip() or None,
                    category=(row.get("category") or "").strip() or None,
                    religion=(row.get("religion") or row.get("religion_guess") or "").strip() or None,
                    religion_guess=(row.get("religion_guess") or "").strip() or None,
                    address=(row.get("address") or "").strip() or None,
                    website=(row.get("website") or "").strip() or None,
                    phone=(row.get("phone") or "").strip() or None,
                    source=(row.get("source") or "manual_import").strip(),
                    source_id=(row.get("source_id") or "").strip() or None,
                    notes=(row.get("notes") or "").strip() or None,
                    status="new",
                )
            )
            added += 1
    console.print(f"[green]Imported {added} organizations.[/green]")


# ── LLM ─────────────────────────────────────────────────────────────────────
@app.command("test-llm")
def cmd_test_llm() -> None:
    """Check the local Ollama connection."""
    try:
        model = check_connection()
        console.print("[green]Local Ollama connection works.[/green]")
        console.print(f"Model: {model}")
    except OllamaUnavailable as exc:
        console.print("[red]Local Ollama connection failed.[/red]")
        console.print(str(exc))
        raise typer.Exit(1)


# ── Pipeline stages ─────────────────────────────────────────────────────────
@app.command("discover")
def cmd_discover(max_cities: int = typer.Option(5, "--max-cities")) -> None:
    """Discover organizations for pending cities (needs GOOGLE_PLACES_API_KEY)."""
    with session_scope() as s:
        stats = campaign_mod.run_discovery(s, max_cities=max_cities)
    _print_stats("Discovery", stats)


@app.command("enrich")
def cmd_enrich(limit: int = typer.Option(10, "--limit")) -> None:
    """Find public emails on organizations' websites."""
    with session_scope() as s:
        stats = campaign_mod.run_enrich(s, limit=limit)
    _print_stats("Enrichment", stats)


@app.command("draft")
def cmd_draft(limit: int = typer.Option(10, "--limit")) -> None:
    """Generate bilingual outreach drafts for organizations with a contact."""
    with session_scope() as s:
        stats = campaign_mod.run_draft(s, limit=limit)
    _print_stats("Drafting", stats)


@app.command("send")
def cmd_send(limit: int = typer.Option(50, "--limit")) -> None:
    """Send drafts per the campaign's email_mode and daily limit (REAL emails)."""
    with session_scope() as s:
        stats = campaign_mod.run_send(s, limit=limit)
    _print_stats("Sending", stats)


@app.command("run")
def cmd_run(
    max_cities: int = typer.Option(3, "--max-cities"),
    enrich_limit: int = typer.Option(20, "--enrich-limit"),
    draft_limit: int = typer.Option(20, "--draft-limit"),
    send_limit: int = typer.Option(50, "--send-limit"),
    do_send: bool = typer.Option(False, "--send", help="Also send (respects mode/limit)."),
) -> None:
    """Run the full pipeline once: discover -> enrich -> draft (-> send)."""
    with session_scope() as s:
        stats = campaign_mod.run_pipeline(
            s,
            max_cities=max_cities,
            enrich_limit=enrich_limit,
            draft_limit=draft_limit,
            send_limit=send_limit,
            do_send=do_send,
        )
    _print_stats("Pipeline", stats)


@app.command("send-test")
def cmd_send_test(
    to: str = typer.Argument(..., help="Recipient address for the test email."),
    org: str = typer.Option("Sample Community Church", "--org", help="Org name used in the greeting."),
    lang: str = typer.Option("en", "--lang", help="Language code (e.g. en, cs, de)."),
) -> None:
    """Send ONE real test email (the live template + signature) to an address.

    Bypasses the pipeline, suppression list, daily limit and EMAIL_MODE — it is an
    explicit manual test, so it sends regardless of those. Use it to confirm your
    SMTP credentials work and to see exactly how the email renders in an inbox.
    """
    from infinity_outreach import email_sender
    from infinity_outreach.email_writer import build_email

    settings = get_settings()
    content = build_email(org_name=org, language_code=lang)
    try:
        with email_sender.SmtpSender() as sender:
            msg = email_sender._build_message(
                subject=content.subject,
                body=content.body,
                to_email=to,
                from_name=settings.sender_name,
                from_email=settings.effective_sender_email or settings.smtp_user,
            )
            message_id = sender.send(msg, to)
    except email_sender.SenderNotConfigured as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Send failed:[/red] {exc}")
        raise typer.Exit(1)
    console.print(
        f"[green]Test email sent[/green] to [bold]{to}[/bold] "
        f"from {settings.effective_sender_email or settings.smtp_user} "
        f"(subject: {content.subject!r}, message-id {message_id})."
    )


@app.command("auto")
def cmd_auto() -> None:
    """Run the FULL pipeline autonomously and continuously until everything is done.

    Discover → enrich → draft → send, region by region, respecting daily limits,
    resuming cleanly after any stop. This is the single command an AI agent runs.
    Honours EMAIL_MODE: 'draft' (default) drafts but never sends; set it to
    'auto_send' in .env to go live. Stop with `cli stop` or Ctrl-C.
    """
    from infinity_outreach import autorun

    init_db()
    autorun.run_forever()


@app.command("stop")
def cmd_stop() -> None:
    """Ask a running `auto` loop to stop gracefully after its current step."""
    from infinity_outreach.config import STOP_FILE

    STOP_FILE.parent.mkdir(parents=True, exist_ok=True)
    STOP_FILE.write_text("stop", encoding="utf-8")
    console.print(f"[yellow]Stop requested.[/yellow] The auto loop will exit shortly ({STOP_FILE}).")


@app.command("export-orgs")
def cmd_export_orgs(
    csv_path: str = typer.Argument("", help="Output CSV path (default: data/exports/organizations.csv)."),
) -> None:
    """Write the deliverable table: every org + what was sent."""
    from infinity_outreach.reporting import write_orgs_report

    out = Path(csv_path) if csv_path else None
    with session_scope() as s:
        path = write_orgs_report(s, out)
    console.print(f"[green]Wrote organizations report to {path}[/green]")


@app.command("scan-optouts")
def cmd_scan_optouts() -> None:
    """Scan the mailbox (IMAP) for unsubscribe replies and suppress them."""
    from infinity_outreach.optout_scanner import scan_opt_outs

    with session_scope() as s:
        n = scan_opt_outs(s)
    console.print(f"[green]Suppressed {n} opt-out replies.[/green]")


# ── Listings ────────────────────────────────────────────────────────────────
@app.command("list-orgs")
def cmd_list_orgs(limit: int = typer.Option(50, "--limit")) -> None:
    """List organizations."""
    with session_scope() as s:
        orgs = s.query(Organization).order_by(Organization.id).limit(limit).all()
        table = Table(title="Organizations")
        for col in ("ID", "Name", "City", "Country", "Religion", "Website", "Contacts"):
            table.add_column(col, overflow="fold")
        for o in orgs:
            table.add_row(
                str(o.id), o.name, o.city or "", o.country or "",
                o.religion or "", o.website or "", str(len(o.contacts)),
            )
    console.print(table)


@app.command("list-drafts")
def cmd_list_drafts(limit: int = typer.Option(50, "--limit")) -> None:
    """List email drafts (id, organization, email, subject, status)."""
    with session_scope() as s:
        drafts = s.query(EmailDraft).order_by(EmailDraft.id).limit(limit).all()
        table = Table(title="Email drafts")
        for col in ("ID", "Org", "Email", "Subject", "Status", "Fallback"):
            table.add_column(col, overflow="fold")
        for d in drafts:
            org = s.get(Organization, d.organization_id)
            contact = s.get(Contact, d.contact_id) if d.contact_id else None
            table.add_row(
                str(d.id), org.name if org else "?",
                contact.email if contact else "", d.subject,
                d.status, "yes" if d.used_fallback else "",
            )
    console.print(table)


@app.command("show-draft")
def cmd_show_draft(draft_id: int) -> None:
    """Print the full body of one draft."""
    with session_scope() as s:
        d = s.get(EmailDraft, draft_id)
        if not d:
            console.print(f"[red]Draft {draft_id} not found.[/red]")
            raise typer.Exit(1)
        console.print(f"[bold]Subject:[/bold] {d.subject}\n")
        console.print(d.body)


@app.command("approve-draft")
def cmd_approve_draft(draft_id: int) -> None:
    """Mark a draft as approved (eligible to send in review mode)."""
    _set_draft_status(draft_id, "approved")


@app.command("reject-draft")
def cmd_reject_draft(draft_id: int) -> None:
    """Mark a draft as rejected (never sent)."""
    _set_draft_status(draft_id, "rejected")


@app.command("suppress")
def cmd_suppress(email: str, reason: str = typer.Option("manual", "--reason")) -> None:
    """Add an email to the suppression / opt-out list."""
    with session_scope() as s:
        added = add_to_suppression(s, email, reason=reason)
    console.print(
        f"[green]Suppressed {email}.[/green]" if added else f"[yellow]{email} already suppressed.[/yellow]"
    )


@app.command("export-drafts")
def cmd_export_drafts(
    csv_path: str = typer.Argument("", help="Output CSV path (default: data/exports/drafts.csv)."),
) -> None:
    """Export drafts to CSV for manual review."""
    out = Path(csv_path) if csv_path else (EXPORTS_DIR / "drafts.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with session_scope() as s, out.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["draft_id", "organization", "email", "subject", "status", "body"])
        for d in s.query(EmailDraft).order_by(EmailDraft.id).all():
            org = s.get(Organization, d.organization_id)
            contact = s.get(Contact, d.contact_id) if d.contact_id else None
            writer.writerow([
                d.id, org.name if org else "", contact.email if contact else "",
                d.subject, d.status, d.body,
            ])
    console.print(f"[green]Exported drafts to {out}[/green]")


@app.command("stats")
def cmd_stats() -> None:
    """Show a quick status summary."""
    with session_scope() as s:
        settings = get_settings()
        c = campaign_mod.get_campaign(s)
        table = Table(title="Infinity Outreach — status")
        table.add_column("Metric")
        table.add_column("Value", justify="right")
        table.add_row("Cities (pending)", str(s.query(City).filter(City.status == "pending").count()))
        table.add_row("Organizations", str(s.query(Organization).count()))
        table.add_row("Contacts", str(s.query(Contact).count()))
        table.add_row("Drafts", str(s.query(EmailDraft).count()))
        table.add_row("Approved drafts", str(s.query(EmailDraft).filter(EmailDraft.status == "approved").count()))
        table.add_row("Sent (all time)", str(s.query(SentLog).filter(SentLog.status == "sent").count()))
        ws = warmup_status(s)
        table.add_row("Sent today", str(sent_today_count(s)))
        table.add_row("Daily limit (today)", str(ws["current"]))
        if ws["enabled"]:
            table.add_row(
                "Warm-up",
                f"on · day {ws.get('day', 0)} · cap {ws['cap']} · "
                f"next {ws.get('next_value', '?')}/day in {ws.get('next_bump_in_days', '?')}d",
            )
        table.add_row("Email mode (.env)", settings.email_mode)
        table.add_row("Religions", ", ".join(c.religions))
        table.add_row("Regions", " -> ".join(c.regions) if c.regions else "—")
        table.add_row("SMTP configured", "yes" if settings.smtp_configured() else "no")
        table.add_row("Places API key", "yes" if settings.places_configured() else "no (OSM only)")
    console.print(table)


@app.command("web")
def cmd_web(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8000, "--port"),
) -> None:
    """Launch the local web control panel."""
    import uvicorn

    # Ensure the project root (containing the `web` package) is importable.
    root = Path(__file__).resolve().parents[2]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    console.print(f"[green]Control panel:[/green] http://{host}:{port}")
    uvicorn.run("web.app:app", host=host, port=port, reload=False)


# ── Helpers ─────────────────────────────────────────────────────────────────
def _set_draft_status(draft_id: int, status: str) -> None:
    with session_scope() as s:
        d = s.get(EmailDraft, draft_id)
        if not d:
            console.print(f"[red]Draft {draft_id} not found.[/red]")
            raise typer.Exit(1)
        d.status = status
    console.print(f"[green]Draft {draft_id} -> {status}.[/green]")


def _print_stats(title: str, stats) -> None:
    table = Table(title=title)
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    for k, v in stats.as_dict().items():
        if k == "notes":
            continue
        table.add_row(k, str(v))
    console.print(table)
    for note in stats.as_dict().get("notes", []):
        console.print(f"[yellow]• {note}[/yellow]")


if __name__ == "__main__":
    app()
