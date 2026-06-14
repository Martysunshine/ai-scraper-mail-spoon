"""Extract public email addresses from HTML / text.

Pure functions, no I/O — easy to unit test. Handles the common obfuscations
that organizations use on public contact pages (``info [at] church . org``,
``mailto:`` links, etc.) without touching anything behind a login or captcha.
"""

from __future__ import annotations

import re

# Standard-ish email regex (good enough for public contact pages).
_EMAIL_RE = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,24}",
)

# Common textual obfuscations -> canonical symbols.
_DEOBFUSCATE = [
    (re.compile(r"\s*\[\s*at\s*\]\s*", re.I), "@"),
    (re.compile(r"\s*\(\s*at\s*\)\s*", re.I), "@"),
    (re.compile(r"\s+at\s+", re.I), "@"),
    (re.compile(r"\s*\[\s*dot\s*\]\s*", re.I), "."),
    (re.compile(r"\s*\(\s*dot\s*\)\s*", re.I), "."),
    (re.compile(r"\s+dot\s+", re.I), "."),
]

# Addresses that are almost never a real human/org inbox.
_JUNK_PREFIXES = ("noreply", "no-reply", "donotreply", "do-not-reply")
_JUNK_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "sentry.io",
    "wix.com",
    "wixpress.com",
    "godaddy.com",
    "squarespace.com",
)
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")


def _deobfuscate(text: str) -> str:
    for pattern, repl in _DEOBFUSCATE:
        text = pattern.sub(repl, text)
    return text


def _looks_like_image_filename(addr: str) -> bool:
    # e.g. "logo@2x.png" style strings sometimes match the regex.
    return addr.lower().endswith(_IMAGE_EXTS)


def is_probably_real(addr: str) -> bool:
    addr_l = addr.lower()
    local, _, domain = addr_l.partition("@")
    if not domain or "." not in domain:
        return False
    if _looks_like_image_filename(addr_l):
        return False
    if any(local.startswith(p) for p in _JUNK_PREFIXES):
        return False
    if domain in _JUNK_DOMAINS:
        return False
    return True


def extract_emails(text: str, *, drop_junk: bool = True) -> list[str]:
    """Return de-duplicated, lower-cased emails found in ``text``.

    ``drop_junk`` removes no-reply / placeholder / image-like matches.
    Order is preserved (first occurrence wins).
    """
    if not text:
        return []
    cleaned = _deobfuscate(text)
    seen: set[str] = set()
    out: list[str] = []
    for match in _EMAIL_RE.findall(cleaned):
        addr = match.strip().strip(".").lower()
        if addr in seen:
            continue
        if drop_junk and not is_probably_real(addr):
            continue
        seen.add(addr)
        out.append(addr)
    return out
