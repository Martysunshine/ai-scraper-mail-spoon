"""Tests for the public-email extractor."""

from __future__ import annotations

from infinity_outreach.email_extractor import extract_emails, is_probably_real


def test_extracts_plain_email_from_html():
    html = """
    <html><body>
      <p>Contact us at <a href="mailto:office@stmary-church.org">office@stmary-church.org</a></p>
    </body></html>
    """
    emails = extract_emails(html)
    assert "office@stmary-church.org" in emails


def test_deobfuscates_at_and_dot():
    text = "Reach the rabbi: rabbi [at] synagogue [dot] org for details."
    emails = extract_emails(text)
    assert "rabbi@synagogue.org" in emails


def test_dedupes_and_lowercases():
    text = "Info@Temple.org, info@temple.org and INFO@TEMPLE.ORG"
    emails = extract_emails(text)
    assert emails == ["info@temple.org"]


def test_drops_noreply_and_placeholders():
    text = "noreply@church.org, real@church.org, webmaster@example.com"
    emails = extract_emails(text)
    assert "real@church.org" in emails
    assert "noreply@church.org" not in emails
    assert "webmaster@example.com" not in emails  # example.com is a placeholder domain


def test_ignores_image_filenames():
    text = "background image logo@2x.png and contact pastor@parish.net"
    emails = extract_emails(text)
    assert "pastor@parish.net" in emails
    assert all(not e.endswith(".png") for e in emails)


def test_is_probably_real():
    assert is_probably_real("hello@mandir.in")
    assert not is_probably_real("no-reply@mandir.in")
    assert not is_probably_real("broken@@nope")
    assert not is_probably_real("file@image.png")


def test_empty_input_returns_empty_list():
    assert extract_emails("") == []
    assert extract_emails(None) == []
