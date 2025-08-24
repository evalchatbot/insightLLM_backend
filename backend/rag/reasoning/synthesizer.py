# backend/rag/reasoning/synthesizer.py
from __future__ import annotations
from typing import List, Dict, Any
from backend.rag.memory.context_state import EvidenceSnippet
from backend.rag.models.schemas import Citation

FINAL_PROMPT = """You are a careful assistant. Using ONLY the EVIDENCE below, answer the USER QUESTION.
- If evidence is insufficient, say: "Not found in provided sources."
- Keep reasoning tight and structured.
- Do not invent details not present in evidence.
- Keep it concise but complete.

USER QUESTION:
{question}

EVIDENCE:
{evidence_block}

INSTRUCTIONS:
- Synthesize a single coherent answer grounded in the evidence.
- At the end, add a short "References" list with the evidence IDs you used, e.g., [E1, E3].
"""

def _format_evidence(evidence: List[EvidenceSnippet], max_chars_per_snippet: int = 1200) -> str:
    lines = []
    for i, s in enumerate(evidence, start=1):
        txt = (s.content or "")[:max_chars_per_snippet]
        lines.append(f"[E{i}] (doc={s.doc_id} chunk={s.chunk_id} src={s.source})\n{txt}\n")
    return "\n".join(lines)

async def generate_final_answer(
    llm_client: Any,
    question: str,
    evidence: List[EvidenceSnippet],
    temperature: float = 0.2,
    max_tokens: int = 900
) -> Dict[str, Any]:
    if not evidence:
        return {
            "answer": "Not found in provided sources.",
            "citations": [],
        }

    prompt = FINAL_PROMPT.format(
        question=question.strip(),
        evidence_block=_format_evidence(evidence)
    )
    answer = await llm_client.generate(prompt, temperature=temperature, max_tokens=max_tokens)

    # Build coarse citations (no char offsets yet)
    citations: List[Citation] = []
    for s in evidence:
        citations.append(Citation(
            doc_id=s.doc_id,
            chunk_id=s.chunk_id,
            source=s.source,
            start_char=0,
            end_char=0
        ))
    return {
        "answer": answer.strip(),
        "citations": citations,
    }
