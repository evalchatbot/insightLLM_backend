# backend/rag/reasoning/graph_controller.py
from __future__ import annotations
from typing import List, Dict, Optional, Any
import asyncio
from backend.rag.config import get_rag_settings
from backend.rag.models.schemas import StepTrace
from backend.rag.memory.context_state import ContextState, EvidenceSnippet
from backend.rag.planning.subquestion_generator import SubquestionGenerator
from backend.rag.planning.dependency_tracker import DependencyTracker
from backend.rag.retrieval.hybrid_retriever import HybridRetriever
from backend.rag.adapters.supabase_store import SupabaseVectorStoreAdapter
from backend.rag.reasoning.validator import sanitize_snippets, has_sufficient_evidence
from backend.rag.reasoning.synthesizer import generate_final_answer
from backend.rag.telemetry.langsmith_tracer import trace_agent_method, LangSmithTracer

# helper: get last user turn
def _last_user_query(messages: List[Dict]) -> str:
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return str(m.get("content", "")).strip()
    return ""

@trace_agent_method(name="rag_controller", tags=["rag", "controller", "multi_step"])
async def run_controller(
    messages: List[Dict],
    selection_filters: Optional[Dict] = None,
    max_iterations: Optional[int] = None,
    llm_client: Any = None,
    retriever: Optional[HybridRetriever] = None,
    planner: Optional[SubquestionGenerator] = None,
) -> Dict[str, Any]:
    """
    Orchestrates multi-step RAG:
    1) Plan sub-questions
    2) Retrieve evidence per sub-question
    3) Validate/sanitize evidence
    4) Optionally plan more when queue runs low
    5) Synthesize grounded final answer
    """
    settings = get_rag_settings()
    max_iters = max_iterations or settings.MAX_ITERATIONS
    user_query = _last_user_query(messages)
    if not user_query:
        return {"answer": "No user query found.", "citations": [], "iterations": 0, "traces": [], "budget_used": {}}

    # Instantiate dependencies if not provided
    if retriever is None:
        # Build via your SupabaseService automatically if available
        try:
            from backend.db.supabase_service import SupabaseService  # <- your code
            svc = SupabaseService(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)
            adapter = SupabaseVectorStoreAdapter(svc)
            retriever = HybridRetriever(adapter, top_k=settings.TOP_K)
        except Exception as e:
            raise RuntimeError(f"Retriever not provided and could not init Supabase: {e}")

    if planner is None:
        if llm_client is None:
            raise RuntimeError("Planner requires an llm_client with .generate(prompt, **kwargs).")
        planner = SubquestionGenerator(llm_client=llm_client, max_subquestions=5, temperature=0.1)

    ctx = ContextState()
    tracker = DependencyTracker()
    traces: List[StepTrace] = []

    # Initial plan
    plan = await planner.generate(user_query=user_query, context_notes=ctx.notes)
    if not plan.subquestions:
        # Fallback: treat the whole query as one sub-question
        plan.subquestions = [user_query]
    tracker.add(plan.subquestions, plan.dependencies)

    for it in range(max_iters):
        ctx.iteration = it + 1

        # pick next ready sub-question
        subq = tracker.next_ready()
        if not subq:
            # If queue empty, try planning more using context/evidence (simple heuristic)
            if not tracker.pending():
                extra_plan = await planner.generate(
                    user_query=user_query,
                    context_notes=ctx.notes + "\nAlready explored: " + ", ".join(list(tracker.done))
                )
                tracker.add(extra_plan.subquestions, extra_plan.dependencies)
                subq = tracker.next_ready()

            if not subq:
                break  # nothing to do

        # Retrieve for this sub-question
        docs = await retriever.retrieve(subq, filters=selection_filters)
        evidence_snips = [
            EvidenceSnippet(
                doc_id=d.get("id", ""),
                chunk_id=d.get("chunk_id", ""),
                source=d.get("source", "unknown"),
                content=d.get("content", ""),
                score=float(d.get("final_score", d.get("score", 0.0))),
                metadata=d.get("metadata", {}) or {}
            )
            for d in docs
        ]

        # Validate/sanitize
        clean_snips = sanitize_snippets(evidence_snips)
        if clean_snips:
            ctx.add_evidence(clean_snips)

        # (Optional) basic sufficiency check could influence re-plan; keep simple for now
        tracker.mark_done(subq)

        # Trace
        traces.append(StepTrace(
            iteration=ctx.iteration,
            subquestions=[subq],
            retrieved_ids=[f"{s.doc_id}:{s.chunk_id}" for s in clean_snips],
            notes=f"Retrieved {len(clean_snips)} snippets."
        ))

        # Simple early-stop: if queue empty after answering a couple items and we have solid evidence
        if not tracker.pending() and has_sufficient_evidence(ctx.accumulated_evidence, min_docs=2):
            break

    # Final synthesis
    if llm_client is None:
        # No LLM to synthesize; return a stub summary of evidence
        answer = "Collected evidence snippets but no LLM provided to synthesize final answer."
        citations = []
    else:
        gen = await generate_final_answer(
            llm_client=llm_client,
            question=user_query,
            evidence=ctx.accumulated_evidence
        )
        answer = gen["answer"]
        citations = gen["citations"]

    return {
        "answer": answer,
        "citations": citations,
        "iterations": ctx.iteration,
        "traces": traces,
        "budget_used": {"iterations": ctx.iteration},
    }
