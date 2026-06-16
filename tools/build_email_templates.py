r"""Generate email_templates/outreach_<code>.html from outreach_languages.md.

Single source of truth: email_templates/outreach_languages.md holds every
translation under a `## <code> — <Language>` heading, keeping the
{organisation's name} placeholder and the markdown links. Each language has the
same structure (greeting, intro, a bold mission line, a 5-item bullet list, two
links, a closing). This script converts each section into a clean, Gmail-ready
outreach_<code>.html with the {{org_name}} and {{opt_out}} placeholders the
engine fills per organization. Right-to-left languages (ar, he, ur) get
dir="rtl" automatically.

Run after editing the markdown:
    .\.venv\Scripts\python.exe tools\build_email_templates.py
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "email_templates"
MD_FILE = OUT_DIR / "outreach_languages.md"
RTL_CODES = {"ar", "he", "ur"}
BULLET_EMOJI = ["🌍", "📅", "🤝", "❤️", "📣"]

# Matches a section header line like "## cs — Czech" and captures the code.
HEADER_RE = re.compile(r"(?m)^##\s+([A-Za-z]{2})\s+—.*$")


def _md_links(text: str) -> str:
    """Convert [label](url) markdown links to clickable <a href> anchors."""
    return re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r'<a href="\2">\1</a>', text)


def _esc(text: str) -> str:
    return text.replace("&", "&amp;")


def _is_bullet(block: str) -> bool:
    return any(block.startswith(e) for e in BULLET_EMOJI) and "http" not in block


def build_html(raw: str, *, rtl: bool = False) -> str:
    blocks = [b.strip() for b in raw.strip().split("\n\n") if b.strip()]
    style = "font-family: Arial, Helvetica, sans-serif; font-size: 15px; line-height: 1.6; color: #222;"
    if rtl:
        style += " direction: rtl; text-align: right;"
    out: list[str] = [f'<div style="{style}">', ""]

    greeting = blocks[0].replace("{organisation's name}", "{{org_name}}")
    out.append(f"  <p>{_md_links(_esc(greeting))}</p>")

    bullets: list[str] = []

    def flush() -> None:
        if not bullets:
            return
        out.append('  <ul style="padding-left: 1.2em; margin: 0 0 1em;">')
        for b in bullets:
            out.append(f'    <li style="margin-bottom: 6px;">{_md_links(_esc(b))}</li>')
        out.append("  </ul>")
        bullets.clear()

    for block in blocks[1:]:
        if block.startswith("🕊"):                       # bold mission line
            flush()
            out.append(f'  <p style="font-size: 16px;"><b>{_md_links(_esc(block))}</b></p>')
        elif _is_bullet(block):                           # benefit bullet
            bullets.append(block)
        else:                                             # paragraph (incl. link lines)
            flush()
            out.append(f"  <p>{_md_links(_esc(block))}</p>")
    flush()

    # No opt-out here: the engine appends the signature, then a single opt-out
    # footer, after the bilingual body (email_writer.build_email).
    out.append("</div>")
    return "\n".join(out) + "\n"


def parse_sections(md: str) -> dict[str, str]:
    """Split the markdown into {code: body_text}, dropping '---' separators."""
    parts = HEADER_RE.split(md)
    sections: dict[str, str] = {}
    # parts = [preamble, code1, body1, code2, body2, ...]
    for i in range(1, len(parts), 2):
        code = parts[i].lower()
        body = re.sub(r"(?m)^-{3,}\s*$", "", parts[i + 1]).strip()
        if body:
            sections[code] = body
    return sections


def main() -> None:
    md = MD_FILE.read_text(encoding="utf-8")
    sections = parse_sections(md)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for code, raw in sections.items():
        html = build_html(raw, rtl=code in RTL_CODES)
        (OUT_DIR / f"outreach_{code}.html").write_text(html, encoding="utf-8")
        flag = " (rtl)" if code in RTL_CODES else ""
        print(f"  outreach_{code}.html  ({len(html):>5} bytes){flag}")
    print(f"\nDone — {len(sections)} templates generated from {MD_FILE.name}.")


if __name__ == "__main__":
    main()
