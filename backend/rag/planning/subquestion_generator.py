# backend/rag/planning/subquestion_generator.py
from __future__ import annotations
from typing import List, Dict, Optional, Any
import json
from dataclasses import dataclass
from backend.rag.telemetry.langsmith_tracer import trace_agent_method

DEFAULT_MAX_SUBQUESTIONS = 5

PLANNER_SYSTEM_INSTRUCTIONS = (
    "You are a precise planner that decomposes a complex user task into small, "
    "focused, answerable sub-questions. Output STRICT JSON only."
)

PLANNER_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "subquestions": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 0,
            "maxItems": DEFAULT_MAX_SUBQUESTIONS
        },
        "dependencies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "child": {"type": "string"},
                    "depends_on": {"type": "string"}
                },
                "required": ["child", "depends_on"]
            }
        },
        "notes": {"type": "string"}
    },
    "required": ["subquestions"],
    "additionalProperties": False
}

PLANNER_PROMPT_TEMPLATE = """{system_instructions}

USER_QUERY:
{user_query}

CONTEXT_NOTES:
{context_notes}

REQUIREMENTS:
- Decompose the user query into at most {k} concise sub-questions.
- Only include sub-questions that are necessary and non-overlapping.
- Prefer specific, answerable questions over broad ones.
- If some sub-questions must be answered before others, include "dependencies".
- Respond with STRICT JSON (no prose, no markdown).

JSON_SCHEMA (informal):
{subschema}

Return JSON ONLY with fields: "subquestions", "dependencies" (optional), "notes" (optional).
"""

def _build_prompt(user_query: str, context_notes: str, k: int) -> str:
    return PLANNER_PROMPT_TEMPLATE.format(
        system_instructions=PLANNER_SYSTEM_INSTRUCTIONS,
        user_query=user_query.strip(),
        context_notes=(context_notes or "").strip() or "(none)",
        k=k,
        subschema=json.dumps(PLANNER_JSON_SCHEMA, indent=2)
    )

def _safe_json_loads(s: str) -> Optional[Dict]:
    try:
        return json.loads(s)
    except Exception:
        return None

@dataclass
class PlannerOutput:
    subquestions: List[str]
    dependencies: List[Dict[str, str]]
    notes: str

class SubquestionGenerator:
    """
    Uses an async LLM client with a .generate(prompt: str, **kwargs) -> str method
    to produce a small set of sub-questions and optional dependencies.
    """
    def __init__(self, llm_client: Any, max_subquestions: int = DEFAULT_MAX_SUBQUESTIONS, temperature: float = 0.1):
        self.llm = llm_client
        self.max_subquestions = max_subquestions
        self.temperature = temperature

    @trace_agent_method(name="subquestion_planning", tags=["planning", "rag"])
    async def generate(self, user_query: str, context_notes: str = "") -> PlannerOutput:
        prompt = _build_prompt(user_query, context_notes, self.max_subquestions)

        # 1st attempt
        raw = await self.llm.generate(prompt, temperature=self.temperature, max_tokens=600)
        data = _safe_json_loads(raw)

        # Retry once if malformed
        if data is None or "subquestions" not in data:
            repair_prompt = (
                f"{prompt}\n\n"
                "The previous output was not valid JSON. Return STRICT JSON that matches the schema. "
                "Do not include any extra text."
            )
            raw = await self.llm.generate(repair_prompt, temperature=0.0, max_tokens=600)
            data = _safe_json_loads(raw)
            if data is None or "subquestions" not in data:
                # Fall back to empty plan
                return PlannerOutput(subquestions=[], dependencies=[], notes="")

        # Sanitize fields
        subqs = data.get("subquestions") or []
        subqs = [s.strip() for s in subqs if isinstance(s, str) and s.strip()]
        subqs = subqs[: self.max_subquestions]

        deps_raw = data.get("dependencies") or []
        deps: List[Dict[str, str]] = []
        for d in deps_raw:
            if not isinstance(d, dict):
                continue
            c = d.get("child")
            p = d.get("depends_on")
            if isinstance(c, str) and isinstance(p, str) and c.strip() and p.strip():
                deps.append({"child": c.strip(), "depends_on": p.strip()})

        notes = data.get("notes") if isinstance(data.get("notes"), str) else ""
        return PlannerOutput(subquestions=subqs, dependencies=deps, notes=notes)
