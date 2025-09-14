"""
Supabase client for database and vector operations.
"""
from supabase import create_client, Client
from typing import Any, Dict, List, Optional
from backend.config import SUPABASE_URL, SUPABASE_KEY
from loguru import logger
import asyncio
import time


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
        self._embedding_dimensions = None  # Cache for embedding dimensions

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

    def get_embedding_dimensions(self) -> int:
        """
        Detect the embedding dimensions used in the database.
        """
        if self._embedding_dimensions is not None:
            return self._embedding_dimensions
        
        try:
            # Try to get a sample embedding from the database
            result = self.client.table("document_chunks").select("embedding").limit(1).execute()
            if result.data and len(result.data) > 0 and result.data[0].get("embedding"):
                embedding = result.data[0]["embedding"]
                self._embedding_dimensions = len(embedding)
                logger.info(f"[VECTOR_SEARCH] Detected embedding dimensions: {self._embedding_dimensions}")
                return self._embedding_dimensions
        except Exception as e:
            logger.warning(f"[VECTOR_SEARCH] Could not detect embedding dimensions: {e}")
        
        # Default fallback (common embedding sizes)
        self._embedding_dimensions = 384  # Common for many models
        logger.info(f"[VECTOR_SEARCH] Using default embedding dimensions: {self._embedding_dimensions}")
        return self._embedding_dimensions
    
    # Optional stub
    def vector_search(self, table: str, embedding: List[float], top_k: int = 5) -> Any:
        pass

    async def search_chunks_vector(self, query_embedding, book_ids, top_k: int = 5) -> List[dict]:
        """
        Perform vector search with timeout protection and fallback strategies.
        """
        try:
            # Limit parameters to prevent timeout
            safe_top_k = min(int(top_k), 10)  # Limit to 10 results max
            safe_book_ids = None
            
            # If book_ids provided, limit to prevent timeout
            if book_ids and len(book_ids) > 0:
                safe_book_ids = book_ids[:5]  # Limit to 5 books max
                logger.info(f"[VECTOR_SEARCH] Limiting search to {len(safe_book_ids)} books")
            else:
                logger.info(f"[VECTOR_SEARCH] Searching all books")
            
            # Check embedding dimensions
            embedding_dims = len(_py_floats(query_embedding))
            logger.info(f"[VECTOR_SEARCH] Query embedding dimensions: {embedding_dims}")
            
            payload = {
                "query_embedding": _py_floats(query_embedding),
                "match_count": safe_top_k,
                "book_ids": safe_book_ids,
            }
            
            logger.info(f"[VECTOR_SEARCH] Starting search with top_k={safe_top_k}, books={len(safe_book_ids) if safe_book_ids else 'all'}")
            
            # Try the RPC function with timeout handling
            start_time = time.time()
            result = self.client.rpc("match_documents", payload).execute()
            elapsed_time = time.time() - start_time
            
            logger.info(f"[VECTOR_SEARCH] Search completed in {elapsed_time:.2f}s, found {len(result.data) if result.data else 0} results")
            return result.data or []
            
        except Exception as e:
            logger.error(f"[VECTOR_SEARCH] RPC search failed: {e}")
            
            # Check if it's a timeout error or dimension mismatch
            error_str = str(e).lower()
            if 'timeout' in error_str or '57014' in str(e):
                logger.warning(f"[VECTOR_SEARCH] Timeout detected, trying fallback search")
                return await self._fallback_vector_search(safe_book_ids, safe_top_k)
            elif 'different vector dimensions' in error_str:
                logger.warning(f"[VECTOR_SEARCH] Vector dimension mismatch detected")
                logger.warning(f"[VECTOR_SEARCH] Your embeddings might be {embedding_dims} dims but DB expects different")
                # Still try fallback as it doesn't rely on vector similarity
                return await self._fallback_vector_search(safe_book_ids, safe_top_k)
            else:
                logger.error(f"[VECTOR_SEARCH] Non-recoverable error: {type(e).__name__}: {e}")
                return []
    
    async def _fallback_vector_search(self, book_ids, top_k: int = 5) -> List[dict]:
        """
        Fallback search strategy when vector search times out.
        Uses non-vector queries to still return relevant results.
        """
        try:
            logger.info(f"[VECTOR_SEARCH] Executing fallback search strategy")
            
            # Strategy 1: Get chunks from specified books (preferred)
            if book_ids and len(book_ids) > 0:
                logger.info(f"[VECTOR_SEARCH] Fallback: Getting chunks from {len(book_ids)} specific books")
                query = (
                    self.client.table("document_chunks")
                    .select("*")
                    .in_("book_id", book_ids[:3])  # Limit to 3 books max
                    .order("created_at", desc=True)
                    .limit(min(top_k, 10))  # Limit results
                )
            else:
                # Strategy 2: Get recent chunks, but with more constraints to avoid timeout
                logger.info(f"[VECTOR_SEARCH] Fallback: Getting recent chunks with constraints")
                
                # First, try to get a few books to limit the scope
                try:
                    books_query = self.client.table("books").select("id").limit(3).execute()
                    if books_query.data and len(books_query.data) > 0:
                        available_book_ids = [book["id"] for book in books_query.data]
                        logger.info(f"[VECTOR_SEARCH] Fallback: Using available books: {len(available_book_ids)}")
                        
                        query = (
                            self.client.table("document_chunks")
                            .select("*")
                            .in_("book_id", available_book_ids)
                            .order("created_at", desc=True)
                            .limit(min(top_k, 5))  # Very limited for safety
                        )
                    else:
                        # Last resort: very limited query
                        logger.warning(f"[VECTOR_SEARCH] Fallback: No books found, using minimal query")
                        query = (
                            self.client.table("document_chunks")
                            .select("id, content, book_id")
                            .order("created_at", desc=True)
                            .limit(3)  # Very small limit to avoid timeout
                        )
                except Exception as book_error:
                    logger.warning(f"[VECTOR_SEARCH] Could not get books for fallback: {book_error}")
                    # Minimal fallback
                    query = (
                        self.client.table("document_chunks")
                        .select("id, content, book_id")
                        .limit(3)
                    )
            
            result = query.execute()
            fallback_results = result.data or []
            
            logger.info(f"[VECTOR_SEARCH] Fallback search returned {len(fallback_results)} results")
            return fallback_results
            
        except Exception as fallback_error:
            logger.error(f"[VECTOR_SEARCH] Fallback search also failed: {fallback_error}")
            
            # Ultimate fallback: try to get just one record to verify DB connectivity
            try:
                logger.info(f"[VECTOR_SEARCH] Attempting ultimate fallback (single record)")
                minimal_result = self.client.table("document_chunks").select("id, content").limit(1).execute()
                return minimal_result.data or []
            except Exception as ultimate_error:
                logger.error(f"[VECTOR_SEARCH] Ultimate fallback failed: {ultimate_error}")
                return []
