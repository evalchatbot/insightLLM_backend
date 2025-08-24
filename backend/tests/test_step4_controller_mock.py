# backend/tests/test_step4_controller_mock.py
import asyncio
from backend.rag.reasoning.graph_controller import run_controller
from backend.rag.retrieval.hybrid_retriever import HybridRetriever

# Reuse the Step-2 mock adapter
class MockSupabaseAdapter:
    async def hybrid_search(self, text_query, query_embedding, top_k, filters=None):
        return [
            {"id": "b1", "chunk_id": "c1", "source": "mock", "content": "Recursive RAG breaks tasks into sub-questions.", "score": 0.7, "metadata": {}},
            {"id": "b2", "chunk_id": "c2", "source": "mock", "content": "Hybrid retrieval mixes vector and keyword signals.", "score": 0.6, "metadata": {}},
            {"id": "b3", "chunk_id": "c3", "source": "mock", "content": "Termination can depend on max iterations or sufficiency.", "score": 0.5, "metadata": {}},
        ]

class MockLLM:
    async def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        # If it's a planner prompt (asks for JSON), return JSON
        if "Return JSON ONLY" in prompt or '"subquestions"' in prompt:
            return """{
              "subquestions": [
                "What are the key components of the pipeline?",
                "How should retrieval be configured?"
              ],
              "dependencies": [
                {"child":"How should retrieval be configured?","depends_on":"What are the key components of the pipeline?"}
              ],
              "notes": "Plan then implement."
            }"""
        # Otherwise it's the final synthesis
        return "A multi-step RAG system plans sub-questions, retrieves evidence iteratively, and synthesizes a grounded answer.\n\nReferences: [E1, E2]"

async def main():
    retriever = HybridRetriever(adapter=MockSupabaseAdapter(), top_k=2)
    result = await run_controller(
        messages=[{"role":"user","content":"Design a multi-step RAG pipeline for our chatbot."}],
        selection_filters=None,
        max_iterations=3,
        llm_client=MockLLM(),
        retriever=retriever,   # using mock retriever
        planner=None           # planner will be created with MockLLM
    )
    print("✅ Final answer:\n", result["answer"])
    print("✅ Iterations:", result["iterations"])
    print("✅ Traces:", [t.dict() for t in result["traces"]])
    print("✅ Citations:", [c.dict() for c in result["citations"]])

if __name__ == "__main__":
    asyncio.run(main())
