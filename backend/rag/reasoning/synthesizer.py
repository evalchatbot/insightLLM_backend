# backend/rag/reasoning/synthesizer.py
from __future__ import annotations
from typing import List, Dict, Any
from backend.rag.memory.context_state import EvidenceSnippet
from backend.rag.models.schemas import Citation
from backend.rag.telemetry.langsmith_tracer import trace_agent_method

FINAL_PROMPT = """You are an expert CSS exam preparation assistant. Using ONLY the EVIDENCE below, answer the USER QUESTION in CSS exam format.

REQUIRED FORMAT:
1. Introduction (2-3 sentences outlining the topic's significance)
2. Body (12-20 headings with detailed explanations based on evidence)
3. Conclusion (2-3 sentences summarizing key points for CSS candidates)

GUIDELINES:
- Use only information present in the evidence
- If evidence is insufficient, say: "Insufficient evidence in provided sources."
- Structure as a model CSS exam answer
- Include relevant examples and analysis from the evidence
- Maintain academic tone suitable for civil service examination

USER QUESTION:
{question}

EVIDENCE:
{evidence_block}

INSTRUCTIONS:
- Synthesize a comprehensive CSS exam-style answer grounded in the evidence
- Create 12-20 specific headings that cover different aspects of the topic
- Each heading should be a one-line summary followed by 2-4 explanatory sentences
- At the end, add a "References" section with evidence IDs used, e.g., [E1, E3]

Answer in CSS exam format:"""

def _format_evidence(evidence: List[EvidenceSnippet], max_chars_per_snippet: int = 1200) -> str:
    lines = []
    for i, s in enumerate(evidence, start=1):
        txt = (s.content or "")[:max_chars_per_snippet]
        lines.append(f"[E{i}] (doc={s.doc_id} chunk={s.chunk_id} src={s.source})\n{txt}\n")
    return "\n".join(lines)

@trace_agent_method(name="final_answer_synthesis", tags=["synthesis", "rag"])
async def generate_final_answer(
    llm_client: Any,
    question: str,
    evidence: List[EvidenceSnippet],
    temperature: float = 0.4,
    max_tokens: int = 2048
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
