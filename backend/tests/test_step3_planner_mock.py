import asyncio
from backend.rag.planning.subquestion_generator import SubquestionGenerator
from backend.rag.planning.dependency_tracker import DependencyTracker

class MockLLM:
    async def generate(self, prompt: str, temperature: float = 0.0, max_tokens: int = 512) -> str:
        # Return valid JSON directly, pretending we parsed the prompt
        return """{
          "subquestions": [
            "What are the key components of the pipeline?",
            "How should retrieval be configured?",
            "What termination conditions should be used?"
          ],
          "dependencies": [
            {"child": "How should retrieval be configured?", "depends_on": "What are the key components of the pipeline?"}
          ],
          "notes": "Start broad, then specifics."
        }"""

async def test_planner_and_deps():
    planner = SubquestionGenerator(llm_client=MockLLM(), max_subquestions=5)
    out = await planner.generate(
        user_query="Design a recursive / multi-step RAG system for our chatbot",
        context_notes="We already have Supabase vector search."
    )
    print("✅ Planner subquestions:", out.subquestions)
    print("✅ Planner dependencies:", out.dependencies)

    tracker = DependencyTracker()
    tracker.add(out.subquestions, out.dependencies)

    # First ready (should be the first item; the dependency is on it)
    q1 = tracker.next_ready()
    print("✅ Next ready:", q1)
    tracker.mark_done(q1)

    # Then the dependent one should become ready
    q2 = tracker.next_ready()
    print("✅ Next ready after marking done:", q2)

    # Remaining
    rest = tracker.pending()
    print("✅ Remaining pending:", rest)

if __name__ == "__main__":
    asyncio.run(test_planner_and_deps())
