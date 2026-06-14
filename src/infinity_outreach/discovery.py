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

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .constants import religion as get_religion
from .constants import search_queries_for
from .models import Organization

_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"

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


def _place_details(place_id: str, session: requests.Session, api_key: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": "website,formatted_phone_number,formatted_address,name",
        "key": api_key,
    }
    try:
        resp = session.get(_DETAILS_URL, params=params, timeout=get_settings().request_timeout)
        data = resp.json()
        return data.get("result", {}) if data.get("status") == "OK" else {}
    except (requests.RequestException, ValueError):
        return {}


def _text_search(
    query: str, session: requests.Session, api_key: str, *, max_results: int
) -> list[dict]:
    """Run a Places text search, following up to two pages of results."""
    results: list[dict] = []
    params = {"query": query, "key": api_key}
    pages = 0
    while True:
        try:
            resp = session.get(_TEXTSEARCH_URL, params=params, timeout=get_settings().request_timeout)
            data = resp.json()
        except (requests.RequestException, ValueError):
            break

        status = data.get("status")
        if status not in ("OK", "ZERO_RESULTS"):
            # e.g. REQUEST_DENIED / OVER_QUERY_LIMIT — stop and surface upstream.
            raise DiscoveryUnavailable(
                f"Places API returned status={status}: {data.get('error_message', '')}"
            )

        results.extend(data.get("results", []))
        pages += 1
        token = data.get("next_page_token")
        if not token or len(results) >= max_results or pages >= 2:
            break
        # next_page_token needs a short delay before it becomes valid.
        time.sleep(2.0)
        params = {"pagetoken": token, "key": api_key}

    return results[:max_results]


def find_organizations(
    city: str,
    country: str,
    religion_key: str,
    *,
    limit: int = 20,
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
        raw = _text_search(query, http, api_key, max_results=limit)
        subtype = _subtype_from_query(query)
        for place in raw:
            pid = place.get("place_id")
            if not pid or pid in seen_place_ids:
                continue
            seen_place_ids.add(pid)
            details = _place_details(pid, http, api_key)
            candidates.append(
                OrgCandidate(
                    name=place.get("name", "Unknown"),
                    place_id=pid,
                    address=details.get("formatted_address") or place.get("formatted_address"),
                    website=details.get("website"),
                    phone=details.get("formatted_phone_number"),
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
        candidates = find_organizations(city, country, rkey, limit=per_religion)
        total_new += save_candidates(
            session, candidates, city=city, country=country, language_code=language_code
        )
    return total_new
