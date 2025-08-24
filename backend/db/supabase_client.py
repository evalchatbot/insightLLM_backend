"""
Supabase client for database and vector operations.
"""
from supabase import create_client, Client
from typing import Any, Dict, List, Optional
from backend.config import SUPABASE_URL, SUPABASE_KEY
from loguru import logger
import asyncio


def _py_floats(vec) -> list[float]:
    try:
        # works whether vec is list, ndarray, or list of np.float32
        if hasattr(vec, "tolist"):
            return [float(x) for x in vec.tolist()]
        return [float(x) for x in vec]
    except Exception:
        # last resort: wrap single scalar
        return [float(vec)]


class SupabaseDB:
    """Supabase client wrapper for CRUD and vector operations."""
    def __init__(self):
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    # ✅ Compatibility alias so other code can use .supabase
    @property
    def supabase(self) -> Client:
        return self.client

    def insert(self, table: str, data: Dict[str, Any]) -> Any:
        return self.client.table(table).insert(data).execute()

    def select(self, table: str, filters: Optional[Dict[str, Any]] = None) -> Any:
        query = self.client.table(table).select("*")
        if filters:
            for k, v in filters.items():
                if isinstance(v, list):
                    query = query.in_(k, v)
                else:
                    query = query.eq(k, v)
        return query.execute()

    def update(self, table: str, filters: Dict[str, Any], data: Dict[str, Any]) -> Any:
        query = self.client.table(table)
        for k, v in filters.items():
            query = query.eq(k, v)
        return query.update(data).execute()

    def delete(self, table: str, filters: Dict[str, Any]) -> Any:
        query = self.client.table(table)
        for k, v in filters.items():
            query = query.eq(k, v)
        return query.delete().execute()

    # Optional stub
    def vector_search(self, table: str, embedding: List[float], top_k: int = 5) -> Any:
        pass

    async def search_chunks_vector(self, query_embedding, book_ids, top_k: int = 5) -> List[dict]:
        try:
            payload = {
                "query_embedding": _py_floats(query_embedding),   # ✅ pure Python floats
                "match_count": int(top_k),
                # ✅ send None (not []) to mean “no filter”
                "book_ids": book_ids if (book_ids and len(book_ids) > 0) else None,
            }
            # You can call via .client or .supabase (both work now)
            result = self.client.rpc("match_documents", payload).execute()
            return result.data or []
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return []
