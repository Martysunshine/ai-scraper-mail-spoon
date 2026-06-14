"""Tests for the religion taxonomy and search-query building."""

from __future__ import annotations

from infinity_outreach.constants import (
    FOCUS_RELIGIONS,
    language_name,
    religion,
    search_queries_for,
)


def test_focus_religions_match_brief():
    assert set(FOCUS_RELIGIONS) == {
        "christianity",
        "judaism",
        "hinduism",
        "buddhism",
        "taoism",
    }


def test_search_queries_include_city_and_country():
    queries = search_queries_for("christianity", "Prague", "Czechia")
    assert queries, "expected at least one query"
    assert all("Prague, Czechia" in q for q in queries)
    assert any("Catholic" in q for q in queries)


def test_unknown_religion_returns_no_queries():
    assert search_queries_for("flying_spaghetti", "Rome", "Italy") == []


def test_language_name_lookup():
    assert language_name("cs") == "Czech"
    assert language_name("he") == "Hebrew"
    assert language_name(None) == "English"
    assert language_name("zz") == "English"  # unknown falls back to English


def test_religion_lookup_is_case_insensitive():
    assert religion("BUDDHISM").name == "Buddhism"
    assert religion("buddhism").focus is True
