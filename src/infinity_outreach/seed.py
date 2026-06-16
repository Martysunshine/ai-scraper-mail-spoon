"""Seed the worklist from ``official_languages_by_country.csv``.

That CSV lists, per (country, language): up to eight major cities. We expand it
into one row per city so the engine can walk country -> city -> religion. The
language travels with each city so the email writer can produce a native-tongue
version.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import DATA_DIR, PROJECT_ROOT
from .models import City

CITY_COLUMNS = [f"City_{i}" for i in range(1, 9)]


@dataclass
class CityRow:
    city: str
    country: str
    continent: str | None
    language: str | None
    language_code: str | None


def _languages_csv_path() -> Path:
    """Locate the languages CSV (project root preferred, then data/)."""
    candidates = [
        PROJECT_ROOT / "official_languages_by_country.csv",
        DATA_DIR / "official_languages_by_country.csv",
    ]
    for c in candidates:
        if c.exists():
            return c
    raise FileNotFoundError(
        "official_languages_by_country.csv not found in project root or data/."
    )


def parse_language_rows(path: Path | None = None) -> list[CityRow]:
    """Read the languages CSV into a flat list of CityRow (deduplicated)."""
    path = path or _languages_csv_path()
    rows: list[CityRow] = []
    seen: set[tuple[str, str]] = set()
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        for record in reader:
            country = (record.get("Country") or "").strip()
            if not country:
                continue
            continent = (record.get("Continent") or "").strip() or None
            language = (record.get("Language") or "").strip() or None
            code = (record.get("Code") or "").strip() or None
            for col in CITY_COLUMNS:
                city = (record.get(col) or "").strip()
                if not city:
                    continue
                key = (city.lower(), country.lower())
                if key in seen:
                    continue
                seen.add(key)
                rows.append(
                    CityRow(
                        city=city,
                        country=country,
                        continent=continent,
                        language=language,
                        language_code=code,
                    )
                )
    return rows


def seed_cities(
    session: Session,
    *,
    only_countries: list[str] | None = None,
    only_continents: list[str] | None = None,
) -> int:
    """Insert cities into the DB (skip existing). Returns new-row count.

    Filter by country names and/or by continent (region). The autonomous loop
    seeds one region at a time via ``only_continents=["Europe"]`` etc.
    """
    rows = parse_language_rows()
    if only_countries:
        wanted = {c.strip().lower() for c in only_countries}
        rows = [r for r in rows if r.country.lower() in wanted]
    if only_continents:
        regions = {c.strip().lower() for c in only_continents}
        rows = [r for r in rows if (r.continent or "").lower() in regions]

    existing = {
        (c, co)
        for c, co in session.execute(select(City.city, City.country)).all()
    }
    new_count = 0
    for r in rows:
        if (r.city, r.country) in existing:
            continue
        session.add(
            City(
                city=r.city,
                country=r.country,
                continent=r.continent,
                language=r.language,
                language_code=r.language_code,
                status="pending",
            )
        )
        existing.add((r.city, r.country))
        new_count += 1
    session.flush()
    return new_count


def write_cities_csv(path: Path | None = None) -> Path:
    """Write a flat data/cities.csv (city,country,language,language_code)."""
    path = path or (DATA_DIR / "cities.csv")
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = parse_language_rows()
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["city", "country", "language", "language_code"])
        for r in rows:
            writer.writerow([r.city, r.country, r.language or "", r.language_code or ""])
    return path


def country_language_index() -> list[dict]:
    """Country/language catalogue for the web panel's country picker.

    Returns a list like:
        [{"country": "Czechia", "language": "Czech", "code": "cs",
          "continent": "Europe", "city_count": 8}, ...]
    Deduplicated per (country, language).
    """
    rows = parse_language_rows()
    index: dict[tuple[str, str], dict] = {}
    for r in rows:
        key = (r.country, r.language or "")
        entry = index.setdefault(
            key,
            {
                "country": r.country,
                "language": r.language,
                "code": r.language_code,
                "continent": r.continent,
                "city_count": 0,
            },
        )
        entry["city_count"] += 1
    return sorted(index.values(), key=lambda e: (e["continent"] or "", e["country"]))
