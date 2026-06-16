"""Discover religious organizations via the Google Places API.

Why the API and not raw Google Maps scraping?
    The Places API is the *supported* way to query Google Maps data
    programmatically. It returns the same names, addresses, websites and phone
    numbers, but reliably and within Google's terms. Raw HTML scraping of Maps
    breaks constantly and gets the IP/account blocked — see AGENT_RULES.md.

If no API key is configured the engine still works: import organizations from a
CSV instead (``import-orgs``) — e.g. an export you assembled by hand.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import religion as get_religion
from .constants import search_queries_for
from .models import ApiCallLog, Organization

# Places API (New) endpoints — cheaper field-mask billing vs legacy API.
# Text Search with places.id mask = Essentials tier (~$5/1k vs legacy $32/1k).
# Place Details with website/phone = Pro tier (~$17/1k, same as legacy).
_TEXTSEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
_DETAILS_URL = "https://places.googleapis.com/v1/places/{}"
_DETAILS_FIELDS = "id,displayName,formattedAddress,nationalPhoneNumber,websiteUri"

# Map a venue search term to a likely religion subtype, for nicer records.
_SUBTYPE_HINTS = {
    "catholic": "Catholic",
    "orthodox": "Orthodox",
    "protestant": "Protestant",
    "evangelical": "Protestant",
    "theravada": "Theravada",
    "mahayana": "Mahayana",
    "vajrayana": "Vajrayana",
    "reform": "Reform",
}


class DiscoveryUnavailable(RuntimeError):
    """Raised when discovery cannot run (e.g. no Places API key)."""


def _count_calls_today(session: Session) -> int:
    today = datetime.combine(date.today(), datetime.min.time()).replace(tzinfo=timezone.utc)
    return session.query(ApiCallLog).filter(ApiCallLog.called_at >= today).count()


def _log_calls(session: Session, endpoint: str, n: int = 1, status: str = "OK") -> None:
    for _ in range(n):
        session.add(ApiCallLog(service="google_places", endpoint=endpoint, response_status=status))
    session.flush()


@dataclass
class OrgCandidate:
    name: str
    place_id: str
    address: str | None = None
    website: str | None = None
    phone: str | None = None
    religion: str | None = None
    religion_subtype: str | None = None
    source: str = "google_places"


def _subtype_from_query(query: str) -> str | None:
    q = query.lower()
    for needle, subtype in _SUBTYPE_HINTS.items():
        if needle in q:
            return subtype
    return None


def _place_details(place_id: str, http: requests.Session, api_key: str) -> dict:
    """Fetch name, address, website, phone for one place. Pro pricing tier."""
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": _DETAILS_FIELDS,
    }
    try:
        resp = http.get(
            _DETAILS_URL.format(place_id),
            headers=headers,
            timeout=get_settings().request_timeout,
        )
        if resp.status_code == 404:
            return {}
        resp.raise_for_status()
        data = resp.json()
        return {
            "name": data.get("displayName", {}).get("text", ""),
            "formatted_address": data.get("formattedAddress"),
            "website": data.get("websiteUri"),
            "phone": data.get("nationalPhoneNumber"),
        }
    except (requests.RequestException, ValueError):
        return {}


def _text_search(
    query: str, http: requests.Session, api_key: str, *, max_results: int
) -> tuple[list[dict], int]:
    """Text Search (New) with Pro field mask — returns full place data in one call.

    Requesting name/address/website/phone directly avoids a Place Details call per
    org, cutting total API calls by ~3×. Returns (place_data_list, pages_fetched).
    """
    places: list[dict] = []
    body: dict = {"textQuery": query, "pageSize": min(20, max_results)}
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,"
                             "places.nationalPhoneNumber,places.websiteUri",
        "Content-Type": "application/json",
    }
    pages = 0
    while True:
        try:
            resp = http.post(
                _TEXTSEARCH_URL,
                json=body,
                headers=headers,
                timeout=get_settings().request_timeout,
            )
            if resp.status_code == 403:
                raise DiscoveryUnavailable(
                    f"Places API (New) returned 403 — check your API key, billing, and that "
                    f"'Places API (New)' is enabled in Google Cloud: {resp.text}"
                )
            resp.raise_for_status()
            data = resp.json()
        except DiscoveryUnavailable:
            raise
        except (requests.RequestException, ValueError):
            break

        for raw in data.get("places", []):
            pid = raw.get("id")
            if pid:
                places.append({
                    "id": pid,
                    "name": raw.get("displayName", {}).get("text", ""),
                    "address": raw.get("formattedAddress"),
                    "website": raw.get("websiteUri"),
                    "phone": raw.get("nationalPhoneNumber"),
                })
        pages += 1

        token = data.get("nextPageToken")
        if not token or len(places) >= max_results or pages >= 2:
            break
        body = {"textQuery": query, "pageSize": 20, "pageToken": token}

    return places[:max_results], pages


def find_organizations(
    city: str,
    country: str,
    religion_key: str,
    *,
    limit: int = 20,
    db_session: Session | None = None,
) -> list[OrgCandidate]:
    """Query Places for one religion in one city and return candidates."""
    settings = get_settings()
    if not settings.places_configured():
        raise DiscoveryUnavailable(
            "GOOGLE_PLACES_API_KEY is not set. Set it in .env, or use "
            "`import-orgs` to load organizations from a CSV instead."
        )

    rel = get_religion(religion_key)
    if rel is None:
        return []

    api_key = settings.google_places_api_key
    http = requests.Session()
    http.headers.update({"User-Agent": settings.user_agent})

    seen_place_ids: set[str] = set()
    candidates: list[OrgCandidate] = []

    for query in search_queries_for(religion_key, city, country):
        if len(candidates) >= limit:
            break

        # --- Guardrail: enforce daily Places API call budget ---
        if db_session is not None:
            used = _count_calls_today(db_session)
            if used >= settings.places_daily_limit:
                raise DiscoveryUnavailable(
                    f"Daily Places API limit reached ({used}/{settings.places_daily_limit} calls). "
                    "Resume tomorrow or raise PLACES_DAILY_LIMIT in .env."
                )

        place_data, pages_fetched = _text_search(query, http, api_key, max_results=limit)
        if db_session is not None:
            _log_calls(db_session, "text_search", pages_fetched)

        subtype = _subtype_from_query(query)
        for place in place_data:
            pid = place["id"]
            if pid in seen_place_ids:
                continue
            seen_place_ids.add(pid)

            website = place.get("website")

            # Fallback: only call Place Details if text search didn't return a website.
            # This keeps Place Details calls rare — most real orgs include websiteUri.
            if not website:
                if db_session is not None:
                    used = _count_calls_today(db_session)
                    if used >= settings.places_daily_limit:
                        raise DiscoveryUnavailable(
                            f"Daily Places API limit reached ({used}/{settings.places_daily_limit} calls). "
                            "Resume tomorrow or raise PLACES_DAILY_LIMIT in .env."
                        )
                details = _place_details(pid, http, api_key)
                if db_session is not None:
                    _log_calls(db_session, "place_details", 1)
                website = details.get("website")
                place = {**place, **{k: v for k, v in details.items() if v}}

            candidates.append(
                OrgCandidate(
                    name=place.get("name") or "Unknown",
                    place_id=pid,
                    address=place.get("address") or place.get("formatted_address"),
                    website=website,
                    phone=place.get("phone"),
                    religion=rel.name,
                    religion_subtype=subtype,
                )
            )
            if len(candidates) >= limit:
                break
        time.sleep(settings.request_delay_seconds)

    return candidates


def save_candidates(
    session: Session,
    candidates: list[OrgCandidate],
    *,
    city: str,
    country: str,
    language_code: str | None,
) -> int:
    """Upsert candidates into the organizations table. Returns new-row count."""
    new_count = 0
    for c in candidates:
        existing = session.execute(
            select(Organization).where(
                Organization.source == c.source,
                Organization.source_id == c.place_id,
            )
        ).scalar_one_or_none()
        if existing is not None:
            # Backfill website/phone if we learned them this time.
            existing.website = existing.website or c.website
            existing.phone = existing.phone or c.phone
            continue

        session.add(
            Organization(
                name=c.name,
                city=city,
                country=country,
                language_code=language_code,
                category="Religious organization",
                religion=c.religion,
                religion_subtype=c.religion_subtype,
                religion_guess=c.religion,
                address=c.address,
                website=c.website,
                phone=c.phone,
                source=c.source,
                source_id=c.place_id,
                place_id=c.place_id,
                status="new",
            )
        )
        new_count += 1
    session.flush()
    return new_count


def discover_city(
    session: Session,
    *,
    city: str,
    country: str,
    language_code: str | None,
    religion_keys: list[str],
    max_orgs_per_city: int = 20,
) -> int:
    """Discover + persist organizations for one city across several religions."""
    total_new = 0
    per_religion = max(1, max_orgs_per_city // max(1, len(religion_keys)))
    for rkey in religion_keys:
        candidates = find_organizations(city, country, rkey, limit=per_religion, db_session=session)
        total_new += save_candidates(
            session, candidates, city=city, country=country, language_code=language_code
        )
    return total_new


def discover_city_hybrid(
    session: Session,
    *,
    city: str,
    country: str,
    language_code: str | None,
    religion_keys: list[str],
    max_orgs_per_city: int = 20,
    fallback_threshold: int = 5,
) -> tuple[int, bool, bool]:
    """Discover organizations using Google Places first, OSM as the fallback.

    Google Places is the **primary** source — it has the best coverage and most
    often includes websites and phone numbers. OpenStreetMap (free, no key) is the
    **fallback**, used when Google is unavailable: no API key, the daily Google
    budget (PLACES_DAILY_LIMIT) is exhausted, or Google returned too few results
    for a religion. So discovery runs on Google up to the daily cap, then keeps
    going for free on OSM.

    Flow per religion:
      1. PRIMARY: query Google Places (if configured and budget remains).
      2. FALLBACK: if Google was unavailable or returned fewer than
         fallback_threshold results, query OSM to fill the gap.

    Returns (new_org_count, osm_searched, google_searched).
    """
    from .osm_discovery import osm_find_organizations

    per_religion = max(1, max_orgs_per_city // max(1, len(religion_keys)))
    total_new = 0
    did_osm = False
    did_google = False
    settings = get_settings()

    for rkey in religion_keys:
        google_candidates: list[OrgCandidate] = []

        # --- PRIMARY: Google Places, while a key is set and budget remains ---
        if settings.places_configured() and (
            settings.places_daily_limit - _count_calls_today(session) > 0
        ):
            try:
                google_candidates = find_organizations(
                    city, country, rkey, limit=per_religion, db_session=session
                )
                total_new += save_candidates(
                    session, google_candidates,
                    city=city, country=country, language_code=language_code,
                )
                did_google = True
            except DiscoveryUnavailable:
                google_candidates = []  # budget hit mid-run — OSM takes over below

        # --- FALLBACK: OSM, when Google was unavailable or thin ---
        if len(google_candidates) >= fallback_threshold:
            continue  # Google covered this religion well — skip OSM

        osm_candidates = osm_find_organizations(
            city, country, rkey, limit=per_religion - len(google_candidates)
        )
        did_osm = True
        total_new += save_candidates(
            session, osm_candidates,
            city=city, country=country, language_code=language_code,
        )

    return total_new, did_osm, did_google
