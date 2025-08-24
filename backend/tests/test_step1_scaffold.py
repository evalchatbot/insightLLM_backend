import asyncio
from backend.rag.config import get_rag_settings
from backend.rag.models.schemas import ChatRequest, ChatResponse, StepTrace, Citation
from backend.rag.memory.context_state import ContextState, EvidenceSnippet
from backend.rag.memory.dedupe import dedupe_docs
from backend.rag.memory.cache import TTLCache
from backend.rag.telemetry.tracing import span
from backend.rag.telemetry.metrics import metrics


def test_config_and_env():
    settings = get_rag_settings()
    print("✅ RAG Settings loaded:", settings.dict())


def test_models():
    req = ChatRequest(messages=[{"role": "user", "content": "Hello RAG"}])
    resp = ChatResponse(answer="Hi!", iterations=1)
    print("✅ ChatRequest:", req.dict())
    print("✅ ChatResponse:", resp.dict())


def test_context_and_evidence():
    ctx = ContextState()
    snippet = EvidenceSnippet(doc_id="1", chunk_id="c1", source="test", content="hello", score=0.9)
    ctx.add_evidence([snippet])
    ctx.enqueue_subquestions(["What is RAG?"])
    subq = ctx.pop_next_subquestion()
    print("✅ ContextState evidence:", ctx.accumulated_evidence)
    print("✅ ContextState subquestion dequeued:", subq)


def test_dedupe_and_cache():
    docs = [
        {"id": "1", "chunk_id": "c1", "content": "a", "score": 0.5},
        {"id": "1", "chunk_id": "c1", "content": "a", "score": 0.9},
    ]
    deduped = dedupe_docs(docs)
    print("✅ Deduped docs:", deduped)

    cache = TTLCache(ttl_s=2)
    cache.set("k", "value")
    print("✅ Cache get:", cache.get("k"))


def test_tracing_and_metrics():
    with span("test-span", foo="bar"):
        for i in range(3):
            metrics.inc("retrieval_calls")
        metrics.observe_ms("latency_total_ms", 123)

    print("✅ Metrics counters:", metrics.counters)
    print("✅ Metrics timers:", metrics.timers_ms)


if __name__ == "__main__":
    test_config_and_env()
    test_models()
    test_context_and_evidence()
    test_dedupe_and_cache()
    test_tracing_and_metrics()
