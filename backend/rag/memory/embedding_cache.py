"""
Embedding cache for performance optimization.
Caches embeddings to avoid redundant computation.
"""
import hashlib
from typing import List, Optional
from backend.rag.memory.cache import TTLCache
from backend.rag.config import get_rag_settings

class EmbeddingCache:
    """Cache for embeddings to avoid redundant computation."""
    
    def __init__(self, ttl_s: int = None):
        settings = get_rag_settings()
        self.cache = TTLCache(ttl_s or settings.CACHE_TTL_S)
        self.enabled = settings.ENABLE_CACHE
    
    def _make_key(self, text: str) -> str:
        """Create a cache key from text."""
        # Use hash to handle long texts and ensure consistent keys
        return hashlib.md5(text.encode('utf-8')).hexdigest()
    
    def get(self, text: str) -> Optional[List[float]]:
        """Get cached embedding for text."""
        if not self.enabled:
            return None
        return self.cache.get(self._make_key(text))
    
    def set(self, text: str, embedding: List[float]) -> None:
        """Cache embedding for text."""
        if not self.enabled:
            return
        self.cache.set(self._make_key(text), embedding)
    
    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()

# Global embedding cache instance
_embedding_cache = EmbeddingCache()

def get_embedding_cache() -> EmbeddingCache:
    """Get the global embedding cache instance."""
    return _embedding_cache
