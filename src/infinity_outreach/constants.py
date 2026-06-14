"""Religion taxonomy, search vocabulary and language helpers.

This module encodes *what* the agent looks for in each city. The campaign you
configure in the web panel selects a subset of these religions and a subset of
countries; the discovery engine then expands each (religion x city) pair into
concrete Google Places search queries.

Focus religions (per the project brief):
    Christianity, Judaism, Hinduism, Buddhism, Taoism

Other religions are listed so the taxonomy is complete and future campaigns can
opt in, but the defaults target the five above.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Religion:
    """A religion, its sub-traditions, and the words used to find its venues."""

    key: str
    name: str
    subtypes: tuple[str, ...]
    # Building / venue words searched on Google Maps (English).
    venue_terms: tuple[str, ...]
    # Whether this religion is part of the default campaign focus.
    focus: bool = False


# ── The taxonomy ────────────────────────────────────────────────────────────
RELIGIONS: dict[str, Religion] = {
    "christianity": Religion(
        key="christianity",
        name="Christianity",
        subtypes=("Catholic", "Orthodox", "Protestant", "Other"),
        venue_terms=(
            "church",
            "Catholic church",
            "Orthodox church",
            "Protestant church",
            "Evangelical church",
            "parish",
            "cathedral",
            "chapel",
        ),
        focus=True,
    ),
    "judaism": Religion(
        key="judaism",
        name="Judaism",
        subtypes=("Orthodox", "Conservative", "Reform", "Other"),
        venue_terms=("synagogue", "Jewish community", "Jewish centre", "temple"),
        focus=True,
    ),
    "hinduism": Religion(
        key="hinduism",
        name="Hinduism",
        subtypes=("Vaishnavism", "Shaivism", "Shaktism", "Other"),
        venue_terms=(
            "Hindu temple",
            "mandir",
            "Hindu community",
            "Hindu cultural centre",
        ),
        focus=True,
    ),
    "buddhism": Religion(
        key="buddhism",
        name="Buddhism",
        subtypes=("Theravada", "Mahayana", "Vajrayana", "Other"),
        venue_terms=(
            "Buddhist temple",
            "Buddhist centre",
            "Buddhist monastery",
            "meditation centre",
            "dharma centre",
        ),
        focus=True,
    ),
    "taoism": Religion(
        key="taoism",
        name="Taoism",
        subtypes=("—",),
        venue_terms=("Taoist temple", "Daoist temple", "Taoist association"),
        focus=True,
    ),
    # ── Non-focus religions (available, not enabled by default) ─────────────
    "islam": Religion(
        key="islam",
        name="Islam",
        subtypes=("Sunni", "Shia", "Other"),
        venue_terms=("mosque", "Islamic centre", "masjid"),
    ),
    "spiritualism": Religion(
        key="spiritualism",
        name="Spiritualism",
        subtypes=("—",),
        venue_terms=("spiritualist church", "spiritual centre"),
    ),
    "pagan_folk": Religion(
        key="pagan_folk",
        name="Pagan / Folk / Neo-Spiritual",
        subtypes=("—",),
        venue_terms=("pagan community", "neo-spiritual centre", "folk religion"),
    ),
    "secular": Religion(
        key="secular",
        name="Agnostic / Secular",
        subtypes=("—",),
        venue_terms=("secular humanist community", "ethical society"),
    ),
    "atheism": Religion(
        key="atheism",
        name="Atheism",
        subtypes=("—",),
        venue_terms=("atheist association", "humanist association"),
    ),
}

# The five religions the project focuses on, in priority order.
FOCUS_RELIGIONS: list[str] = [k for k, r in RELIGIONS.items() if r.focus]

DEFAULT_RELIGIONS = FOCUS_RELIGIONS


def religion(key: str) -> Religion | None:
    return RELIGIONS.get(key.strip().lower())


def search_queries_for(religion_key: str, city: str, country: str) -> list[str]:
    """Build the list of Google Places text queries for a religion in a city.

    Example: ("christianity", "Prague", "Czechia") ->
        ["church in Prague, Czechia", "Catholic church in Prague, Czechia", ...]
    """
    rel = religion(religion_key)
    if rel is None:
        return []
    location = f"{city}, {country}"
    return [f"{term} in {location}" for term in rel.venue_terms]


# ── Language helpers ────────────────────────────────────────────────────────
# Maps the ISO code found in official_languages_by_country.csv to a human name.
# Used so the email writer can produce a native-language version next to English.
LANGUAGE_NAMES: dict[str, str] = {
    "cs": "Czech",
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "de": "German",
    "it": "Italian",
    "pl": "Polish",
    "pt": "Portuguese",
    "ru": "Russian",
    "sk": "Slovak",
    "es": "Spanish",
    "tr": "Turkish",
    "uk": "Ukrainian",
    "ar": "Arabic",
    "bn": "Bengali",
    "zh": "Chinese",
    "he": "Hebrew",
    "hi": "Hindi",
    "id": "Indonesian",
    "ja": "Japanese",
    "ko": "Korean",
    "ms": "Malay",
    "ne": "Nepali",
    "th": "Thai",
    "ur": "Urdu",
    "vi": "Vietnamese",
}


def language_name(code: str | None) -> str:
    if not code:
        return "English"
    return LANGUAGE_NAMES.get(code.strip().lower(), "English")


# Draft / sending status vocabularies (kept in one place to avoid typos).
DRAFT_STATUSES = ("draft", "approved", "sent", "rejected", "failed")
CONTACT_STATUSES = ("new", "valid", "bounced", "opted_out")
CITY_STATUSES = ("pending", "processing", "done", "skipped")
