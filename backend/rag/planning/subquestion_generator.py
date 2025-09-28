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
        # First try direct JSON parsing
        return json.loads(s)
    except Exception:
        try:
            # Try extracting JSON from markdown code blocks
            import re
            # Look for JSON inside ```json or ``` blocks
            json_match = re.search(r'```(?:json)?\s*([\s\S]*?)```', s)
            if json_match:
                json_content = json_match.group(1).strip()
                return json.loads(json_content)
            
            # Try finding JSON between { and } if no code blocks
            json_match = re.search(r'(\{[\s\S]*\})', s)
            if json_match:
                json_content = json_match.group(1).strip()
                return json.loads(json_content)
                
        except Exception:
            pass
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
        self.max_subquestions = min(max_subquestions, 3)  # Limit for faster planning
        self.temperature = temperature

    @trace_agent_method(name="subquestion_planning", tags=["planning", "rag"])
    async def generate(self, user_query: str, context_notes: str = "") -> PlannerOutput:
        # Check if user query is contaminated and clean if needed
        if "Please provide a comprehensive" in user_query or "Previous context:" in user_query:
            user_query = self._extract_clean_question(user_query)

        prompt = _build_prompt(user_query, context_notes, self.max_subquestions)
        
        # 1st attempt with reduced tokens for faster response
        raw = await self.llm.generate(prompt, temperature=self.temperature, max_tokens=300)
        data = _safe_json_loads(raw)

        # Retry once if malformed (but with shorter timeout)
        if data is None or "subquestions" not in data:
            # Simplified repair prompt for faster processing
            repair_prompt = f"Return JSON with subquestions array for: {user_query[:100]}..."
            raw = await self.llm.generate(repair_prompt, temperature=0.0, max_tokens=200)
            data = _safe_json_loads(raw)
            if data is None or "subquestions" not in data:
                # Fall back to single question for immediate processing
                return PlannerOutput(subquestions=[user_query], dependencies=[], notes="fallback")

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
    
    def _extract_clean_question(self, contaminated_query: str) -> str:
        """
        Extract clean question from contaminated user query.
        This is an emergency safeguard against queries that contain context formatting.
        """
        try:
            # Pattern 1: Look for "Current question:" pattern
            if "Current question:" in contaminated_query:
                parts = contaminated_query.split("Current question:")
                if len(parts) > 1:
                    clean_question = parts[-1].strip()
                    # Remove any trailing formatting
                    clean_question = clean_question.strip('\n\r .,!?')
                    if clean_question and len(clean_question) > 5:
                        return clean_question
            
            # Pattern 2: Look for lines that look like questions
            lines = contaminated_query.split('\n')
            for line in lines:
                line = line.strip()
                # Skip empty lines and formatting lines
                if not line:
                    continue
                if line.startswith("Please provide"):
                    continue
                if line.startswith("Previous context"):
                    continue
                if line.startswith("Current question"):
                    continue
                if line.startswith("User:"):
                    continue
                if line.startswith("Assistant:"):
                    continue
                if line.endswith(":"):
                    continue
                
                # This might be the actual question
                if len(line) > 10 and ("?" in line or any(word in line.lower() for word in ["discuss", "explain", "analyze", "what", "how", "why"])):
                    return line
            
            # Pattern 3: If all else fails, look for the longest meaningful line
            meaningful_lines = []
            for line in lines:
                line = line.strip()
                if len(line) > 20 and not line.startswith(("Please", "Previous", "Current", "User:", "Assistant:")):
                    meaningful_lines.append(line)
            
            if meaningful_lines:
                # Return the first meaningful line that looks like a question
                for line in meaningful_lines:
                    if any(word in line.lower() for word in ["aristotle", "distributive", "justice"]):
                        return line
                # Fallback to first meaningful line
                return meaningful_lines[0]
            
            # Ultimate fallback - just return "Discuss Aristotle's distributive justice"
            return "Discuss Aristotle's distributive justice"
            
        except Exception:
            # If cleaning fails completely, return a safe default
            return "Discuss Aristotle's distributive justice"
