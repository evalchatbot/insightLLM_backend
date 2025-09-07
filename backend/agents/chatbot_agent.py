"""
Chatbot Agent module.
Handles RAG pipeline, vector search, and memory management (short-term and long-term).
"""
from typing import Dict, Any, List, Optional
from backend.memory.short_term import ShortTermMemory
from backend.memory.long_term import LongTermMemory
from backend.db.supabase_client import SupabaseDB
from backend.config import GROQ_API_KEY, CHATBOT_LLM_MODEL
from backend.rag.embedding import FastEmbedEmbedding
from backend.rag.context import create_context_from_chunks
from backend.rag.llm.groq_httpx import GroqHTTPxLLM
from backend.rag.reasoning.graph_controller import run_controller
from backend.rag.adapters.supabase_store import SupabaseVectorStoreAdapter
from backend.rag.retrieval.hybrid_retriever import HybridRetriever
from backend.rag.models.schemas import Citation
from backend.rag.telemetry.langsmith_tracer import trace_agent_method, trace_llm_call, LangSmithTracer
from backend.rag.telemetry.performance_monitor import get_performance_monitor
from backend.rag.classification.question_classifier import get_question_classifier, QuestionType
from backend.rag.classification.generic_responses import get_generic_response_handler

import httpx
import logging
import os
import time

class ChatbotAgent:
    """
    Chatbot agent with RAG pipeline, vector search, and memory integration.
    """
    def __init__(self):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self.db = SupabaseDB()
        self.llm_model = CHATBOT_LLM_MODEL
        self.groq_api_key = GROQ_API_KEY
        self.embedding = FastEmbedEmbedding()
        self.logger = logging.getLogger(__name__)
        self.performance_monitor = get_performance_monitor()
        self.question_classifier = get_question_classifier()
        self.generic_handler = get_generic_response_handler()
        
    async def ask_fast(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Fast single-step RAG for when multi-step is too slow.
        Uses cached embeddings and reduced retrieval for speed.
        """
        self.logger.info(f"Fast mode: user_id={user_id}, session_id={session_id}, genre={genre}")
        start_time = time.time()
        
        try:
            # Use cached embedding generation
            query_embedding = await self.embedding.generate(question)
            
            # Reduce book scope if not provided
            if not book_ids:
                books_res = self.db.select("books", {"genre": genre})
                all_book_ids = [b["id"] for b in books_res.data] if hasattr(books_res, 'data') else []
                # Limit to top 5 books for faster retrieval
                book_ids = all_book_ids[:5]
            
            # Reduced top_k for faster retrieval
            chunks = await self.db.search_chunks_vector(query_embedding, book_ids, top_k=3)
            
            if chunks:
                unique_book_ids = list(set(chunk["book_id"] for chunk in chunks))
                books_data = self.db.select("books", {"id": unique_book_ids})
                book_map = {book["id"]: book for book in books_data.data} if hasattr(books_data, 'data') else {}
                for chunk in chunks:
                    book = book_map.get(chunk["book_id"])
                    if book:
                        chunk["book_title"] = book["title"]
                        chunk["book_author"] = book["author"]
            
            context_str = create_context_from_chunks(chunks)
            context = self.short_term.get_recent_messages(user_id, session_id)[-5:]  # Limit context to last 5
            
            # Shorter prompt for faster processing but maintain CSS format
            prompt = f"""Context: {context_str[:1000]}...

Question: {question}

IMPORTANT: Provide a CSS exam-style answer with:
1. Brief Introduction (1-2 sentences)
2. Body (6-10 key headings with explanations)
3. Brief Conclusion (1-2 sentences)

Answer:"""
            answer = self._call_llm_groq_fast(prompt)
            
            # Memory updates with smart summarization
            self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
            self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": answer})
            
            # Check if we should summarize the conversation
            if self.short_term.should_summarize(user_id, session_id):
                current_messages = self.short_term.get_recent_messages(user_id, session_id)
                await self.long_term.save_conversation_summary(user_id, session_id, current_messages)
                # Reset the conversation count after summarization
                self.short_term.reset_conversation_count(user_id, session_id)
                # Clean up old individual facts
                await self.long_term.cleanup_old_facts(user_id, session_id)
            else:
                # For short conversations, save individual fact
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
            
            total_time = time.time() - start_time
            return {
                "answer": answer,
                "sources": chunks,
                "context": context,
                "metadata": {
                    "retrieved_chunks": len(chunks),
                    "mode": "fast",
                    "total_time": round(total_time, 2)
                }
            }
        except Exception as e:
            self.logger.error(f"Error in ChatbotAgent.ask_fast: {e}")
            raise
    
    def _call_llm_groq_fast(self, prompt: str) -> str:
        """Optimized GROQ API call with reduced tokens for faster response."""
        if not self.groq_api_key or not self.llm_model:
            return "[Error: GROQ API key or model not configured]"
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "You are an expert CSS exam preparation assistant. Provide structured answers with Introduction, Body (6-10 headings), and Conclusion format. Be comprehensive but concise."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 1024,  # Increased to accommodate CSS exam format
            "temperature": 0.4   # Balanced for structured responses
        }
        try:
            with httpx.Client(timeout=15) as client:  # Reduced timeout
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[GROQ API error: {e}]"

    @trace_agent_method(name="chatbot_ask", tags=["chatbot", "main_entry"])
    async def ask(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Smart routing: Generic questions get immediate responses, specific questions use RAG pipeline.
        """
        # Step 1: Classify the question
        question_type, confidence = self.question_classifier.classify_question(question)
        self.logger.info(f"Question classified as {question_type.value} with confidence {confidence:.2f}")
        
        # Step 2: Handle generic questions immediately
        if question_type == QuestionType.GENERIC and confidence >= 0.4:
            generic_response = self.generic_handler.get_response(question)
            if generic_response:
                # Still update memory for continuity
                self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
                self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": generic_response})
                
                # Check if we should summarize (even for generic responses)
                if self.short_term.should_summarize(user_id, session_id):
                    current_messages = self.short_term.get_recent_messages(user_id, session_id)
                    await self.long_term.save_conversation_summary(user_id, session_id, current_messages)
                    self.short_term.reset_conversation_count(user_id, session_id)
                    await self.long_term.cleanup_old_facts(user_id, session_id)
                
                return {
                    "answer": generic_response,
                    "sources": [],
                    "context": self.short_term.get_recent_messages(user_id, session_id),
                    "metadata": {
                        "question_type": "generic",
                        "confidence": confidence,
                        "mode": "direct_response",
                        "retrieved_chunks": 0
                    }
                }
        
        # Step 3: For specific content questions, use RAG pipeline
        use_multi = os.getenv("USE_MULTI_STEP_RAG", "true").lower() in ("1", "true", "yes", "on")
        use_adaptive = os.getenv("USE_ADAPTIVE_RAG", "false").lower() in ("1", "true", "yes", "on")

        # Adaptive mode: try multi-step with timeout, fallback to fast mode
        if use_adaptive:
            try:
                # Try multi-step with a shorter timeout
                task = asyncio.create_task(self.ask_multi_step(
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    genre=genre,
                    book_ids=book_ids,
                    max_iterations=1,  # Single iteration for speed
                ))
                res = await asyncio.wait_for(task, timeout=10.0)  # 10 second timeout
                
                # Ensure the legacy route shape is preserved
                if "context" not in res:
                    res["context"] = self.short_term.get_recent_messages(user_id, session_id)
                res["metadata"]["mode"] = "adaptive_multi"
                res["metadata"]["question_type"] = question_type.value
                res["metadata"]["classification_confidence"] = confidence
                return res
                
            except asyncio.TimeoutError:
                self.logger.warning("Multi-step RAG timed out, falling back to fast mode")
                # Cancel the task
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                
                # Fallback to fast mode
                res = await self.ask_fast(user_id, session_id, question, genre, book_ids)
                res["metadata"]["mode"] = "adaptive_fast_fallback"
                res["metadata"]["question_type"] = question_type.value
                res["metadata"]["classification_confidence"] = confidence
                return res
            except Exception as e:
                self.logger.error(f"Multi-step RAG failed, falling back to fast mode: {e}")
                res = await self.ask_fast(user_id, session_id, question, genre, book_ids)
                res["metadata"]["mode"] = "adaptive_fast_fallback"
                res["metadata"]["question_type"] = question_type.value
                res["metadata"]["classification_confidence"] = confidence
                return res

        if use_multi:
            # Start performance monitoring
            metrics = self.performance_monitor.start_session()
            start_time = time.time()
            
            try:
                res = await self.ask_multi_step(
                    user_id=user_id,
                    session_id=session_id,
                    question=question,
                    genre=genre,
                    book_ids=book_ids,
                    max_iterations=2,  # Reduced for faster response
                )
                
                # Update metrics
                metrics.total_time = time.time() - start_time
                if "metadata" in res:
                    metrics.iterations = res["metadata"].get("iterations", 0)
                    metrics.evidence_count = len(res.get("sources", []))
                
                # Log performance metrics
                self.performance_monitor.log_metrics(metrics)
                
                # Add performance info to response
                res["performance"] = metrics.to_dict()
                
                # Add classification metadata
                res["metadata"]["question_type"] = question_type.value
                res["metadata"]["classification_confidence"] = confidence
                
                # Ensure the legacy route shape is preserved (context is expected on response)
                if "context" not in res:
                    res["context"] = self.short_term.get_recent_messages(user_id, session_id)
                return res
            except Exception as e:
                metrics.total_time = time.time() - start_time
                self.performance_monitor.log_metrics(metrics)
                raise

        # ---- Legacy single-shot path (your original code) ----
        self.logger.info(f"Received question from user_id={user_id}, session_id={session_id}, genre={genre}")
        try:
            query_embedding = await self.embedding.generate(question)
            if not book_ids:
                books_res = self.db.select("books", {"genre": genre})
                book_ids = [b["id"] for b in books_res.data] if hasattr(books_res, 'data') else []
            chunks = await self.db.search_chunks_vector(query_embedding, book_ids, top_k=5)
            if chunks:
                unique_book_ids = list(set(chunk["book_id"] for chunk in chunks))
                books_data = self.db.select("books", {"id": unique_book_ids})
                book_map = {book["id"]: book for book in books_data.data} if hasattr(books_data, 'data') else {}
                for chunk in chunks:
                    book = book_map.get(chunk["book_id"])
                    if book:
                        chunk["book_title"] = book["title"]
                        chunk["book_author"] = book["author"]
            context_str = create_context_from_chunks(chunks)
            context = self.short_term.get_recent_messages(user_id, session_id)
            prompt = self._compose_prompt(question, context, context_str, user_id)
            answer = self._call_llm_groq(prompt)
            
            # Memory updates with smart summarization
            self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
            self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": answer})
            
            # Check if we should summarize the conversation
            if self.short_term.should_summarize(user_id, session_id):
                current_messages = self.short_term.get_recent_messages(user_id, session_id)
                await self.long_term.save_conversation_summary(user_id, session_id, current_messages)
                self.short_term.reset_conversation_count(user_id, session_id)
                await self.long_term.cleanup_old_facts(user_id, session_id)
            else:
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
            return {
                "answer": answer,
                "sources": chunks,
                "context": context,
                "metadata": {"retrieved_chunks": len(chunks)}
            }
        except Exception as e:
            self.logger.error(f"Error in ChatbotAgent.ask: {e}")
            raise

    def _compose_prompt(self, question: str, chat_context: List[dict], context_str: str, user_id: str = None) -> str:
        """Compose prompt for LLM using chat history, retrieved chunks, and long-term context."""
        prompt_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '..', 'prompts', 'chatbot.txt')
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                system_prompt = f.read().strip()
        except Exception:
            system_prompt = """You are an expert CSS exam preparation assistant. Structure your answers with:
1. Introduction (2-3 sentences)
2. Body (12-20 headings with detailed explanations)
3. Conclusion (2-3 sentences)
Focus on comprehensive, exam-style responses for civil service preparation."""
        
        # Build chat history from recent messages
        chat_history = "\n".join([m["message"] for m in chat_context])
        
        # Add long-term context if available
        long_term_context = ""
        if user_id:
            try:
                user_context = self.long_term.get_user_context(user_id, max_summaries=3)
                if user_context and "No previous conversation" not in user_context:
                    long_term_context = f"\nPrevious Context:\n{user_context}\n"
            except Exception as e:
                self.logger.warning(f"Failed to retrieve long-term context: {e}")
        
        return f"""{system_prompt}

{long_term_context}

Recent Chat:
{chat_history}

Relevant Book Context:
{context_str}

Question: {question}

IMPORTANT: Structure your answer in the following format:
1. Introduction (2-3 sentences)
2. Body (12-20 headings with detailed explanations under each)
3. Conclusion (2-3 sentences)

Answer:"""

    @trace_llm_call(name="chatbot_groq_call", provider="groq")
    def _call_llm_groq(self, prompt: str) -> str:
        """Call the GROQ API to get an answer from the configured LLM model."""
        if not self.groq_api_key or not self.llm_model:
            return "[Error: GROQ API key or model not configured]"
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "You are an expert CSS exam preparation assistant. Always provide structured, comprehensive answers suitable for civil service examination preparation."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 2048,  # Increased for detailed CSS exam answers
            "temperature": 0.4   # Slightly lower for more structured, consistent responses
        }
        try:
            with httpx.Client(timeout=30) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[GROQ API error: {e}]"

    @trace_agent_method(name="chatbot_multi_step_rag", tags=["chatbot", "multi_step", "rag"])
    async def ask_multi_step(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None,
            max_iterations: int = 3,
    ) -> Dict[str, Any]:
        """
        Multi-step RAG pipeline:
          - builds messages from short-term memory
          - narrows retrieval by book_ids (or resolves from genre)
          - runs plan → retrieve → validate → synthesize
          - stores memories and returns answer + resolved sources
        """
        self.logger.info(f"[multi-step] user_id={user_id} session_id={session_id} genre={genre}")

        # 0) Build chat history → messages[{role, content}]
        history = self.short_term.get_recent_messages(user_id, session_id)  # your structure: {"sender","message"}
        messages: List[Dict[str, str]] = []
        for m in history:
            role = "assistant" if m.get("sender") == "assistant" else "user"
            content = str(m.get("message", "")).strip()
            if content:
                messages.append({"role": role, "content": content})
        # Append the current user question as the last message
        messages.append({"role": "user", "content": question.strip()})

        # 1) Resolve filters: book_ids (or by genre)
        if not book_ids:
            # your DB select wrapper – same logic as your existing ask(...)
            try:
                books_res = self.db.select("books", {"genre": genre})
                book_ids = [b["id"] for b in getattr(books_res, "data", [])]
            except Exception as e:
                self.logger.warning(f"[multi-step] failed to fetch books by genre: {e}")
                book_ids = []
        selection_filters = {"book_ids": book_ids} if (book_ids and len(book_ids) > 0) else None

        # 2) Build retriever that wraps your Supabase DB (reuses your RPC)
        adapter = SupabaseVectorStoreAdapter(self.db)  # expects .search_chunks_vector and .supabase
        retriever = HybridRetriever(adapter)

        # 3) Async LLM client for planner + synthesizer
        llm = GroqHTTPxLLM(api_key=self.groq_api_key, model=self.llm_model)

        self.logger.info(f"[multi-step] genre={genre} book_ids={book_ids} selection_filters={selection_filters}")

        # 4) Run controller
        result = await run_controller(
            messages=messages,
            selection_filters=selection_filters,
            max_iterations=max_iterations,
            llm_client=llm,
            retriever=retriever,  # supply explicitly to avoid lazy import differences
            planner=None,  # controller will instantiate planner with llm
        )


        context_for_response = history  # return the pre-question chat history for UI parity

        answer: str = result.get("answer", "")
        citations: List[Citation] = result.get("citations", [])
        traces = result.get("traces", [])
        iterations = result.get("iterations", 0)

        # 5) Resolve source chunks from citations (by chunk_id) for UI parity with your current return shape
        sources = await self._resolve_sources_from_citations(citations)

        # 6) Memory updates with smart summarization
        self.short_term.add_message(user_id, session_id, {"sender": "user", "message": question})
        self.short_term.add_message(user_id, session_id, {"sender": "assistant", "message": answer})
        
        # Check if we should summarize the conversation
        try:
            if self.short_term.should_summarize(user_id, session_id):
                current_messages = self.short_term.get_recent_messages(user_id, session_id)
                await self.long_term.save_conversation_summary(user_id, session_id, current_messages)
                self.short_term.reset_conversation_count(user_id, session_id)
                await self.long_term.cleanup_old_facts(user_id, session_id)
                self.logger.info(f"[multi-step] Summarized conversation for {user_id}/{session_id}")
            else:
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
        except Exception as e:
            self.logger.warning(f"[multi-step] memory save failed: {e}")

        return {
            "answer": answer,
            "sources": sources,
            "context": context_for_response,
            "traces": [t.dict() for t in traces],
            "metadata": {"iterations": iterations, "book_ids": book_ids},
        }

    async def _resolve_sources_from_citations(self, citations: List[Citation]) -> List[Dict[str, Any]]:
        """
        Given citations (doc_id/book_id + chunk_id), fetch the chunk rows from Supabase
        so your UI gets the same 'sources' structure it expects.
        """
        if not citations:
            return []
        # Collect chunk_ids
        chunk_ids = list({c.chunk_id for c in citations if getattr(c, "chunk_id", None)})
        if not chunk_ids:
            return []

        # Use the underlying supabase client directly to fetch chunks by id
        try:
            rows = (
                       self.db.supabase.table("document_chunks")
                       .select("id,book_id,content,page_start,page_end,chunk_index,metadata,created_at")
                       .in_("id", chunk_ids)
                       .execute()
                       .data
                   ) or []
        except Exception as e:
            self.logger.warning(f"[multi-step] fetch sources by chunk_ids failed: {e}")
            rows = []

        # Optionally enrich with book title/author (like your current ask())
        if rows:
            uniq_book_ids = list({r.get("book_id") for r in rows if r.get("book_id")})
            try:
                books_data = self.db.select("books", {"id": uniq_book_ids})
                book_map = {b["id"]: b for b in getattr(books_data, "data", [])}
                for r in rows:
                    b = book_map.get(r.get("book_id"))
                    if b:
                        r["book_title"] = b.get("title")
                        r["book_author"] = b.get("author")
            except Exception:
                pass

        return rows
    
    def classify_question_debug(self, question: str) -> Dict[str, Any]:
        """
        Debug method to analyze question classification.
        Useful for testing and tuning the classification system.
        """
        return self.question_classifier.get_classification_details(question)