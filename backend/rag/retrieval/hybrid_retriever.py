# backend/rag/retrieval/hybrid_retriever.py
from __future__ import annotations
from typing import List, Dict, Optional
from backend.rag.config import get_rag_settings
from backend.rag.memory.dedupe import dedupe_docs
from backend.rag.retrieval.bm25 import rerank_with_bm25
from backend.rag.telemetry.langsmith_tracer import trace_retrieval

# fastembed for embeddings
try:
    from fastembed import TextEmbedding
except Exception:
    TextEmbedding = None

class EmbeddingClient:
    def __init__(self, model_name: str):
        if TextEmbedding is None:
            raise RuntimeError("fastembed is not installed. Run: pip install fastembed")
        self.model = TextEmbedding(model_name)

    def embed(self, texts: List[str]) -> List[List[float]]:
        vectors: List[List[float]] = []
        for vec in self.model.embed(texts):
            # vec could be a NumPy array or iterable of np.float32 — normalize to plain floats
            if hasattr(vec, "tolist"):
                vectors.append([float(x) for x in vec.tolist()])
            else:
                vectors.append([float(x) for x in vec])
        return vectors

def _normalize_scores(docs: List[Dict], key: str) -> List[Dict]:
    if not docs:
        return docs
    vals = [d.get(key, 0.0) for d in docs]
    mn, mx = min(vals), max(vals)
    if mx <= mn:
        return docs
    out = []
    for d in docs:
        nd = dict(d)
        nd[key] = (d.get(key, 0.0) - mn) / (mx - mn)
        out.append(nd)
    return out

class HybridRetriever:
    """
    Supabase-only hybrid retriever:
      - Vector similarity via pgvector RPC (through SupabaseVectorStoreAdapter)
      - Keyword ilike on content, then BM25 re-rank on combined pool
      - Dedupe + final sort (0.6 * vector_score + 0.4 * bm25_score)
    """
    def __init__(self, adapter, top_k: Optional[int] = None):
        self.settings = get_rag_settings()
        self.adapter = adapter
        self.top_k = top_k or self.settings.TOP_K
        self.embedder = EmbeddingClient(self.settings.EMBEDDING_MODEL_NAME)

    @trace_retrieval(name="hybrid_retrieve")
    async def retrieve(self, query_text: str, filters: Optional[Dict] = None) -> List[Dict]:
        # 1) Embed query
        [q_emb] = self.embedder.embed([query_text])

        # 2) Initial hybrid from adapter (vector + keyword merged, vector-first)
        initial = await self.adapter.hybrid_search(
            text_query=query_text,
            query_embedding=q_emb,
            top_k=max(self.top_k * 2, self.top_k),
            filters=filters,
        )

        if not initial:
            return []

        # 3) Normalize vector 'score' so we can blend with BM25
        initial = _normalize_scores(initial, key="score")

        # 4) BM25 re-rank on content for keyword signal
        bm25_ranked = rerank_with_bm25(query_text, initial, top_k=len(initial))
        bm25_ranked = _normalize_scores(bm25_ranked, key="bm25_score")

        # 5) Merge scores: final_score = 0.6 * vector + 0.4 * bm25
        combined = []
        for d in bm25_ranked:
            nd = dict(d)
            vs = d.get("score", 0.0)
            ks = d.get("bm25_score", 0.0)
            nd["final_score"] = 0.6 * vs + 0.4 * ks
            combined.append(nd)

        # 6) Dedupe & sort by final_score desc, take top_k
        combined = dedupe_docs(combined)
        combined.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)
        return combined[: self.top_k]
