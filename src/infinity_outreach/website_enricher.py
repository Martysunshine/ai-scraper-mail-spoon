"""Polite public-website enrichment.

Given an organization's website, fetch the homepage plus a few obvious public
pages (contact / about / impressum / imprint) and extract public email
addresses. This deliberately stays inside the boundaries set in AGENT_RULES.md:

* only public pages, only GET requests
* obeys robots.txt
* never bypasses captchas, logins or anti-bot protection
* rate-limited and identifies itself via the configured User-Agent
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .config import get_settings
from .email_extractor import extract_emails

# Link text / hrefs that tend to point at a page carrying a contact address.
_CONTACT_HINTS = (
    "contact",
    "kontakt",
    "about",
    "impressum",
    "imprint",
    "ueber",
    "über",
    "contacto",
    "contatti",
    "nous-contacter",
    "get-in-touch",
)


@dataclass
class EnrichmentResult:
    website: str
    emails: list[str] = field(default_factory=list)
    contact_page_url: str | None = None
    pages_fetched: int = 0
    error: str | None = None


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _robots_allows(url: str, user_agent: str) -> bool:
    """Best-effort robots.txt check. On any failure, allow (fail-open)."""
    try:
        parts = urlparse(url)
        robots_url = f"{parts.scheme}://{parts.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        return True


def _fetch(url: str, session: requests.Session) -> str | None:
    s = get_settings()
    try:
        resp = session.get(url, timeout=s.request_timeout, allow_redirects=True)
        ctype = resp.headers.get("Content-Type", "")
        if resp.status_code == 200 and "text/html" in ctype:
            return resp.text
    except requests.RequestException:
        return None
    return None


def _find_contact_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    found: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        label = (a.get_text() or "").lower()
        haystack = f"{href.lower()} {label}"
        if any(hint in haystack for hint in _CONTACT_HINTS):
            absolute = urljoin(base_url, href)
            if absolute.startswith(("http://", "https://")) and absolute not in found:
                found.append(absolute)
    return found[:5]  # cap: stay polite, don't crawl the whole site


def enrich_website(website: str) -> EnrichmentResult:
    """Fetch a homepage + likely contact pages and return public emails."""
    s = get_settings()
    url = _normalize_url(website)
    result = EnrichmentResult(website=url)
    if not url:
        result.error = "empty website"
        return result

    if not _robots_allows(url, s.user_agent):
        result.error = "blocked by robots.txt"
        return result

    session = requests.Session()
    session.headers.update({"User-Agent": s.user_agent, "Accept": "text/html"})

    home_html = _fetch(url, session)
    result.pages_fetched += 1
    if not home_html:
        result.error = "homepage unreachable"
        return result

    emails: list[str] = []
    contact_page: str | None = None

    for addr in extract_emails(home_html):
        if addr not in emails:
            emails.append(addr)

    # Visit a few obvious contact-style pages.
    for link in _find_contact_links(home_html, url):
        time.sleep(s.request_delay_seconds)  # polite pacing
        if not _robots_allows(link, s.user_agent):
            continue
        page_html = _fetch(link, session)
        result.pages_fetched += 1
        if not page_html:
            continue
        page_emails = extract_emails(page_html)
        if page_emails:
            contact_page = contact_page or link
            for addr in page_emails:
                if addr not in emails:
                    emails.append(addr)

    result.emails = emails
    result.contact_page_url = contact_page
    return result
