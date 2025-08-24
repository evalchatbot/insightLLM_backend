from __future__ import annotations
from typing import Protocol, TypedDict, Optional, List, Dict


class RetrievedDoc(TypedDict):
    id: str
    chunk_id: str
    book_id: str | None
    source: str
    content: str
    score: float
    metadata: Dict


class VectorStoreAdapter(Protocol):
    async def similarity_search(
            self, query_embedding: List[float], top_k: int, filters: Optional[Dict] = None
    ) -> List[RetrievedDoc]: ...

    async def hybrid_search(
            self, text_query: str, query_embedding: List[float], top_k: int, filters: Optional[Dict] = None
    ) -> List[RetrievedDoc]: ...

    async def get_by_ids(self, ids: List[str]) -> List[RetrievedDoc]: ...
