"""The single autonomous command: discover → enrich → draft → send, forever.

An AI agent (or a person) runs ``cli auto`` once. This loop then drives the whole
pipeline continuously, region by region, until every targeted organization has
been found and contacted — which may take hours, days or weeks.

Design guarantees
-----------------
* **Resumable.** All progress lives in the database (city status, org status,
  drafts, sent_log). Stopping and restarting picks up exactly where it left off
  and never re-contacts an organization.
* **Graceful stop.** Writing ``data/STOP`` (via ``cli stop``) or pressing Ctrl-C
  finishes the current step, writes the report, and exits cleanly.
* **Self-pacing.** Respects the Google Places daily budget (OSM is the free
  primary source) and the email daily-send limit. When a cap is hit it keeps
  cycling and drains over the following days.
* **Dry-run first.** Honours ``EMAIL_MODE``: with the shipped default ``draft``
  it discovers and drafts but sends nothing, so you can inspect real drafts
  before flipping ``EMAIL_MODE=auto_send`` to go live.
"""

from __future__ import annotations

import signal
import time
from datetime import datetime, timezone

from .compliance import sent_today_count
from .config import STOP_FILE, get_settings
from .db import session_scope
from . import campaign as campaign_mod
from .discovery import _count_calls_today
from .models import TaskRun
from .reporting import write_orgs_report

_stop_requested = False


def _request_stop(signum, _frame) -> None:  # noqa: ANN001
    global _stop_requested
    _stop_requested = True
    print("\n[auto] stop requested — finishing the current step, then exiting…", flush=True)


def _install_signal_handlers() -> None:
    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, sig_name, None)
        if sig is not None:
            try:
                signal.signal(sig, _request_stop)
            except (ValueError, OSError):
                pass  # not in main thread / unsupported on this platform


def _should_stop() -> bool:
    if _stop_requested:
        return True
    if STOP_FILE.exists():
        print("[auto] STOP file found — exiting cleanly.", flush=True)
        return True
    return False


def _clear_stop_file() -> None:
    try:
        STOP_FILE.unlink()
    except OSError:
        pass


def _heartbeat(session, *, region: str | None, summary: dict) -> str:
    """Write a TaskRun heartbeat row and return a one-line human status."""
    sent_today = sent_today_count(session)
    settings = get_settings()
    google_used = _count_calls_today(session)
    google_left = max(0, settings.places_daily_limit - google_used)

    line = (
        f"region={region or '—'} | pending_cities={summary['pending_cities']} "
        f"enrich={summary['enrich_pending']} draft={summary['draft_pending']} "
        f"sendable={summary['sendable']} | sent_today={sent_today}/{settings.daily_send_limit} "
        f"| google_left={google_left} | mode={settings.email_mode}"
    )
    run = TaskRun(
        task_name="auto",
        status="running",
        details=line,
        finished_at=datetime.now(timezone.utc),
    )
    session.add(run)
    session.flush()
    return line


def _run_one_cycle() -> tuple[bool, str]:
    """Run a single discover→enrich→draft→send pass.

    Returns (done, status_line). ``done`` is True when there is no work left.
    """
    settings = get_settings()
    with session_scope() as session:
        campaign = campaign_mod.get_campaign(session)

        # 1. Make sure the active region has cities seeded.
        region = campaign_mod.seed_active_region(session, campaign)

        # 2. The pipeline, one batch each.
        campaign_mod.run_discovery(
            session, max_cities=settings.auto_discover_batch, campaign=campaign
        )
        campaign_mod.run_enrich(session, limit=20)
        campaign_mod.run_draft(session, limit=20, campaign=campaign)
        if settings.email_mode in ("review", "auto_send"):
            campaign_mod.run_send(session, limit=settings.daily_send_limit, campaign=campaign)

        # 3. Status + report.
        summary = campaign_mod.work_summary(session, campaign)
        active_region = summary.get("active_region") or region
        line = _heartbeat(session, region=active_region, summary=summary)
        write_orgs_report(session)

        # 4. Are we done?
        #    Discovery + enrichment + drafting all exhausted, every region seeded.
        pipeline_done = (
            summary["pending_cities"] == 0
            and not summary["unseeded_regions"]
            and summary["enrich_pending"] == 0
            and summary["draft_pending"] == 0
        )
        # In a dry run (draft/review) that is enough. In auto_send we are only
        # done once every draft has actually gone out (sendable drained); while
        # the daily cap blocks remaining sends, sendable stays > 0 and we keep
        # cycling so they drain over the following days.
        done = pipeline_done and (
            settings.email_mode != "auto_send" or summary["sendable"] == 0
        )
        return done, line


def run_forever() -> None:
    """Entry point for ``cli auto``. Loops until done or a stop is requested."""
    _install_signal_handlers()
    _clear_stop_file()  # a stale STOP from a previous run shouldn't kill this one
    settings = get_settings()
    cycle = 0
    print(
        f"[auto] starting — mode={settings.email_mode}, "
        f"cycle={settings.auto_cycle_seconds:.0f}s, discover_batch={settings.auto_discover_batch}. "
        f"Stop with `cli stop` or Ctrl-C.",
        flush=True,
    )

    while not _should_stop():
        cycle += 1
        try:
            done, line = _run_one_cycle()
        except Exception as exc:  # noqa: BLE001 — never let one bad cycle kill the loop
            print(f"[auto] cycle {cycle} error: {exc} — retrying next cycle.", flush=True)
            if _sleep_interruptible(settings.auto_cycle_seconds):
                break
            continue

        print(f"[auto] cycle {cycle}: {line}", flush=True)

        if done:
            print("[auto] All targeted organizations have been discovered and contacted. Done.", flush=True)
            _finalize()
            return

        if _should_stop():
            break
        if _sleep_interruptible(settings.auto_cycle_seconds):
            break

    _finalize()
    _clear_stop_file()
    print("[auto] stopped. Re-run `cli auto` to resume where it left off.", flush=True)


def _finalize() -> None:
    """Write a final fresh report on the way out."""
    try:
        with session_scope() as session:
            write_orgs_report(session)
    except Exception:  # noqa: BLE001
        pass


def _sleep_interruptible(seconds: float) -> bool:
    """Sleep in short slices so a stop request is honoured quickly.

    Returns True if a stop was requested during the sleep.
    """
    waited = 0.0
    step = 1.0
    while waited < seconds:
        if _should_stop():
            return True
        time.sleep(min(step, seconds - waited))
        waited += step
    return _should_stop()
