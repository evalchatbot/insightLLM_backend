"""
Chatbot Agent tuned for Pakistani competitive exam preparation.
Provides teacher-style answers without any RAG dependencies.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional

from backend.db.supabase_service import SupabaseService
from backend.memory.long_term import LongTermMemory
from backend.memory.short_term import ShortTermMemory
from backend.rag.llm.streaming_client import StreamingLLMClient, get_streaming_llm_client
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)


SYSTEM_PROMPT = (
    "System Prompt: Pakistani Competitive Exam Mentor\n"
    "You specialise in Political Science and governance for Pakistani competitive examinations.\n"
    "Core rules you must ALWAYS obey:\n"
    "1. Follow the custom instructions supplied in the user prompt exactly—they may override or narrow the default exam structure.\n"
    "2. Think aloud (internally) about the task before drafting. Identify the directives (define, compare, critique, apply, etc.) and satisfy each one explicitly.\n"
    "3. Maintain a scholarly yet approachable tone. Use evidence (constitutional articles, case law, theorists, contemporary events) whenever relevant.\n"
    "4. Every argument must be analytical: state the point, explain the reasoning, anchor it in Pakistan/global context, and (where apt) balance with critique.\n"
    "5. Never repeat sentences or recycle the same argument under different headings.\n"
    "6. Never mention the acronym 'CSS'.\n"
    "7. When instructed to provide exam-technique guidance, it must appear after the conclusion.\n"
)

SYSTEM_PROMPT_ID = "css-pol-sci.v3"


TITLE_PROMPT_TEMPLATE = (
    "You are naming a chat for a Pakistani CSS/PMS aspirant.\n"
    "Student question: \"{question}\"\n"
    "Mentor answer (summary): \"{answer}\".\n"
    "Produce a concise title (max 6 words) that reflects the exam-prep focus. "
    "Use Title Case and avoid punctuation except spaces or hyphen."
)


class ChatbotAgent:
    """
    A lightweight, non-RAG chatbot tailored for Pakistani competitive exams.
    """

    def __init__(self) -> None:
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self._streaming_client: Optional[StreamingLLMClient] = None

        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        if supabase_url and supabase_key:
            try:
                self.db_service = SupabaseService(supabase_url, supabase_key)
                logger.info("[CHATBOT] Supabase service initialised")
            except Exception as exc:
                logger.error(f"[CHATBOT] Failed to init Supabase service: {exc}")
                self.db_service = None
        else:
            self.db_service = None
            logger.warning("[CHATBOT] Supabase service not configured; skipping persistence")

    # ------------------------------------------------------------------ #
    # Public API used by FastAPI routes
    # ------------------------------------------------------------------ #
    async def ask(
        self,
        user_id: str,
        session_id: str,
        question: str,
        genre: str = "general",
        book_ids: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, object]:
        """
        Generate a complete answer (non-streaming) while maintaining context.
        """
        cleaned_question = self._sanitize_question(question)
        analysis = await self._analyze_question(cleaned_question)
        context = await self._get_context(user_id, session_id, conversation_id)
        user_prompt = self._build_user_prompt(cleaned_question, context, analysis)

        start = time.time()
        answer, token_usage = await self._ensure_streaming_client().generate_complete(
            prompt=user_prompt,
            temperature=0.3,
            max_tokens=3200,
            system_message=SYSTEM_PROMPT,
        )

        update_info = await self._update_memory(
            user_id=user_id,
            session_id=session_id,
            question=cleaned_question,
            answer=answer,
            conversation_id=conversation_id,
        )

        metadata = {
            "mode": "single_llm",
            "system_prompt": SYSTEM_PROMPT_ID,
            "context_messages": len(context),
            "response_time": round(time.time() - start, 3),
            "question_analysis": analysis,
            "token_usage": token_usage,
        }
        if update_info:
            metadata.update({k: v for k, v in update_info.items() if v is not None})

        return {
            "answer": answer,
            "sources": [],
            "citations": [],
            "context": context,
            "metadata": metadata,
        }

    async def ask_fast(
        self,
        user_id: str,
        session_id: str,
        question: str,
        genre: str = "general",
        book_ids: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, object]:
        """
        Backwards-compatibility wrapper; fast mode now equals standard ask.
        """
        return await self.ask(
            user_id=user_id,
            session_id=session_id,
            question=question,
            genre=genre,
            book_ids=book_ids,
            conversation_id=conversation_id,
        )

    async def ask_multi_step(
        self,
        user_id: str,
        session_id: str,
        question: str,
        genre: str = "general",
        book_ids: Optional[List[str]] = None,
        max_iterations: int = 2,
        conversation_id: Optional[str] = None,
    ) -> Dict[str, object]:
        """
        Multi-step mode is deprecated; delegate to single-call response.
        """
        return await self.ask(
            user_id=user_id,
            session_id=session_id,
            question=question,
            genre=genre,
            book_ids=book_ids,
            conversation_id=conversation_id,
        )

    async def stream_answer(
        self,
        user_id: str,
        session_id: str,
        question: str,
        genre: str = "general",
        book_ids: Optional[List[str]] = None,
        conversation_id: Optional[str] = None,
    ) -> AsyncGenerator[str, None]:
        """
        Stream answer chunks while keeping memory updated after completion.
        """
        cleaned_question = self._sanitize_question(question)
        analysis = await self._analyze_question(cleaned_question)
        context = await self._get_context(user_id, session_id, conversation_id)
        user_prompt = self._build_user_prompt(cleaned_question, context, analysis)

        llm_stream = self._ensure_streaming_client().generate_stream(
            prompt=user_prompt,
            temperature=0.3,
            max_tokens=3200,
            system_message=SYSTEM_PROMPT,
        )

        agent = self

        class StreamWrapper:
            def __init__(self):
                self._iterator = llm_stream.__aiter__()
                self.collected: List[str] = []
                self.answer: str = ""
                self.update_info: Dict[str, Optional[str]] = {}
                self.context_messages = len(context)
                self.analysis = analysis
                self.token_usage: Optional[Dict[str, int]] = None

            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    chunk, usage_info = await self._iterator.__anext__()
                except StopAsyncIteration:
                    self.answer = "".join(self.collected).strip()
                    
                    # If token usage wasn't provided, calculate it from the full response
                    if self.token_usage is None or self.token_usage.get("completion_tokens", 0) == 0:
                        from backend.utils.usage_tracking import get_token_count
                        full_prompt = SYSTEM_PROMPT + "\n\n" + user_prompt
                        prompt_tokens = get_token_count(full_prompt, model="gpt-4")
                        completion_tokens = get_token_count(self.answer, model="gpt-4")
                        self.token_usage = {
                            "prompt_tokens": prompt_tokens,
                            "completion_tokens": completion_tokens,
                            "total_tokens": prompt_tokens + completion_tokens
                        }
                    
                    self.update_info = await agent._update_memory(
                        user_id=user_id,
                        session_id=session_id,
                        question=cleaned_question,
                        answer=self.answer,
                        conversation_id=conversation_id,
                    )
                    raise StopAsyncIteration
                else:
                    if chunk:
                        self.collected.append(chunk)
                        return chunk
                    elif usage_info:
                        # Store token usage info
                        self.token_usage = usage_info
                        # If we have the full answer collected, we can calculate completion tokens
                        if self.collected and usage_info.get("completion_tokens", 0) == 0:
                            from backend.utils.usage_tracking import get_token_count
                            full_answer = "".join(self.collected)
                            completion_tokens = get_token_count(full_answer, model="gpt-4")
                            self.token_usage["completion_tokens"] = completion_tokens
                            self.token_usage["total_tokens"] = usage_info.get("prompt_tokens", 0) + completion_tokens
                        # Skip yielding None chunks
                        return await self.__anext__()
                    else:
                        # Both None, skip
                        return await self.__anext__()

        return StreamWrapper()

    # ------------------------------------------------------------------ #
    # Conversation utilities
    # ------------------------------------------------------------------ #
    async def create_conversation_with_title(
        self,
        user_id: str,
        question: str,
        answer: str,
        icon: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new conversation with an auto-generated, exam-themed title.
        """
        if not self.db_service:
            logger.warning("[CHATBOT] Cannot auto-create conversation without Supabase service")
            return None

        try:
            title = await self._generate_conversation_title(question, answer)
            conversation_data = {
                "user_id": user_id,
                "title": title,
                "icon": icon,
                "is_pinned": False,
            }
            result = self.db_service.create_conversation(conversation_data)
            return result.get("id") if result else None
        except Exception as exc:
            logger.error(f"[CHATBOT] Failed to create conversation with title: {exc}")
            return None

    async def get_agent_capabilities(self) -> Dict[str, object]:
        """
        Diagnostic helper for API consumers.
        """
        return {
            "agent_type": "single_llm",
            "system_prompt": SYSTEM_PROMPT_ID,
            "supports_streaming": True,
            "rag_enabled": False,
            "memory": {
                "short_term": True,
                "long_term": True,
                "summarisation_threshold": self.short_term.summarization_threshold,
            },
        }

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _ensure_streaming_client(self) -> StreamingLLMClient:
        if not self._streaming_client:
            self._streaming_client = get_streaming_llm_client()
        return self._streaming_client

    async def _get_context(
        self,
        user_id: str,
        session_id: str,
        conversation_id: Optional[str],
    ) -> List[Dict[str, str]]:
        try:
            if conversation_id and self.db_service:
                records = self.db_service.get_recent_conversation_messages(conversation_id, limit=8)
                context: List[Dict[str, str]] = []
                for record in records:
                    if record.get("user_prompt"):
                        context.append(
                            {
                                "sender": "user",
                                "message": record.get("user_prompt", ""),
                                "timestamp": record.get("created_at"),
                            }
                        )
                    if record.get("llm_response"):
                        context.append(
                            {
                                "sender": "assistant",
                                "message": record.get("llm_response", ""),
                                "timestamp": record.get("created_at"),
                            }
                        )
                return context[-8:]
            return self.short_term.get_recent_messages(user_id, session_id)
        except Exception as exc:
            logger.warning(f"[CHATBOT] Failed to load context: {exc}")
            return []

    def _build_user_prompt(self, question: str, context: List[Dict[str, str]], analysis: Dict[str, Any]) -> str:
        parts: List[str] = []

        if context:
            trimmed = context[-6:]
            history_lines = []
            for entry in trimmed:
                role = entry.get("sender", "user").title()
                message = entry.get("message", "").strip()
                if message:
                    history_lines.append(f"{role}: {message}")
            if history_lines:
                parts.append("Recent exchange (latest last):")
                parts.append("\n".join(history_lines))

        cleaned_question = question.strip()
        mode = analysis.get("mode", "essay")
        directives = analysis.get("directives", [])
        reasoning = analysis.get("reasoning_focus", [])
        comparison_pairs = analysis.get("comparison_pairs", [])
        principles = analysis.get("principles", [])
        multi_parts = analysis.get("multi_part_breakdown", [])
        expected_length = analysis.get("expected_length", "essay")

        if mode == "brief":
            parts.append("Question:")
            parts.append(cleaned_question)
            parts.append(
                "Generate a concise, high-quality response (120–180 words). "
                "Address the user's need directly with clear reasoning, cite at least one relevant concept or fact, "
                "and adopt a supportive mentor tone. No headings are required for short responses."
            )
            return "\n\n".join(parts)

        parts.append("Exam Question:")
        parts.append(cleaned_question)

        instructions: List[str] = [
            "Use Markdown with consistent heading levels. Major sections must appear as level-two headings (`##`).",
            "Begin with `## Introduction` containing four tightly written sentences (70–90 words). Frame the thesis, define the key concept(s), and preview every strand you will cover. Never greet or mention yourself.",
            "After the introduction, outline the discussion with numbered level-two headings: `## 1. ...`, `## 2. ...`, etc. Each heading title must encapsulate an argument or theme rather than repeat the question.",
        ]

        suggested_min = analysis.get("suggested_subheadings_min", 10)
        suggested_max = analysis.get("suggested_subheadings_max", 14)
        instructions.append(
            f"Within those numbered sections, create between {suggested_min} and {suggested_max} distinct level-three subheadings (`### 1.1 ...`, `### 1.2 ...`, etc.). "
            "Each subheading must be a single analytical claim (cause → effect or argument → implication) followed by a paragraph of 90–110 words."
        )

        if principles:
            instructions.append(
                "Dedicate the earliest subheadings to enumerating each core principle individually before moving to applications or critiques. "
                f"The principles to cover include: {', '.join(principles)}."
            )

        if comparison_pairs:
            for pair in comparison_pairs:
                instructions.append(
                    f"Include a dedicated comparative subheading contrasting {pair.get('item_a')} and {pair.get('item_b')} with evaluative commentary."
                )

        if multi_parts:
            instructions.append(
                "Explicitly resolve every part of the prompt. Use distinct numbered headings or clustered subheadings for each component:\n"
                + "\n".join(f"- {item}" for item in multi_parts)
            )

        if reasoning:
            instructions.append(
                "For each subheading, emphasise reasoning styles: "
                + ", ".join(reasoning)
                + ". Make the logic transparent—state the claim, explain causality, cite supporting evidence, then offer Pakistan/global linkage."
            )

        instructions.extend(
            [
                "Integrate critiques and contemporary relevance within the body instead of isolating them at the end. "
                "Draw on theorists (classical and modern), jurisprudence, and Pakistan-specific governance experience.",
                "Employ bullet lists for enumerations, comparative takeaways, or policy recommendations so the answer remains scannable.",
                "Target a total length between 1,100 and 1,400 words unless explicitly told otherwise.",
                "Add `## Conclusion` to synthesise the discussion and deliver a reasoned judgement.",
                "Finish with `## Exam Technique Guidance` containing 3–4 concise bullet points tailored to this question. This section must always be last.",
                "Never mention the acronym 'CSS'.",
            ]
        )

        parts.append("Obligations for this answer:")
        parts.append("\n".join(f"- {item}" for item in instructions))

        rubric_notes = []
        if directives:
            rubric_notes.append("Address the following directives explicitly: " + ", ".join(directives))
        key_terms = analysis.get("key_terms")
        if key_terms:
            rubric_notes.append("Key terms to weave into the discussion: " + ", ".join(key_terms))
        if not rubric_notes:
            rubric_notes.append(
                "Use constitutional references, landmark cases, and current affairs to illustrate points wherever relevant."
            )

        parts.append("Evaluator reminders (keep internal, do not echo verbatim):")
        parts.append("\n".join(f"• {note}" for note in rubric_notes))
        parts.append(
            "Write the answer now, adhering strictly to the obligations above. "
            "Ensure coverage of every directive and maintain analytical depth throughout."
        )
        return "\n\n".join(parts)

    def _sanitize_question(self, raw: str) -> str:
        try:
            if not raw:
                return raw
            if "Current question:" in raw:
                raw = raw.split("Current question:")[-1]
            lines = [line.strip() for line in raw.splitlines() if line.strip()]
            for line in lines:
                if line.endswith(":"):
                    continue
                if line.lower().startswith(("user:", "assistant:")):
                    continue
                if len(line) > 6:
                    return line
            return raw.strip()
        except Exception:
            return raw

    async def _generate_conversation_title(self, question: str, answer: str) -> str:
        prompt = TITLE_PROMPT_TEMPLATE.format(
            question=question.strip(),
            answer=answer.strip()[:300],
        )
        title, _ = await self._ensure_streaming_client().generate_complete(
            prompt=prompt,
            temperature=0.4,
            max_tokens=32,
            system_message="You craft short, exam-focused chat titles.",
        )
        cleaned = title.replace("\n", " ").strip("\"' ").strip()
        return cleaned[:60] or "CSS Prep Chat"

    async def _analyze_question(self, question: str) -> Dict[str, Any]:
        stripped = question.strip()
        if not stripped:
            return {"mode": "brief", "reason": "empty_question"}

        lower = stripped.lower()
        words = re.findall(r"\w+", lower)
        word_count = len(words)

        greetings = {"hi", "hello", "hey", "salam", "salaam", "thank", "thanks", "good morning", "good evening"}
        if word_count <= 4 and any(greet in lower for greet in greetings):
            return {
                "mode": "brief",
                "tone": "polite acknowledgement",
                "directives": [],
                "reasoning_focus": [],
                "expected_length": "short",
            }

        essay_triggers = [
            "discuss",
            "evaluate",
            "critically",
            "analyse",
            "analyze",
            "assess",
            "to what extent",
            "how far",
            "how do",
            "how does",
            "how can",
            "explain",
            "why",
            "compare",
            "contrast",
            "examine",
            "elaborate",
            "comment",
            "what are",
        ]

        is_essay = any(trigger in lower for trigger in essay_triggers) or "?" in stripped or word_count >= 18
        mode = "essay" if is_essay else "brief"

        directives: List[str] = []
        directive_map = {
            "discuss": "discuss the major dimensions of the topic",
            "evaluate": "evaluate strengths and weaknesses",
            "critically": "deliver a critical appraisal",
            "assess": "assess the significance",
            "analyse": "analyse underlying structures",
            "analyze": "analyse underlying structures",
            "explain": "explain core mechanisms",
            "why": "justify the causes",
            "how do": "describe the operational process",
            "how does": "describe the operational process",
            "how can": "illustrate practical application",
            "compare": "compare contrasting perspectives",
            "contrast": "contrast the specified perspectives",
            "what extent": "judge the extent or limits",
            "what are": "identify and describe the requested items",
        }
        for key, directive in directive_map.items():
            if key in lower and directive not in directives:
                directives.append(directive)

        reasoning_focus: List[str] = []
        if any(term in lower for term in ["why", "cause", "impact", "effect", "protect", "consequence"]):
            reasoning_focus.append("cause-effect reasoning")
        if any(term in lower for term in ["compare", "contrast", "versus", "vs", "similarities", "differences"]):
            reasoning_focus.append("comparative reasoning")
        if any(term in lower for term in ["should", "ought", "recommend", "future", "policy"]):
            reasoning_focus.append("normative judgement")
        if "critically" in lower or "evaluate" in lower or "assessment" in lower:
            reasoning_focus.append("evaluative judgement")
        if not reasoning_focus:
            reasoning_focus.append("analytical exposition")

        principles: List[str] = []
        if "principles of constitutional democracy" in lower:
            principles = [
                "rule of law",
                "separation of powers",
                "constitutional supremacy",
                "fundamental rights",
                "federalism or devolution",
                "independent judiciary",
            ]

        comparison_pairs: List[Dict[str, str]] = []
        if any(term in lower for term in ["compare", "contrast", "versus", "vs"]):
            match = re.search(r"between\s+(.+?)\s+and\s+(.+)", lower)
            if match:
                item_a = match.group(1).strip(" ?.")
                item_b = match.group(2).strip(" ?.")
                comparison_pairs.append({"item_a": item_a.upper(), "item_b": item_b.upper()})

        multi_parts: List[str] = []
        if " and how " in lower and "principle" in lower and "protect" in lower:
            multi_parts = [
                "Enumerate and explain the fundamental principles of constitutional democracy.",
                "Demonstrate how each principle safeguards minority rights in theory and practice.",
            ]

        if not multi_parts and "and" in lower and "?" in stripped:
            segments = [seg.strip(" ?.") for seg in stripped.split(" and ") if seg.strip()]
            if len(segments) > 1:
                multi_parts = segments[:3]

        expected_length = "essay" if mode == "essay" else "short"
        suggested_subheadings_min = 10 if mode == "essay" else 0
        suggested_subheadings_max = 14 if mode == "essay" else 0

        key_terms = []
        if "constitutional democracy" in lower:
            key_terms.append("constitutional democracy")
        if "minority" in lower:
            key_terms.append("minority rights")
        if "federalism" in lower:
            key_terms.append("federalism")

        if not directives:
            directives.append("explain the topic comprehensively with relevant context")

        analysis = {
            "mode": mode,
            "directives": directives,
            "reasoning_focus": reasoning_focus,
            "principles": principles,
            "comparison_pairs": comparison_pairs,
            "multi_part_breakdown": multi_parts,
            "expected_length": expected_length,
            "suggested_subheadings_min": suggested_subheadings_min,
            "suggested_subheadings_max": suggested_subheadings_max,
            "key_terms": key_terms,
            "raw_question": question,
        }

        if mode != "essay":
            analysis["expected_length"] = "short"
            analysis["suggested_subheadings_min"] = 0
            analysis["suggested_subheadings_max"] = 0

        return analysis

    async def _update_memory(
        self,
        user_id: str,
        session_id: str,
        question: str,
        answer: str,
        conversation_id: Optional[str],
    ) -> Dict[str, Optional[str]]:
        update: Dict[str, Optional[str]] = {}
        suggested_title: Optional[str] = None
        try:
            if conversation_id:
                update["conversation_id"] = conversation_id

            needs_title = False
            existing_title: Optional[str] = None

            if conversation_id and self.db_service:
                self.db_service.add_message_pair(conversation_id, question, answer)

                conversation = self.db_service.get_conversation_by_id(conversation_id)
                if conversation:
                    existing_title = (conversation.get("title") or "").strip()
                    if not existing_title or existing_title.lower() in {"new chat", "untitled", "chat"}:
                        needs_title = True
                    else:
                        update["conversation_title"] = existing_title
                else:
                    needs_title = True
            else:
                needs_title = True

            if needs_title:
                try:
                    suggested_title = await self._generate_conversation_title(question, answer)
                except Exception as exc:
                    logger.debug(f"[CHATBOT] Title suggestion failed: {exc}")
                    suggested_title = None

            if conversation_id and self.db_service and suggested_title:
                try:
                    self.db_service.update_conversation(conversation_id, {"title": suggested_title})
                    update["conversation_title"] = suggested_title
                except Exception as exc:
                    logger.debug(f"[CHATBOT] Title update skipped: {exc}")
                    if existing_title:
                        update.setdefault("conversation_title", existing_title)

            self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
            self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": answer})

            if self.short_term.should_summarize(user_id, session_id):
                messages = self.short_term.get_recent_messages(user_id, session_id)
                await self.long_term.save_conversation_summary(user_id, session_id, messages)
                self.short_term.reset_conversation_count(user_id, session_id)
                await self.long_term.cleanup_old_facts(user_id, session_id)
            else:
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
        except Exception as exc:
            logger.warning(f"[CHATBOT] Memory update failed: {exc}")
        if suggested_title:
            update.setdefault("suggested_title", suggested_title)
        return update
