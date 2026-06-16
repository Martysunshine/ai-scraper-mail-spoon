"""Lightweight email verification to keep the bounce rate low.

A high bounce rate is the fastest way to wreck a sending domain's reputation, so
we reject undeliverable addresses *before* sending. Two cheap, safe checks only —
deliberately **no SMTP mailbox probing**, which is unreliable (big providers
don't answer truthfully) and can itself get the sending IP flagged:

  1. Syntax / RFC validity.
  2. The recipient domain actually accepts mail (has an MX record, or an A
     record as a fallback).

Transient DNS errors fail **open** (treated as deliverable) so a flaky lookup
never silently drops a whole run.
"""

from __future__ import annotations

import re
from functools import lru_cache

try:  # pragma: no cover - import guard
    from email_validator import EmailNotValidError, validate_email
    _HAVE_VALIDATOR = True
except Exception:  # noqa: BLE001
    _HAVE_VALIDATOR = False

try:  # pragma: no cover - import guard
    import dns.resolver as _dns
    _HAVE_DNS = True
except Exception:  # noqa: BLE001
    _HAVE_DNS = False

_SYNTAX_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _syntax_ok(address: str) -> bool:
    if _HAVE_VALIDATOR:
        try:
            validate_email(address, check_deliverability=False)
            return True
        except EmailNotValidError:
            return False
    return bool(_SYNTAX_RE.match(address or ""))


@lru_cache(maxsize=8192)
def _domain_deliverable(domain: str) -> bool | None:
    """True = accepts mail (MX/A), False = resolves but no mail, None = unknown."""
    if not _HAVE_DNS:
        return None
    definite_no = (_dns.NoAnswer, _dns.NXDOMAIN, _dns.NoNameservers)
    try:
        _dns.resolve(domain, "MX")
        return True
    except definite_no:
        try:
            _dns.resolve(domain, "A")  # some domains receive mail on the A record
            return True
        except definite_no:
            return False
        except Exception:  # noqa: BLE001 — transient
            return None
    except Exception:  # noqa: BLE001 — timeout / transient → fail open
        return None


def verify_email(address: str) -> tuple[bool, str]:
    """Return (deliverable, reason). Rejects bad syntax and dead domains only."""
    address = (address or "").strip()
    if not _syntax_ok(address):
        return False, "invalid syntax"
    domain = address.rsplit("@", 1)[-1].lower()
    if _domain_deliverable(domain) is False:
        return False, f"{domain} has no mail server"
    return True, "ok"
