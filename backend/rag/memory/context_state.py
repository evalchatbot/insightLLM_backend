from __future__ import annotations
from typing import List, Dict, Set, Optional
from pydantic import BaseModel, Field

class EvidenceSnippet(BaseModel):
    doc_id: str
    chunk_id: str
    source: str
    content: str
    score: float
    metadata: Dict = Field(default_factory=dict)

class Budget(BaseModel):
    tokens: int = 0
    time_ms: int = 0

class ContextState(BaseModel):
    iteration: int = 0
    notes: str = ""
    seen_doc_ids: Set[str] = Field(default_factory=set)
    subquestions_queue: List[str] = Field(default_factory=list)
    accumulated_evidence: List[EvidenceSnippet] = Field(default_factory=list)
    budget: Budget = Field(default_factory=Budget)
    citations_buffer: List[Dict] = Field(default_factory=list)

    def enqueue_subquestions(self, subs: List[str]) -> None:
        for s in subs:
            s_norm = s.strip()
            if s_norm and s_norm not in self.subquestions_queue:
                self.subquestions_queue.append(s_norm)

    def pop_next_subquestion(self) -> Optional[str]:
        if not self.subquestions_queue:
            return None
        return self.subquestions_queue.pop(0)

    def add_evidence(self, snippets: List[EvidenceSnippet]) -> None:
        for sn in snippets:
            key = f"{sn.doc_id}:{sn.chunk_id}"
            if key not in self.seen_doc_ids:
                self.seen_doc_ids.add(key)
                self.accumulated_evidence.append(sn)
