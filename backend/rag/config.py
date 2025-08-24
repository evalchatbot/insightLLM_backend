from __future__ import annotations
from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache

class RAGSettings(BaseSettings):
    # Providers
    LLM_PROVIDER: str = Field("groq", description="groq|openai")
    GROQ_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # Vector backends
    VECTOR_BACKEND: str = Field("supabase", description="supabase|weaviate")

    # Supabase pgvector
    SUPABASE_URL: str | None = None
    SUPABASE_SERVICE_KEY: str | None = None
    SUPABASE_SCHEMA: str = "public"
    SUPABASE_TABLE: str = "documents"

    # Weaviate
    WEAVIATE_URL: str | None = None
    WEAVIATE_API_KEY: str | None = None
    WEAVIATE_INDEX: str = "Documents"

    # Embeddings
    EMBEDDING_MODEL_NAME: str = "BAAI/bge-small-en-v1.5"

    # Reranker + Safety
    ENABLE_RERANKER: bool = False
    ENABLE_PII_FILTER: bool = True
    ENABLE_INJECTION_GUARD: bool = True

    # Caching
    ENABLE_CACHE: bool = True
    CACHE_TTL_S: int = 600

    # Budgets
    MAX_ITERATIONS: int = 4
    TOP_K: int = 8
    MAX_TOKENS: int = 4096
    MAX_TIME_S: int = 30

    class Config:
        env_prefix = ""  # read directly from process env

@lru_cache
def get_rag_settings() -> RAGSettings:
    return RAGSettings()
