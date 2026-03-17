"""
Topic taxonomy utilities for Fact Book editorials.
"""

from __future__ import annotations

from typing import Dict, List

PAKISTAN_TOPIC_DOMAINS: List[str] = [
    "Economy",
    "Governance",
    "Geopolitics",
    "Climate & Environment",
    "Security",
    "Technology",
    "Law & Justice",
    "Society",
    "Health",
    "Education",
    "Energy",
    "Gender",
    "Human Rights",
    "Media & Communication",
]

GLOBAL_TOPIC_DOMAINS: List[str] = [
    "Global Economy",
    "Global Geopolitics",
    "Global Climate Emergency",
    "Global Security",
    "Global Technology",
    "Globalisation",
]

OTHER_TOPIC_DOMAIN = "Other"

ALL_TOPIC_DOMAINS: List[str] = [
    *PAKISTAN_TOPIC_DOMAINS,
    *GLOBAL_TOPIC_DOMAINS,
    OTHER_TOPIC_DOMAIN,
]

TOPIC_GROUPS: Dict[str, List[str]] = {
    "Pakistan Domains": PAKISTAN_TOPIC_DOMAINS,
    "Global Domains": GLOBAL_TOPIC_DOMAINS,
    "Other": [OTHER_TOPIC_DOMAIN],
}

_KEYWORD_MAP: Dict[str, str] = {
    "inflation": "Economy",
    "tax": "Economy",
    "budget": "Economy",
    "imf": "Economy",
    "governance": "Governance",
    "accountability": "Governance",
    "election": "Governance",
    "parliament": "Governance",
    "foreign policy": "Geopolitics",
    "diplomatic": "Geopolitics",
    "china": "Geopolitics",
    "india": "Geopolitics",
    "climate": "Climate & Environment",
    "flood": "Climate & Environment",
    "water": "Climate & Environment",
    "security": "Security",
    "terror": "Security",
    "military": "Security",
    "cyber": "Technology",
    "digital": "Technology",
    "ai": "Technology",
    "court": "Law & Justice",
    "judicial": "Law & Justice",
    "law": "Law & Justice",
    "social": "Society",
    "poverty": "Society",
    "health": "Health",
    "hospital": "Health",
    "polio": "Health",
    "education": "Education",
    "school": "Education",
    "university": "Education",
    "power": "Energy",
    "electricity": "Energy",
    "gas": "Energy",
    "women": "Gender",
    "gender": "Gender",
    "rights": "Human Rights",
    "press": "Media & Communication",
    "media": "Media & Communication",
    "world economy": "Global Economy",
    "global economy": "Global Economy",
    "ukraine": "Global Geopolitics",
    "middle east": "Global Geopolitics",
    "global climate": "Global Climate Emergency",
    "nato": "Global Security",
    "global security": "Global Security",
    "big tech": "Global Technology",
    "global technology": "Global Technology",
    "globalisation": "Globalisation",
}


def normalize_topic_domain(value: str) -> str:
    candidate = (value or "").strip()
    if not candidate:
        return OTHER_TOPIC_DOMAIN

    lowered_map = {topic.lower(): topic for topic in ALL_TOPIC_DOMAINS}
    return lowered_map.get(candidate.lower(), OTHER_TOPIC_DOMAIN)


def keyword_fallback_topic_domain(text: str) -> str:
    haystack = (text or "").lower()
    for keyword, topic in _KEYWORD_MAP.items():
        if keyword in haystack:
            return topic
    return OTHER_TOPIC_DOMAIN
