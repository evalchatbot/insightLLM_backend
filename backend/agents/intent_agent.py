"""
Intent Agent
Determines whether a user query is book-specific (use RAG/chatbot) or general/conversational.
Uses lightweight heuristics with optional LLM-assisted classification in future.
"""
from __future__ import annotations
from typing import Dict, Any, Optional, List
import re

from backend.utils.logging_config import get_logger
from backend.rag.llm.providers import get_llm
import json


class IntentAgent:
    """
    Classifies incoming queries into high-level intents:
    - book_specific: content/knowledge requests best handled by RAG
    - general: greetings, chit-chat, capabilities, meta-conversation
    """

    def __init__(self):
        self.logger = get_logger(__name__)
        try:
            self.llm = get_llm()
            model_name = getattr(self.llm, "model_name", None)
            self.logger.info(f"[INTENT] LLM initialized model={model_name or 'default'}")
        except Exception as e:
            self.logger.warning(f"[INTENT] LLM init failed, will use heuristics. err={e}")
            self.llm = None

        # Common conversational/generic patterns
        self._generic_patterns = [
            r"^(hi|hello|hey)\b",
            r"\bhow are you\b",
            r"\bwhat can you do\b",
            r"\bwho are you\b",
            r"\bhelp me\b",
            r"\bcan you help\b",
            r"\bthank(s| you)\b",
            r"\blet's chat\b",
            r"\btell me a joke\b",
            r"\bwhat's up\b",
            r"\bcapabilit(y|ies)\b",
            r"\bsmall talk\b",
        ]

        # Phrases that strongly indicate book/document specificity
        self._book_specific_hints = [
            r"\baccording to\b",
            r"\bin the book\b",
            r"\bin chapter\b",
            r"\bpage \d+\b",
            r"\bsource(s)?\b",
            r"\bcitation(s)?\b",
            r"\bfrom (author|paper|article|document)\b",
            r"\bdiscuss|explain|analy(z|s)e|compare|evaluate\b",
        ]

    def classify(self, question: str, *, genre: Optional[str] = None, book_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Return a dict: { intent: 'book_specific' | 'general', confidence: float, reason: str }
        Heuristics:
        - If explicit book_ids provided -> book_specific (high confidence)
        - If generic-pattern match and no book hints -> general (high confidence)
        - Else default to book_specific to favor grounded answers
        """
        q = (question or "").strip().lower()
        reason_parts: List[str] = []

        if book_ids and len(book_ids) > 0:
            reason_parts.append("book_ids provided")
            result = {"intent": "book_specific", "confidence": 0.95, "reason": ", ".join(reason_parts)}
            self.logger.info(
                f"[INTENT] Classified (book_specific via book_ids) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
            )
            return result

        # strong generic detection
        for pat in self._generic_patterns:
            if re.search(pat, q):
                reason_parts.append(f"matched generic pattern: {pat}")
                # If any book-specific hints also present, lower confidence
                has_book_hint = any(re.search(h, q) for h in self._book_specific_hints)
                conf = 0.6 if has_book_hint else 0.9
                result = {"intent": "general", "confidence": conf, "reason": ", ".join(reason_parts)}
                self.logger.info(
                    f"[INTENT] Classified (general via pattern) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
                )
                return result

        # book-specific hints
        if any(re.search(h, q) for h in self._book_specific_hints):
            reason_parts.append("book/document hint present")
            result = {"intent": "book_specific", "confidence": 0.8, "reason": ", ".join(reason_parts)}
            self.logger.info(
                f"[INTENT] Classified (book_specific via hint) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
            )
            return result

        # Lengthy or content-focused queries default to book-specific
        if len(q) > 60 or any(w in q for w in ["explain", "discuss", "analyze", "evaluate", "summarize", "what", "how", "why", "compare", "contrast"]):
            reason_parts.append("content-focused cue or length")
            result = {"intent": "book_specific", "confidence": 0.7, "reason": ", ".join(reason_parts)}
            self.logger.info(
                f"[INTENT] Classified (book_specific via content cues) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
            )
            return result

        # Default to general if it's short and lacks specificity
        if len(q) < 20:
            reason_parts.append("short and non-specific")
            result = {"intent": "general", "confidence": 0.6, "reason": ", ".join(reason_parts)}
            self.logger.info(
                f"[INTENT] Classified (general via short/unspecific) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
            )
            return result

        # Safe default
        reason_parts.append("default safety: prefer grounded")
        result = {"intent": "book_specific", "confidence": 0.6, "reason": ", ".join(reason_parts)}
        self.logger.info(
            f"[INTENT] Classified (default book_specific) conf={result['confidence']:.2f} reason={result['reason']} q='{q[:200]}'"
        )
        return result

    async def classify_async(self, question: str, *, genre: Optional[str] = None, book_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        LLM-based intent classification. Returns a dict with keys: intent, confidence, reason.
        Falls back to heuristic classify() on failure or missing LLM.
        """
        if not self.llm:
            return self.classify(question, genre=genre, book_ids=book_ids)

        try:
            q = (question or "").strip()
            hints = {
                "genre": genre or "",
                "book_ids_present": bool(book_ids and len(book_ids) > 0),
            }
            instruction = (
                "You are an intent classifier for a routing system. Classify the user's message as either "
                "'book_specific' (asks for topical knowledge, facts, explanations likely grounded in books/documents) "
                "or 'general' (greetings, small-talk, meta questions about capabilities).\n"
                "Return strict JSON with keys: intent ('book_specific'|'general'), confidence (0-1 float), reason (short string).\n"
                "Do not include any text outside of the JSON."
            )
            examples = (
                "Examples:\n"
                "User: 'hi' => {\"intent\": \"general\", \"confidence\": 0.95, \"reason\": \"greeting\"}\n"
                "User: 'what can you do?' => {\"intent\": \"general\", \"confidence\": 0.9, \"reason\": \"meta/capabilities\"}\n"
                "User: 'According to chapter 2 explain federalism' => {\"intent\": \"book_specific\", \"confidence\": 0.9, \"reason\": \"references book/chapter\"}\n"
                "User: 'Discuss causes of poverty' => {\"intent\": \"book_specific\", \"confidence\": 0.75, \"reason\": \"content-focused explanation\"}\n"
            )
            hint_text = f"Hints: genre='{hints['genre']}', book_ids_present={hints['book_ids_present']}\n"
            user_block = f"User: {q}"
            prompt = f"{instruction}\n\n{examples}\n\n{hint_text}{user_block}\n\nJSON:"

            self.logger.info("[INTENT] LLM classification requested")
            raw = await self.llm.generate(prompt, temperature=0.0, max_tokens=120)
            self.logger.info(f"[INTENT] LLM raw: {raw[:300].replace(chr(10),' ')}")

            parsed: Dict[str, Any]
            try:
                # Extract JSON object if wrapped
                m = re.search(r"\{[\s\S]*\}", raw)
                json_str = m.group(0) if m else raw
                parsed = json.loads(json_str)
            except Exception as e:
                self.logger.warning(f"[INTENT] JSON parse failed, falling back. err={e}")
                return self.classify(question, genre=genre, book_ids=book_ids)

            intent = str(parsed.get("intent", "")).strip().lower()
            if intent not in ("book_specific", "general"):
                self.logger.warning(f"[INTENT] Invalid intent '{intent}', falling back to heuristics")
                return self.classify(question, genre=genre, book_ids=book_ids)

            confidence = parsed.get("confidence")
            try:
                confidence = float(confidence)
            except Exception:
                confidence = 0.6

            reason = parsed.get("reason") or "LLM classification"
            result = {"intent": intent, "confidence": max(0.0, min(1.0, confidence)), "reason": reason}
            self.logger.info(
                f"[INTENT] LLM Classified intent={result['intent']} conf={result['confidence']:.2f} reason={result['reason']}"
            )
            return result

        except Exception as e:
            self.logger.error(f"[INTENT] LLM classification failed, using heuristics. err={e}")
            return self.classify(question, genre=genre, book_ids=book_ids)
