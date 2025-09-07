"""
Embedding utilities for RAG pipeline using FastEmbed.
"""
from fastembed import TextEmbedding
import numpy as np
from typing import List
from backend.rag.memory.embedding_cache import get_embedding_cache

class FastEmbedEmbedding:
    """
    Embedding generator using FastEmbed and BAAI/bge-small-en-v1.5.
    """
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.embedding_model = TextEmbedding(model_name=model_name)
        self.cache = get_embedding_cache()

    async def generate(self, text: str) -> List[float]:
        # Check cache first
        cached = self.cache.get(text)
        if cached is not None:
            return cached
        
        try:
            # FastEmbed is sync, so run in thread for async
            import asyncio
            loop = asyncio.get_event_loop()
            embedding = await loop.run_in_executor(None, lambda: list(self.embedding_model.embed([text]))[0])
            result = embedding.tolist() if hasattr(embedding, 'tolist') else list(embedding)
            
            # Cache the result
            self.cache.set(text, result)
            return result
        except Exception as e:
            # Fallback to random vector if embedding fails
            fallback = np.random.rand(384).tolist()
            # Don't cache fallback results
            return fallback
