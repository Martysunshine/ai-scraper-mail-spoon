"""Assemble the outreach email for an organization from fixed template files.

No AI writes anything here. The operator provides finished, Gmail-ready HTML
templates in ``email_templates/`` (one per language, see that folder's README).
This module only:

  * loads the native-language template (if one exists for the org's language),
  * always appends the English template below it,
  * substitutes ``{{org_name}}`` (the greeting) and ``{{opt_out}}`` (compliance),
  * guarantees an opt-out line is present.

The result is HTML and is stored verbatim in ``email_drafts.body``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from .config import get_settings, template_dir


@dataclass
class DraftContent:
    subject: str
    body: str
    used_fallback: bool = False
    error: str | None = None


_SEPARATOR = (
    '\n<hr style="border:none;border-top:1px solid #ddd;margin:28px 0;">\n'
    '<p style="font-size:12px;color:#999;margin:0 0 12px;">English version</p>\n'
)


def _opt_out_line(sender_email: str) -> str:
    addr = sender_email or "us"
    return (
        f'If you would prefer not to hear from us, simply reply with '
        f'"unsubscribe" to {addr} and we will not contact you again.'
    )


@lru_cache(maxsize=64)
def load_template(language_code: str) -> str | None:
    """Return the raw HTML of ``outreach_<code>.html``, or None if absent.

    Cached because the same handful of language files are read for thousands of
    organizations. Call ``load_template.cache_clear()`` after editing a file.
    """
    code = (language_code or "").strip().lower()
    if not code:
        return None
    path = template_dir() / f"outreach_{code}.html"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _strip_html_comments(html: str) -> str:
    return re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL).strip()


@lru_cache(maxsize=1)
def load_signature() -> str | None:
    """Return the Infinity Faith signature block from email_templates/signature.html.

    That file is a signature *builder* page; the real signature is the
    ``<table id="sig">…</table>`` inside it (Kind Regards, the team, CTA buttons,
    and the hosted banner). We extract that table verbatim — its MSO conditional
    comments must be preserved, so it is NOT run through the comment stripper.
    """
    path = template_dir() / "signature.html"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    # Strip HTML comments FIRST — otherwise a comment that mentions the table tag
    # would be matched by the search below and leak into the email body.
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    start = text.find('<table id="sig"')
    if start == -1:
        return None
    close = text.rfind("</table>")  # last </table> = end of the (possibly nested) signature
    if close == -1 or close < start:
        return None
    return text[start : close + len("</table>")].strip()


def _fill(html: str, *, org_name: str, opt_out: str) -> str:
    filled = html.replace("{{org_name}}", org_name).replace("{{opt_out}}", opt_out)
    return _strip_html_comments(filled)


def build_email(
    *,
    org_name: str,
    city: str | None = None,
    country: str | None = None,
    religion: str | None = None,
    language_code: str | None = None,
    campaign=None,
) -> DraftContent:
    """Build the final bilingual (native + English) HTML email for one org.

    ``city``/``country``/``religion``/``campaign`` are accepted for backward
    compatibility with the previous AI writer but are not used: the email body
    comes entirely from the template files.
    """
    settings = get_settings()
    sender_email = settings.effective_sender_email
    opt_out = _opt_out_line(sender_email)
    name = (org_name or "friends").strip()

    english = load_template("en")
    code = (language_code or "").strip().lower()
    native = load_template(code) if code and code != "en" else None

    parts: list[str] = []
    if native:
        parts.append(_fill(native, org_name=name, opt_out=opt_out))
    if english:
        parts.append(_fill(english, org_name=name, opt_out=opt_out))

    if not parts:
        # No template files at all — degrade to a minimal compliant message
        # rather than crash the pipeline. Flag it so it shows up in review.
        body = (
            f'<div style="font-family:Arial,sans-serif;font-size:15px;">'
            f"<p>Dear {name},</p>"
            f"<p>(No email template found. Add email_templates/outreach_en.html.)</p>"
            f'<p style="font-size:12px;color:#888;">{opt_out}</p></div>'
        )
        return DraftContent(
            subject=_subject_for(name, settings),
            body=body,
            used_fallback=True,
            error="No email_templates/outreach_en.html found.",
        )

    body = (_SEPARATOR.join(parts)) if len(parts) == 2 else parts[0]

    # Sign-off: the Infinity Faith signature (with banner + CTA buttons), appended
    # once after the bilingual message. SMTP does not apply a Gmail signature, so
    # we bake it in here.
    signature = load_signature()
    if signature:
        body += "\n" + signature

    # A single opt-out footer at the very bottom (compliance), after the signature.
    body += f'\n<p style="font-size:12px;color:#888;margin-top:24px;">{opt_out}</p>'

    return DraftContent(subject=_subject_for(name, settings), body=body, used_fallback=False)


def _subject_for(org_name: str, settings) -> str:
    subject = settings.email_subject or "An invitation to try Infinity Faith"
    return subject.replace("{{org_name}}", org_name)
