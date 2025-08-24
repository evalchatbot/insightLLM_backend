"""
Supabase client for database and vector operations.
"""
from supabase import create_client, Client
from typing import Any, Dict, List, Optional
from backend.config import SUPABASE_URL, SUPABASE_KEY
from loguru import logger
import asyncio

class SupabaseDB:
    """Supabase client wrapper for CRUD and vector operations."""
    def __init__(self):
        self.client: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

    def insert(self, table: str, data: Dict[str, Any]) -> Any:
        """Insert a record into a table."""
        return self.client.table(table).insert(data).execute()

    def select(self, table: str, filters: Optional[Dict[str, Any]] = None) -> Any:
        """Select records from a table with optional filters."""
        query = self.client.table(table).select("*")
        if filters:
            for k, v in filters.items():
                if isinstance(v, list):
                    query = query.in_(k, v)
                else:
                    query = query.eq(k, v)
        return query.execute()

    def update(self, table: str, filters: Dict[str, Any], data: Dict[str, Any]) -> Any:
        """Update records in a table matching filters."""
        query = self.client.table(table)
        for k, v in filters.items():
            query = query.eq(k, v)
        return query.update(data).execute()

    def delete(self, table: str, filters: Dict[str, Any]) -> Any:
        """Delete records from a table matching filters."""
        query = self.client.table(table)
        for k, v in filters.items():
            query = query.eq(k, v)
        return query.delete().execute()

    # Placeholder for vector search (to be implemented as per Supabase vector extension)
    def vector_search(self, table: str, embedding: List[float], top_k: int = 5) -> Any:
        """Search for similar embeddings in a table (stub)."""
        # Implementation depends on Supabase vector extension setup
        pass

    async def search_chunks_vector(self, query_embedding: List[float], book_ids: List[str], top_k: int = 5) -> List[Dict]:
        """
        Performs vector similarity search for chunks using pgvector (match_documents RPC).
        """
        try:
            loop = asyncio.get_event_loop()
            query = await loop.run_in_executor(
                None,
                lambda: self.client.rpc(
                    'match_documents',
                    {
                        'query_embedding': query_embedding,
                        'match_count': top_k,
                        'book_ids': book_ids
                    }
                ).execute()
            )
            return query.data if query and hasattr(query, 'data') and query.data else []
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
            return []
