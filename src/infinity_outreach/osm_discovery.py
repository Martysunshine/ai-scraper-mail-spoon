"""Discover religious organizations via OpenStreetMap (Overpass API).

Completely free — no API key, no billing, no daily call limit.
Uses two OSM services:
  - Nominatim  : city name → lat/lon  (max 1 req/sec, polite User-Agent required)
  - Overpass   : place-of-worship queries around a point (2s between requests)

Coverage is excellent in Europe, North America, and Australia; acceptable in
Latin America and South/East Asia; thinner in parts of Africa and Central Asia.
The hybrid caller (discovery.discover_city_hybrid) falls back to Google Places
when OSM returns too few results for a city.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from .discovery import OrgCandidate

from .config import get_settings
from .constants import religion as get_religion

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL  = "https://overpass-api.de/api/interpreter"

# Our religion keys → OSM religion tag values to search
_OSM_TAGS: dict[str, list[str]] = {
    "christianity": ["christian"],
    "judaism":      ["jewish"],
    "hinduism":     ["hindu"],
    "buddhism":     ["buddhist"],
    "taoism":       ["taoist"],
}

_nominatim_last: float = 0.0


def geocode_city(city: str, country: str) -> tuple[float, float] | None:
    """Return (lat, lon) for a city via Nominatim. None if not found."""
    global _nominatim_last
    wait = 1.1 - (time.monotonic() - _nominatim_last)
    if wait > 0:
        time.sleep(wait)

    params = {"q": f"{city}, {country}", "format": "json", "limit": 1}
    headers = {"User-Agent": get_settings().user_agent}
    try:
        resp = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=10)
        _nominatim_last = time.monotonic()
        resp.raise_for_status()
        results = resp.json()
        if results:
            return float(results[0]["lat"]), float(results[0]["lon"])
    except (requests.RequestException, ValueError, KeyError, IndexError):
        pass
    return None


def _overpass(lat: float, lon: float, osm_tags: list[str], radius_m: int) -> list[dict]:
    """Run an Overpass query for places of worship with the given religion tags."""
    tag_lines = "\n".join(
        f'  node["amenity"="place_of_worship"]["religion"="{r}"]'
        f'(around:{radius_m},{lat},{lon});\n'
        f'  way["amenity"="place_of_worship"]["religion"="{r}"]'
        f'(around:{radius_m},{lat},{lon});'
        for r in osm_tags
    )
    query = f'[out:json][timeout:30];\n(\n{tag_lines}\n);\nout body;'
    try:
        time.sleep(2.0)
        resp = requests.post(
            OVERPASS_URL,
            data={"data": query},
            headers={"User-Agent": get_settings().user_agent},
            timeout=35,
        )
        resp.raise_for_status()
        return resp.json().get("elements", [])
    except (requests.RequestException, ValueError):
        return []


def osm_find_organizations(
    city: str,
    country: str,
    religion_key: str,
    *,
    limit: int = 20,
    radius_km: int = 30,
) -> list[OrgCandidate]:
    """Find religious orgs via OSM for one religion in one city.

    Returns OrgCandidate list with source='osm'. Zero API cost.
    """
    from .discovery import OrgCandidate

    rel = get_religion(religion_key)
    if rel is None:
        return []

    osm_tags = _OSM_TAGS.get(religion_key)
    if not osm_tags:
        return []

    coords = geocode_city(city, country)
    if coords is None:
        return []

    lat, lon = coords
    elements = _overpass(lat, lon, osm_tags, radius_m=radius_km * 1000)

    seen: set[str] = set()
    results: list[OrgCandidate] = []

    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:en", "")
        if not name:
            continue

        osm_id = f"osm:{el.get('type', 'node')}/{el.get('id', '')}"
        if osm_id in seen:
            continue
        seen.add(osm_id)

        addr_parts = [
            tags.get("addr:housenumber", ""),
            tags.get("addr:street", ""),
            tags.get("addr:city", city),
        ]
        address = ", ".join(p for p in addr_parts if p) or f"{city}, {country}"

        website = (
            tags.get("website")
            or tags.get("contact:website")
            or tags.get("url")
        )
        phone = (
            tags.get("phone")
            or tags.get("contact:phone")
            or tags.get("telephone")
        )

        results.append(
            OrgCandidate(
                name=name,
                place_id=osm_id,
                address=address,
                website=website,
                phone=phone,
                religion=rel.name,
                religion_subtype=None,
                source="osm",
            )
        )
        if len(results) >= limit:
            break

    return results
