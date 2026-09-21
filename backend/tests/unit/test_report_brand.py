"""Brand resolution (rubric.ai vs Lahore CSS Academy) from form field / Origin / Referer."""

from __future__ import annotations

import threading

import pytest

from backend.utils import report_brand
from backend.utils.report_brand import brand_from_origin, normalize_brand, resolve_brand

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("lca", "lca"),
        ("  LCA ", "lca"),
        ("Lahore", "lca"),
        ("lahore-css-academy", "lca"),
        ("LahoreCSSAcademy", "lca"),
        ("rubric", "rubric"),
        ("Rubric.AI", "rubric"),
        ("rubricai", "rubric"),
        ("", None),
        (None, None),
        ("acme", None),
    ],
)
def test_normalize_brand(value, expected):
    assert normalize_brand(value) == expected


@pytest.mark.parametrize(
    ("origin", "expected"),
    [
        ("https://lca-portal.vercel.app", "lca"),
        ("https://LCA-PORTAL.org", "lca"),
        ("https://rubric.ai", "rubric"),
        ("", "rubric"),
        (None, "rubric"),
    ],
)
def test_brand_from_origin(origin, expected):
    assert brand_from_origin(origin) == expected


def test_explicit_brand_beats_headers():
    assert resolve_brand("rubric", origin="https://lca-portal.org", referer="https://lca-portal.org/x") == "rubric"
    assert resolve_brand("lca", origin="https://rubric.ai") == "lca"


def test_unknown_explicit_value_falls_back_to_headers():
    assert resolve_brand("something-else", origin="https://lca-portal.org") == "lca"


def test_origin_then_referer():
    assert resolve_brand(None, origin="https://rubric.ai", referer="https://lca-portal.org/page") == "lca"
    assert resolve_brand(None, origin="", referer="") == "rubric"


def test_markers_come_from_env(monkeypatch):
    monkeypatch.setenv("LCA_BRAND_ORIGINS", " academy.pk , ,Lahore-App ")
    assert report_brand._lca_markers() == ["academy.pk", "lahore-app"]
    assert resolve_brand(None, origin="https://portal.academy.pk") == "lca"
    assert resolve_brand(None, origin="https://lca-portal.org") == "rubric"  # default marker replaced


def test_empty_marker_list_never_matches(monkeypatch):
    monkeypatch.setenv("LCA_BRAND_ORIGINS", " , ")
    assert resolve_brand(None, origin="https://anything.example") == "rubric"


def test_report_cover_brand_is_thread_local():
    from backend.utils.report_cover import current_report_brand, set_report_brand

    set_report_brand("LCA ")
    seen = {}

    def worker():
        seen["other_thread"] = current_report_brand()
        set_report_brand(None)
        seen["after_reset"] = current_report_brand()

    t = threading.Thread(target=worker)
    t.start()
    t.join()
    try:
        assert current_report_brand() == "lca"
        assert seen == {"other_thread": "rubric", "after_reset": "rubric"}
    finally:
        set_report_brand("rubric")
