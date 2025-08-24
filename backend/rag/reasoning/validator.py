# backend/rag/reasoning/validator.py
from __future__ import annotations
import re
from typing import List
from backend.rag.memory.context_state import EvidenceSnippet

_INJECTION_PATTERNS = [
    r"(?i)\b(ignore|disregard) (all|any|previous) (instructions|rules)\b",
    r"(?i)\b(system prompt|override)\b",
]

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"\+?\d[\d\-\s]{7,}\d")

def sanitize_text(t: str) -> str:
    # Strip obvious prompt-injection phrases
    for pat in _INJECTION_PATTERNS:
        t = re.sub(pat, "[REDACTED-INJECTION]", t)
    # PII redaction (lightweight)
    t = _EMAIL.sub("[REDACTED-EMAIL]", t)
    t = _PHONE.sub("[REDACTED-PHONE]", t)
    return t

def sanitize_snippets(snippets: List[EvidenceSnippet]) -> List[EvidenceSnippet]:
    out: List[EvidenceSnippet] = []
    for s in snippets:
        out.append(EvidenceSnippet(
            doc_id=s.doc_id,
            chunk_id=s.chunk_id,
            source=s.source,
            content=sanitize_text(s.content),
            score=s.score,
            metadata=s.metadata,
        ))
    return out

def has_sufficient_evidence(snippets: List[EvidenceSnippet], min_docs: int = 1) -> bool:
    return len(snippets) >= min_docs and any(len(s.content.strip()) > 0 for s in snippets)
