# backend/rag/reasoning/graph_controller.py
from __future__ import annotations
from typing import List, Dict, Optional, Any
import asyncio
import time
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
    Optimized multi-step RAG controller:
    1) Plan sub-questions (reduced iterations)
    2) Parallel retrieval for independent sub-questions
    3) Early stopping when sufficient evidence is found
    4) Fast synthesis with timeout protection
    """
    settings = get_rag_settings()
    max_iters = max_iterations or settings.MAX_ITERATIONS
    start_time = time.time()
    max_time = settings.MAX_TIME_S
    
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

    # Initial plan - optimize for faster planning
    plan = await planner.generate(user_query=user_query, context_notes=ctx.notes)
    if not plan.subquestions:
        # Fallback: treat the whole query as one sub-question
        plan.subquestions = [user_query]
    tracker.add(plan.subquestions, plan.dependencies)

    # Parallel processing for independent subquestions
    async def process_subquestion(subq: str, iteration: int) -> tuple[str, List[EvidenceSnippet], int]:
        """Process a single subquestion and return results."""
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
        clean_snips = sanitize_snippets(evidence_snips)
        return subq, clean_snips, iteration

    for it in range(max_iters):
        # Check timeout
        if time.time() - start_time > max_time:
            break
            
        ctx.iteration = it + 1

        # Get all ready subquestions for parallel processing
        ready_subqs = []
        while True:
            subq = tracker.next_ready()
            if not subq:
                break
            ready_subqs.append(subq)
            
        if not ready_subqs:
            # If queue empty, try planning more (but limit to avoid infinite loops)
            if not tracker.pending() and it < max_iters - 1:
                extra_plan = await planner.generate(
                    user_query=user_query,
                    context_notes=ctx.notes + "\nAlready explored: " + ", ".join(list(tracker.done))
                )
                if extra_plan.subquestions:
                    tracker.add(extra_plan.subquestions, extra_plan.dependencies)
                    continue
            break  # nothing to do

        # Process subquestions in parallel if enabled
        if settings.PARALLEL_SUBQUESTION_RETRIEVAL and len(ready_subqs) > 1:
            tasks = [process_subquestion(subq, ctx.iteration) for subq in ready_subqs]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    continue  # Skip failed retrievals
                subq, clean_snips, iteration = result
                if clean_snips:
                    ctx.add_evidence(clean_snips)
                tracker.mark_done(subq)
                
                # Add trace for this subquestion
                traces.append(StepTrace(
                    iteration=iteration,
                    subquestions=[subq],
                    retrieved_ids=[f"{s.doc_id}:{s.chunk_id}" for s in clean_snips],
                    notes=f"Retrieved {len(clean_snips)} snippets (parallel)."
                ))
        else:
            # Sequential processing for single subquestion or when parallel is disabled
            for subq in ready_subqs:
                subq_result, clean_snips, iteration = await process_subquestion(subq, ctx.iteration)
                if clean_snips:
                    ctx.add_evidence(clean_snips)
                tracker.mark_done(subq)
                
                traces.append(StepTrace(
                    iteration=iteration,
                    subquestions=[subq],
                    retrieved_ids=[f"{s.doc_id}:{s.chunk_id}" for s in clean_snips],
                    notes=f"Retrieved {len(clean_snips)} snippets."
                ))

        # Early stopping: check if we have sufficient evidence
        if (settings.ENABLE_EARLY_STOPPING and 
            has_sufficient_evidence(ctx.accumulated_evidence, min_docs=settings.MIN_EVIDENCE_THRESHOLD)):
            break
            
        # Also break if no more pending and we have some evidence
        if not tracker.pending() and len(ctx.accumulated_evidence) > 0:
            break

    # Final synthesis with timeout protection
    synthesis_start = time.time()
    if llm_client is None:
        # No LLM to synthesize; return a stub summary of evidence
        answer = "Collected evidence snippets but no LLM provided to synthesize final answer."
        citations = []
    else:
        # Check if we have time left for synthesis
        time_remaining = max_time - (time.time() - start_time)
        if time_remaining < 2:  # Need at least 2 seconds for synthesis
            answer = "Timeout: Insufficient time for final synthesis."
            citations = []
        else:
            try:
                # Use appropriate token limit for CSS exam format
                max_tokens = 1024 if time_remaining < 10 else 2048
                gen = await asyncio.wait_for(
                    generate_final_answer(
                        llm_client=llm_client,
                        question=user_query,
                        evidence=ctx.accumulated_evidence,
                        max_tokens=max_tokens
                    ),
                    timeout=min(time_remaining - 1, 10)  # Leave 1 second buffer
                )
                answer = gen["answer"]
                citations = gen["citations"]
            except asyncio.TimeoutError:
                answer = "Timeout: Final synthesis took too long."
                citations = []
            except Exception as e:
                answer = f"Synthesis error: {str(e)}"
                citations = []

    total_time = time.time() - start_time
    return {
        "answer": answer,
        "citations": citations,
        "iterations": ctx.iteration,
        "traces": traces,
        "budget_used": {
            "iterations": ctx.iteration,
            "total_time_s": round(total_time, 2),
            "evidence_count": len(ctx.accumulated_evidence)
        },
    }
