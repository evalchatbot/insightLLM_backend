"""
Decide which brand a report should carry (rubric.ai vs the Lahore CSS Academy
standalone app) from the incoming request, so the shared backend can render
per-app branding without any frontend changes.

Detection order:
  1. an explicit `brand` value (e.g. a form field), if given;
  2. otherwise the request Origin/Referer host — if it matches one of
     LCA_BRAND_ORIGINS (default: "lca-portal"), the brand is "lca".
Default is "rubric".
"""

from __future__ import annotations

import os
from typing import Optional


def _lca_markers() -> list[str]:
    raw = os.getenv("LCA_BRAND_ORIGINS", "lca-portal")
    return [m.strip().lower() for m in raw.split(",") if m.strip()]


def normalize_brand(value: Optional[str]) -> Optional[str]:
    v = (value or "").strip().lower()
    if v in ("lca", "lahore", "lahore-css-academy", "lahorecssacademy"):
        return "lca"
    if v in ("rubric", "rubric.ai", "rubricai"):
        return "rubric"
    return None


def brand_from_origin(origin: str) -> str:
    o = (origin or "").lower()
    for m in _lca_markers():
        if m and m in o:
            return "lca"
    return "rubric"


def resolve_brand(explicit: Optional[str] = None, *, origin: str = "", referer: str = "") -> str:
    """Resolve to 'lca' or 'rubric'. Explicit value wins, then Origin, then Referer."""
    b = normalize_brand(explicit)
    if b:
        return b
    from_origin = brand_from_origin(origin)
    if from_origin == "lca":
        return "lca"
    if brand_from_origin(referer) == "lca":
        return "lca"
    return "rubric"
