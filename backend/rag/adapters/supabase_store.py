# backend/rag/adapters/supabase_store.py
from __future__ import annotations
from typing import List, Dict, Optional, Any
from backend.rag.adapters.base import VectorStoreAdapter, RetrievedDoc

class SupabaseVectorStoreAdapter(VectorStoreAdapter):
    """
    Adapter that wraps your existing SupabaseService instance.

    Expects:
      - service.search_chunks_vector(query_embedding, book_ids, top_k)
      - service.supabase.table("document_chunks") for keyword search fallback
    """
    def __init__(self, service: Any) -> None:
        self.service = service
        # table/column names based on your code
        self.table = "document_chunks"
        self.content_col = "content"
        self.id_col = "id"              # chunk id
        self.book_id_col = "book_id"    # parent document/book id
        self.source = "document_chunks" # static source label

    def _normalize_row(self, row: Dict, score: float = 0.0) -> RetrievedDoc:
        # Include useful metadata (page ranges, etc.)
        meta = row.get("metadata", {}) or {}
        if "page_start" in row: meta["page_start"] = row["page_start"]
        if "page_end" in row:   meta["page_end"] = row["page_end"]
        if "chunk_index" in row: meta["chunk_index"] = row["chunk_index"]

        # Map: id = book_id (doc identity), chunk_id = chunk row id
        return {
            "id": str(row.get(self.book_id_col, "")),          # doc id
            "chunk_id": str(row.get(self.id_col, "")),         # chunk id
            "book_id": str(row.get(self.book_id_col, "")) if row.get(self.book_id_col) else None,
            "source": self.source,
            "content": row.get(self.content_col, "") or "",
            "score": float(row.get("score", score) or 0.0),
            "metadata": meta,
        }

    def _extract_book_ids(self, filters: Optional[Dict]) -> List[str]:
        # We accept filters like {"book_ids": [...]} (aligns with your code)
        if not filters:
            return []
        book_ids = filters.get("book_ids")
        if isinstance(book_ids, list):
            return book_ids
        return []

    async def similarity_search(
        self,
        query_embedding: List[float],
        top_k: int,
        filters: Optional[Dict] = None
    ) -> List[RetrievedDoc]:
        """
        Vector search via your RPC (search_chunks_vector).
        """
        try:
            book_ids = self._extract_book_ids(filters)
            rows = await self.service.search_chunks_vector(query_embedding, book_ids, top_k=top_k)
            rows = rows or []
            # Expect RPC to include 'score' per row. If not, we set default 0.0
            return [self._normalize_row(r) for r in rows]
        except Exception:
            return []

    async def hybrid_search(
        self,
        text_query: str,
        query_embedding: List[float],
        top_k: int,
        filters: Optional[Dict] = None
    ) -> List[RetrievedDoc]:
        """
        Hybrid search: combine keyword LIKE with vector similarity, then merge/dedupe.
        """
        # 1) Vector pass
        vec_rows = await self.similarity_search(query_embedding, top_k, filters)

        # 2) Keyword pass (naive ilike on content); honors book_ids if provided
        kw_rows: List[Dict] = []
        try:
            q = self.service.supabase.table(self.table).select("*")
            book_ids = self._extract_book_ids(filters)
            if book_ids:
                q = q.in_(self.book_id_col, book_ids)
            kw = f"%{text_query}%"
            q = q.ilike(self.content_col, kw).limit(top_k)
            kw_rows = q.execute().data or []
        except Exception:
            kw_rows = []

        # Normalize keyword rows with a small base score so vector signal dominates
        kw_norm = [self._normalize_row(r, score=0.2) for r in kw_rows]

        # Merge unique by (id, chunk_id)
        seen = set()
        out: List[RetrievedDoc] = []
        for r in vec_rows + kw_norm:
            key = (r["id"], r["chunk_id"])
            if key not in seen:
                seen.add(key)
                out.append(r)

        # Sort by 'score' desc (vector-first)
        out.sort(key=lambda x: x.get("score", 0.0), reverse=True)
        return out[:top_k]

    async def get_by_ids(self, ids: List[str]) -> List[RetrievedDoc]:
        """
        Fetch chunks by their chunk IDs (document_chunks.id).
        """
        if not ids:
            return []
        rows = (
            self.service.supabase.table(self.table)
            .select("*")
            .in_(self.id_col, ids)
            .execute()
            .data or []
        )
        return [self._normalize_row(r) for r in rows]
