import asyncio
from backend.rag.retrieval.hybrid_retriever import HybridRetriever
from backend.rag.adapters.supabase_store import SupabaseVectorStoreAdapter

class MockSBResponse:
    def __init__(self, data): self.data = data
    def execute(self): return self

class MockSBTable:
    def __init__(self, rows): self.rows = rows
    def select(self, *_): return self
    def in_(self, *_): return self
    def ilike(self, *_): return self
    def limit(self, *_): return self
    @property
    def data(self): return self.rows

class MockService:
    def __init__(self):
        self.supabase = self
        self._rows = [
            {"id":"c1","book_id":"b1","content":"Recursive RAG with BM25 and vector search.","page_start":1,"page_end":2,"chunk_index":0,"score":0.7},
            {"id":"c2","book_id":"b2","content":"Hybrid retrieval combines keyword and embeddings.","page_start":3,"page_end":4,"chunk_index":1,"score":0.5},
            {"id":"c3","book_id":"b3","content":"BM25 ranks by keyword relevance.","page_start":5,"page_end":6,"chunk_index":2,"score":0.4},
        ]

    # For adapter.hybrid_search keyword fallback
    def table(self, *_):
        return MockSBTable(self._rows)

    # Your RPC wrapper; we just return a subset with prefilled scores
    async def search_chunks_vector(self, query_embedding, book_ids, top_k=5):
        return self._rows[:min(top_k, len(self._rows))]

async def main():
    adapter = SupabaseVectorStoreAdapter(service=MockService())
    retriever = HybridRetriever(adapter, top_k=2)
    res = await retriever.retrieve("How does hybrid recursive RAG work?", filters=None)
    print("✅ Retrieved:", [{"id": r["id"], "chunk_id": r["chunk_id"], "final_score": round(r["final_score"], 3)} for r in res])

if __name__ == "__main__":
    asyncio.run(main())
