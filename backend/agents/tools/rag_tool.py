"""
RAG Tool for CSS Exam Content Retrieval and Answering
Encapsulates the existing RAG pipeline as a tool for the chatbot agent.
"""
import asyncio
import time
from typing import Dict, Any, List, Optional, Tuple
import logging

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
from backend.rag.telemetry.langsmith_tracer import trace_agent_method
from backend.rag.telemetry.performance_monitor import get_performance_monitor

logger = logging.getLogger(__name__)

class RAGTool:
    """
    RAG Tool for retrieving and answering CSS exam content questions.
    Encapsulates the multi-mode RAG pipeline as a callable tool.
    """
    
    def __init__(self):
        self.db = SupabaseDB()
        self.embedding = FastEmbedEmbedding()
        self.llm_model = CHATBOT_LLM_MODEL
        self.groq_api_key = GROQ_API_KEY
        self.performance_monitor = get_performance_monitor()
        self.logger = logging.getLogger(__name__)
    
    @trace_agent_method(name="rag_tool_execute", tags=["rag", "tool", "css_content"])
    async def execute(
        self,
        question: str,
        genre: str,
        context: List[Dict] = None,
        book_ids: Optional[List[str]] = None,
        mode: str = "adaptive"
    ) -> Dict[str, Any]:
        """
        Execute RAG retrieval and answering for CSS exam content.
        
        Args:
            question: The CSS exam question to answer
            genre: Book genre to search within
            context: Conversation context for better answering
            book_ids: Specific book IDs to search (optional)
            mode: RAG mode ("fast", "multi_step", "adaptive")
            
        Returns:
            Dict with answer, sources, citations, and metadata
        """
        start_time = time.time()
        self.logger.info(f"RAG Tool executing: mode={mode}, genre={genre}")
        
        try:
            if mode == "adaptive":
                return await self._execute_adaptive(question, genre, context, book_ids)
            elif mode == "multi_step":
                return await self._execute_multi_step(question, genre, context, book_ids)
            else:  # fast mode
                return await self._execute_fast(question, genre, context, book_ids)
                
        except Exception as e:
            self.logger.error(f"RAG Tool execution failed: {e}")
            return {
                "answer": "I apologize, but I encountered an error while retrieving information. Please try rephrasing your question.",
                "sources": [],
                "citations": [],
                "context": context or [],  # Ensure context is always included
                "metadata": {
                    "error": str(e),
                    "mode": mode,
                    "execution_time": time.time() - start_time
                }
            }
    
    async def _execute_adaptive(
        self, 
        question: str, 
        genre: str, 
        context: List[Dict] = None, 
        book_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Adaptive mode: try multi-step with timeout, fallback to fast."""
        try:
            # Try multi-step with shorter timeout for speed
            task = asyncio.create_task(
                self._execute_multi_step(question, genre, context, book_ids, max_iterations=1)
            )
            result = await asyncio.wait_for(task, timeout=200.0)
            result["metadata"]["mode"] = "adaptive_multi"
            return result
            
        except asyncio.TimeoutError:
            self.logger.warning("Multi-step RAG timed out, falling back to fast mode")
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            
            # Fallback to fast mode
            result = await self._execute_fast(question, genre, context, book_ids)
            result["metadata"]["mode"] = "adaptive_fast_fallback"
            return result
            
        except Exception as e:
            self.logger.error(f"Multi-step RAG failed, falling back to fast mode: {e}")
            result = await self._execute_fast(question, genre, context, book_ids)
            result["metadata"]["mode"] = "adaptive_fast_fallback"
            return result
    
    async def _execute_fast(
        self,
        question: str,
        genre: str,
        context: List[Dict] = None,
        book_ids: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Fast single-step RAG for speed."""
        start_time = time.time()
        
        # Generate query embedding
        query_embedding = await self.embedding.generate(question)
        
        # Get book IDs if not provided
        if not book_ids:
            books_res = self.db.select("books", {"genre": genre})
            book_ids = [b["id"] for b in books_res.data] if hasattr(books_res, 'data') else []
            # Limit to top 5 books for faster retrieval
            book_ids = book_ids[:5]
        
        # Retrieve relevant chunks
        chunks = await self.db.search_chunks_vector(query_embedding, book_ids, top_k=5)
        
        # Enrich chunks with book metadata
        if chunks:
            unique_book_ids = list(set(chunk["book_id"] for chunk in chunks))
            books_data = self.db.select("books", {"id": unique_book_ids})
            book_map = {book["id"]: book for book in books_data.data} if hasattr(books_data, 'data') else {}
            
            for chunk in chunks:
                book = book_map.get(chunk["book_id"])
                if book:
                    chunk["book_title"] = book["title"]
                    chunk["book_author"] = book["author"]
        
        # Create context and generate answer
        context_str = create_context_from_chunks(chunks)
        prompt = self._compose_css_prompt(question, context, context_str)
        answer = await self._call_llm_async(prompt, max_tokens=1024)
        
        # Create citations from chunks
        citations = [
            Citation(
                doc_id=chunk.get("book_id", ""),
                chunk_id=chunk.get("id", ""),
                source=f"{chunk.get('book_title', 'Unknown')} by {chunk.get('book_author', 'Unknown')}",
                content=chunk.get("content", "")[:200] + "...",
                score=float(chunk.get("score", 0.0))
            ) for chunk in chunks
        ]
        
        execution_time = time.time() - start_time
        
        return {
            "answer": answer,
            "sources": chunks,
            "citations": [c.__dict__ for c in citations],
            "context": context or [],  # Ensure context is always included
            "metadata": {
                "mode": "fast",
                "retrieved_chunks": len(chunks),
                "book_ids": book_ids,
                "execution_time": execution_time
            }
        }
    
    async def _execute_multi_step(
        self,
        question: str,
        genre: str,
        context: List[Dict] = None,
        book_ids: Optional[List[str]] = None,
        max_iterations: int = 2
    ) -> Dict[str, Any]:
        """Multi-step RAG with planning and synthesis."""
        start_time = time.time()
        
        # Prepare conversation messages
        messages = []
        if context:
            for msg in context:
                role = "assistant" if msg.get("sender") == "assistant" else "user"
                content = str(msg.get("message", "")).strip()
                if content:
                    messages.append({"role": role, "content": content})
        
        # Add current question
        messages.append({"role": "user", "content": question.strip()})
        
        # Resolve book filters
        if not book_ids:
            try:
                books_res = self.db.select("books", {"genre": genre})
                book_ids = [b["id"] for b in getattr(books_res, "data", [])]
            except Exception as e:
                self.logger.warning(f"Failed to fetch books by genre: {e}")
                book_ids = []
        
        selection_filters = {"book_ids": book_ids} if book_ids else None
        
        # Setup retriever and LLM
        adapter = SupabaseVectorStoreAdapter(self.db)
        retriever = HybridRetriever(adapter)
        llm = GroqHTTPxLLM(api_key=self.groq_api_key, model=self.llm_model)
        
        # Run multi-step controller
        result = await run_controller(
            messages=messages,
            selection_filters=selection_filters,
            max_iterations=max_iterations,
            llm_client=llm,
            retriever=retriever,
        )
        
        # Resolve sources from citations
        sources = await self._resolve_sources_from_citations(result.get("citations", []))
        
        execution_time = time.time() - start_time
        
        return {
            "answer": result.get("answer", ""),
            "sources": sources,
            "citations": [c.__dict__ for c in result.get("citations", [])],
            "context": context or [],  # Ensure context is always included
            "traces": [t.__dict__ for t in result.get("traces", [])],
            "metadata": {
                "mode": "multi_step",
                "iterations": result.get("iterations", 0),
                "book_ids": book_ids,
                "execution_time": execution_time
            }
        }
    
    def _compose_css_prompt(self, question: str, context: List[Dict] = None, context_str: str = "") -> str:
        """Compose adaptive CSS exam-style prompt based on question type."""
        # Get system prompt from file
        try:
            import os
            prompt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'prompts', 'chatbot.txt')
            with open(prompt_path, 'r', encoding='utf-8') as f:
                system_prompt = f.read().strip()
        except Exception:
            system_prompt = """You are an expert CSS exam preparation assistant. Adapt your response style to the user's question and ALWAYS format your response in **Markdown**:

- For comprehensive questions (discuss, explain, analyze): Use full CSS exam format with **Introduction**, **Body** (12-20 headings with ##), **Conclusion**
- For brief requests (briefly, summarize, in short): Provide 3-7 key points using bullet points (-)
- For FAQ questions (how to, tips): Use practical format with numbered steps (1., 2., 3.) or bullet points
- For definitions (what is, define): Use **bold** for key terms and bullet points for features

**Important Markdown Guidelines:**
- Use ## for main headings, ### for subheadings
- Use **bold** for important terms and concepts
- Use *italics* for emphasis
- Use bullet points (-) or numbered lists (1., 2., 3.) for lists
- Use > for important quotes or key points
- Use `code blocks` for any technical terms or examples
- Use --- for horizontal lines to separate sections if needed"""
        
        # Build context from conversation with better summarization
        chat_history = ""
        if context:
            chat_history = self._build_contextual_summary(context, question)
        
        # Detect question type for adaptive instruction
        question_lower = question.lower().strip()
        adaptive_instruction = ""
        
        # Enhanced detection for brief requests
        brief_patterns = [
            "briefly", "summarize", "in short", "quick overview", "summary",
            "tell me shortly", "give me a brief", "short answer", "concise",
            "in simple terms", "just tell me", "quick summary"
        ]
        
        # Check for specific line/point requests ("in 5 lines", "give me 3 points")
        import re
        line_pattern = r"(in|within)\s+(\d+)\s+(lines?|points?|sentences?)"
        point_pattern = r"(give me|tell me)\s+(\d+)\s+(points?|lines?|sentences?)"
        
        line_match = re.search(line_pattern, question_lower)
        point_match = re.search(point_pattern, question_lower)
        
        if line_match or point_match or any(pattern in question_lower for pattern in brief_patterns):
            # Extract specific number if mentioned
            num_points = "3-7"
            if line_match:
                num_points = line_match.group(2)
            elif point_match:
                num_points = point_match.group(2)
            
            adaptive_instruction = f"INSTRUCTION: Provide a very brief, focused response with {num_points} key points using **Markdown bullet points** (-). Keep each point to 1-2 sentences maximum. Be concise and direct. Use **bold** for key terms."
        elif any(word in question_lower for word in ["how to", "tips", "advice", "guidance", "steps"]):
            adaptive_instruction = "INSTRUCTION: Provide practical, actionable guidance in **Markdown** format using numbered steps (1., 2., 3.) or bullet points. Use **bold** for important actions."
        elif any(word in question_lower.split()[:3] for word in ["what", "define", "definition"]):
            adaptive_instruction = "INSTRUCTION: Provide a clear definition using **Markdown**. Use **bold** for the main term, bullet points (-) for key characteristics, and mention CSS exam relevance."
        elif any(word in question_lower.split()[:3] for word in ["discuss", "explain", "analyze", "evaluate", "examine", "assess"]):
            adaptive_instruction = "INSTRUCTION: Use the full CSS exam format in **Markdown** with **Introduction** (2-3 sentences), **Body** (12-20 detailed headings using ##), and **Conclusion** (2-3 sentences). Use **bold** for key concepts."
        else:
            adaptive_instruction = "INSTRUCTION: Analyze the question type and respond appropriately in **Markdown** format - comprehensive format with ## headings for detailed topics, brief format with bullet points for quick requests. Always use **bold** for important terms."
        
        return f"""{system_prompt}

Recent Context:
{chat_history}

Relevant Book Content:
{context_str}

Question: {question}

{adaptive_instruction}

Answer:"""
    
    async def _call_llm_async(self, prompt: str, max_tokens: int = 2048) -> str:
        """Async LLM call for answer generation."""
        if not self.groq_api_key or not self.llm_model:
            return "[Error: GROQ API key or model not configured]"
        
        import httpx
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.llm_model,
            "messages": [
                {"role": "system", "content": "You are an expert CSS exam preparation assistant. Always provide structured, comprehensive answers in **Markdown format** suitable for civil service examination preparation. Use proper headings (##), bullet points (-), **bold** text for key terms, and *italics* for emphasis."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.4
        }
        
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"]
        except Exception as e:
            return f"[GROQ API error: {e}]"
    
    async def _resolve_sources_from_citations(self, citations: List[Citation]) -> List[Dict[str, Any]]:
        """Resolve source chunks from citations."""
        if not citations:
            return []
        
        chunk_ids = list({c.chunk_id for c in citations if hasattr(c, "chunk_id") and c.chunk_id})
        if not chunk_ids:
            return []
        
        try:
            rows = (
                self.db.supabase.table("document_chunks")
                .select("id,book_id,content,page_start,page_end,chunk_index,metadata,created_at")
                .in_("id", chunk_ids)
                .execute()
                .data
            ) or []
        except Exception as e:
            self.logger.warning(f"Failed to fetch sources by chunk_ids: {e}")
            rows = []
        
        # Enrich with book metadata
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
    
    def _build_contextual_summary(self, context: List[Dict], current_question: str) -> str:
        """Build an intelligent contextual summary from conversation history."""
        if not context or len(context) == 0:
            return ""
        
        # Extract key topics and recent interactions
        topics_discussed = []
        recent_qa_pairs = []
        
        # Process conversation to extract meaningful context
        i = 0
        while i < len(context) - 1:  # -1 because we process pairs
            current_msg = context[i]
            next_msg = context[i + 1] if i + 1 < len(context) else None
            
            if (current_msg.get("sender") == "user" and 
                next_msg and next_msg.get("sender") == "assistant"):
                
                user_question = current_msg.get("message", "").strip()
                assistant_answer = next_msg.get("message", "").strip()
                
                # Extract key topics from questions
                question_lower = user_question.lower()
                css_topics = [
                    "constitution", "federalism", "governance", "civil service", "public administration",
                    "political science", "economics", "pakistan studies", "international relations",
                    "css exam", "essay writing", "current affairs", "history", "sociology"
                ]
                
                mentioned_topics = [topic for topic in css_topics if topic in question_lower]
                topics_discussed.extend(mentioned_topics)
                
                # Keep recent Q&A pairs (summarized)
                if len(recent_qa_pairs) < 3:  # Keep last 3 interactions
                    qa_summary = f"Q: {user_question[:100]}{'...' if len(user_question) > 100 else ''}"
                    # Add key points from assistant answer
                    answer_lines = assistant_answer.split('\n')[:3]  # First 3 lines
                    key_answer = ' '.join([line.strip() for line in answer_lines if line.strip()])[:150]
                    qa_summary += f"\nA: {key_answer}{'...' if len(key_answer) >= 150 else ''}"
                    recent_qa_pairs.append(qa_summary)
                
                i += 2  # Skip the assistant response we just processed
            else:
                i += 1
        
        # Build contextual summary
        summary_parts = []
        
        # Add topics discussed
        if topics_discussed:
            unique_topics = list(set(topics_discussed))
            if len(unique_topics) <= 3:
                summary_parts.append(f"Previous topics: {', '.join(unique_topics)}")
            else:
                summary_parts.append(f"Previous topics: {', '.join(unique_topics[:3])} and {len(unique_topics)-3} others")
        
        # Add recent interactions (most relevant)
        if recent_qa_pairs:
            summary_parts.append("Recent conversation:")
            # Only show the most recent interaction to save tokens
            summary_parts.append(recent_qa_pairs[-1])
        
        return "\n".join(summary_parts) if summary_parts else ""
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get tool capabilities description."""
        return {
            "name": "rag_tool",
            "description": "Retrieves and answers CSS exam content questions using book knowledge",
            "capabilities": [
                "CSS exam content retrieval",
                "Academic question answering",
                "Book-based evidence synthesis",
                "Citation generation",
                "Multi-mode RAG (fast, multi-step, adaptive)",
                "Context-aware responses with conversation memory"
            ],
            "input_requirements": {
                "required": ["question", "genre"],
                "optional": ["context", "book_ids", "mode"]
            },
            "output_format": {
                "answer": "CSS exam-style structured answer",
                "sources": "Retrieved book chunks",
                "citations": "Source citations",
                "metadata": "Execution details"
            }
        }


# Global RAG tool instance
_rag_tool = None

def get_rag_tool() -> RAGTool:
    """Get the global RAG tool instance."""
    global _rag_tool
    if _rag_tool is None:
        _rag_tool = RAGTool()
    return _rag_tool
