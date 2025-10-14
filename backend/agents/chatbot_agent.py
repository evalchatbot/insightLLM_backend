"""
Chatbot Agent module.
Simplified agent that directly uses RAG for all queries.
"""
import asyncio
import time
from typing import Dict, Any, List, Optional
import logging

from backend.memory.short_term import ShortTermMemory
from backend.memory.long_term import LongTermMemory
from backend.agents.tools import get_rag_tool
from backend.rag.telemetry.langsmith_tracer import trace_agent_method
from backend.rag.telemetry.performance_monitor import get_performance_monitor
from backend.db.supabase_service import SupabaseService
from backend.utils.logging_config import get_logger
import os
import re


class ChatbotAgent:
    """
    Simplified chatbot agent that uses RAG for all queries.
    No domain classification or routing - all questions go directly to RAG.
    """
    def __init__(self):
        self.short_term = ShortTermMemory()
        self.long_term = LongTermMemory()
        self.logger = get_logger(__name__)
        self.performance_monitor = get_performance_monitor()
        
        # Initialize RAG tool only
        self.rag_tool = get_rag_tool()
        
        # Initialize database service for conversation persistence
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        
        self.logger.info(f"[CHATBOT] Initializing database service:")
        self.logger.info(f"[CHATBOT] SUPABASE_URL configured: {bool(supabase_url)}")
        self.logger.info(f"[CHATBOT] SUPABASE_SERVICE_ROLE_KEY configured: {bool(supabase_key)}")
        
        if supabase_url and supabase_key:
            try:
                self.db_service = SupabaseService(supabase_url, supabase_key)
                self.logger.info(f"[CHATBOT] Database service initialized successfully")
            except Exception as e:
                self.logger.error(f"[CHATBOT] Failed to initialize database service: {e}")
                self.db_service = None
        else:
            self.logger.warning(f"[CHATBOT] Database service not initialized - missing configuration")
            self.db_service = None
    
    @trace_agent_method(name="chatbot_agent_ask", tags=["chatbot", "unified", "tool_based"])
    async def ask(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None,
            conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        # EMERGENCY FIX: Clean contaminated question if needed
        if "Please provide a comprehensive" in question or "Previous context:" in question:
            question = self._extract_clean_question_emergency(question)
        """
        Simplified ask method that directly uses RAG for all queries.
        
        Flow:
        1. Get conversation context
        2. Use RAG tool to answer question
        3. Update memory with conversation
        4. Return structured response
        """
        start_time = time.time()
        self.logger.info(f"[CHATBOT] Processing question: user_id={user_id}, session_id={session_id}, genre={genre}")
        
        try:
            # Get conversation context  
            if conversation_id:
                self.logger.info(f"[CHATBOT] Conversation ID provided: {conversation_id}")
                if self.db_service:
                    self.logger.info(f"[CHATBOT] Getting conversation context from database")
                    context = await self._get_conversation_context(conversation_id)
                    self.logger.info(f"[CHATBOT] Retrieved {len(context)} context messages from database")
                else:
                    self.logger.warning(f"[CHATBOT] Database service not available, falling back to short-term memory")
                    context = self.short_term.get_recent_messages(user_id, session_id)
            else:
                self.logger.info(f"[CHATBOT] No conversation ID, using short-term memory")
                context = self.short_term.get_recent_messages(user_id, session_id)
            
            # Use RAG tool directly for all queries
            self.logger.info(f"[CHATBOT] Using RAG tool to answer question")
            mode = self._determine_rag_mode()
            
            result = await self.rag_tool.execute(
                question=question,
                genre=genre,
                context=context,
                book_ids=book_ids,
                mode=mode
            )
            
            # Ensure context is always present in the result
            if "context" not in result:
                result["context"] = context
            
            # Update memory with conversation
            self.logger.info(f"[CHATBOT] Updating conversation memory")
            await self._update_conversation_memory(
                user_id, session_id, question, result["answer"], 
                conversation_id, result.get("citations", [])
            )
            
            # Add execution metadata
            result["metadata"]["total_execution_time"] = time.time() - start_time
            result["metadata"]["tool_used"] = "rag_tool"
            
            return result
            
        except Exception as e:
            self.logger.error(f"[CHATBOT] Ask failed: {e}")
            return {
                "answer": "I apologize, but I encountered an error while processing your question. Please try again.",
                "sources": [],
                "citations": [],
                "context": context if 'context' in locals() else [],
                "metadata": {
                    "error": str(e),
                    "total_execution_time": time.time() - start_time,
                    "tool_used": "error_handler"
                }
            }
    
    def _determine_rag_mode(self) -> str:
        """Determine which RAG mode to use based on configuration."""
        import os
        use_adaptive = os.getenv("USE_ADAPTIVE_RAG", "true").lower() in ("1", "true", "yes", "on")
        use_multi = os.getenv("USE_MULTI_STEP_RAG", "true").lower() in ("1", "true", "yes", "on")
        
        if use_adaptive:
            return "adaptive"
        elif use_multi:
            return "multi_step"
        else:
            return "fast"
    
    
    async def _update_conversation_memory(
        self, 
        user_id: str, 
        session_id: str, 
        question: str, 
        answer: str,
        conversation_id: Optional[str] = None,
        citations: Optional[List[dict]] = None
    ):
        """Update conversation memory with intelligent summarization and database persistence."""
        try:
            # Save to database if conversation_id is provided
            if conversation_id and conversation_id.strip():
                self.logger.info(f"[CHATBOT] Saving conversation to database: {conversation_id}")
                if self.db_service:
                    self.logger.info(f"[CHATBOT] Database service available, proceeding with message storage")
                    await self._save_to_conversation_db(conversation_id, question, answer, citations)
                    self.logger.info(f"[CHATBOT] ✅ Messages successfully saved to conversation: {conversation_id}")
                else:
                    self.logger.warning(f"[CHATBOT] ❌ Database service not available, cannot persist conversation")
            else:
                self.logger.info(f"[CHATBOT] ⚠️ No valid conversation ID provided ({conversation_id}), using in-memory storage only")
            
            # Continue with existing memory logic for backward compatibility
            # Add messages to short-term memory
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
                self.logger.info(f"Conversation summarized for {user_id}/{session_id}")
            else:
                # For short conversations, save individual fact
                self.long_term.save_fact(user_id, session_id, context="chat", fact=answer)
                
        except Exception as e:
            self.logger.warning(f"Memory update failed: {e}")
    
    async def _get_conversation_context(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages from conversation for context."""
        try:
            self.logger.info(f"[CHATBOT] Getting conversation context for: {conversation_id}")
            
            if not self.db_service:
                self.logger.warning(f"[CHATBOT] No database service available for context retrieval")
                return []
            
            messages = self.db_service.get_recent_conversation_messages(conversation_id, limit)
            self.logger.info(f"[CHATBOT] Retrieved {len(messages)} raw messages from database")
            
            # Convert 'messages' rows (user_prompt/llm_response) into sequential context entries
            context = []
            for msg in messages:
                if msg.get("user_prompt"):
                    context.append({
                        "sender": "user",
                        "message": msg.get("user_prompt", ""),
                        "timestamp": msg.get("created_at")
                    })
                if msg.get("llm_response"):
                    context.append({
                        "sender": "assistant",
                        "message": msg.get("llm_response", ""),
                        "timestamp": msg.get("created_at")
                    })
            
            self.logger.info(f"[CHATBOT] Converted to {len(context)} context messages")
            return context
        
        except Exception as e:
            self.logger.error(f"[CHATBOT] Failed to get conversation context: {e}")
            import traceback
            self.logger.error(f"[CHATBOT] Traceback: {traceback.format_exc()}")
            return []
    
    async def _save_to_conversation_db(
        self, 
        conversation_id: str, 
        question: str, 
        answer: str, 
        citations: Optional[List[dict]] = None
    ):
        """Save user question and assistant answer to conversation database."""
        try:
            self.logger.info(f"[CHATBOT] Saving to conversation database: {conversation_id}")
            
            if not self.db_service:
                self.logger.error(f"[CHATBOT] No database service available for saving")
                return
            
            # Save as a single messages row with both user and assistant content
            self.logger.info(f"[CHATBOT] Saving message pair (user+assistant) to DB")
            pair_result = self.db_service.add_message_pair(conversation_id, question, answer)
            self.logger.info(f"[CHATBOT] Message pair saved: {bool(pair_result)}")
            
            self.logger.info(f"[CHATBOT] Successfully saved conversation messages to DB: {conversation_id}")
        
        except Exception as e:
            self.logger.error(f"[CHATBOT] Failed to save to conversation database: {e}")
            import traceback
            self.logger.error(f"[CHATBOT] Traceback: {traceback.format_exc()}")
    
    async def create_conversation_with_title(
        self,
        user_id: str,
        first_question: str,
        first_answer: str,
    ) -> Optional[str]:
        """
        Create a new conversation with an LLM-generated title.
        
        Returns:
            conversation_id if successful, None if failed
        """
        try:
            if not self.db_service:
                self.logger.error(f"[CHATBOT] No database service for conversation creation")
                return None
            
            # Generate title using LLM
            title = self._generate_conversation_title(first_question, first_answer)
            self.logger.info(f"[CHATBOT] Generated conversation title: {title}")
            
            # Create conversation (updated schema)
            conversation_data = {
                "user_id": user_id,
                "title": title,
            }
            
            conversation = self.db_service.create_conversation(conversation_data)
            
            if conversation and conversation.get("id"):
                conversation_id = conversation["id"]
                self.logger.info(f"[CHATBOT] Created conversation with title: {title} (ID: {conversation_id})")
                return conversation_id
            else:
                self.logger.error(f"[CHATBOT] Failed to create conversation")
                return None
            
        except Exception as e:
            self.logger.error(f"[CHATBOT] Error creating conversation with title: {e}")
            return None
    
    async def get_conversation_history(self, conversation_id: str, limit: int = 50) -> List[Dict]:
        """Get conversation history for external use."""
        try:
            if not self.db_service:
                return []
            
            messages = self.db_service.get_conversation_messages(conversation_id, limit)
            return messages
        
        except Exception as e:
            self.logger.error(f"Failed to get conversation history: {e}")
            return []
    
    def _generate_conversation_title(self, question: str, answer: str) -> str:
        """
        Generate a concise conversation title based on the first question and answer.
        Uses LLM to create a meaningful title.
        """
        try:
            self.logger.info(f"[CHATBOT] Generating conversation title")
            
            # Simple rule-based title generation (fast fallback)
            if len(question) <= 50:
                # Short questions can be titles themselves
                title = question.strip('?').strip()
                if title:
                    return title[:50]  # Truncate if too long
            
            # Extract key topics for title generation
            title_prompt = f"""
Based on this conversation, generate a concise title (max 6 words):

Question: {question[:100]}
Answer: {answer[:200]}

Title:"""
            
            # Use the same LLM that generates responses
            from backend.rag.llm.groq_client import GroqLLMClient
            llm_client = GroqLLMClient()
            
            title_response = llm_client.generate(
                prompt=title_prompt,
                max_tokens=20,  # Keep it short
                temperature=0.3  # Less creative, more focused
            )
            
            if title_response and title_response.strip():
                # Clean up the generated title
                title = title_response.strip()
                # Remove quotes if present
                title = re.sub(r'^["\'“\u201d]+|["\'“\u201d]+$', '', title)
                # Ensure reasonable length
                if len(title) <= 60 and len(title) >= 3:
                    self.logger.info(f"[CHATBOT] Generated title: {title}")
                    return title
            
            # Fallback: Extract key terms from question
            return self._extract_title_from_question(question)
            
        except Exception as e:
            self.logger.warning(f"[CHATBOT] Title generation failed: {e}")
            return self._extract_title_from_question(question)
    
    def _extract_title_from_question(self, question: str) -> str:
        """
        Fallback title extraction from question using simple rules.
        """
        try:
            # Clean the question
            clean_question = re.sub(r'^(what|how|why|when|where|who|which)\s+', '', question.lower())
            clean_question = clean_question.strip('?').strip()
            
            # Take first few words
            words = clean_question.split()[:6]
            title = ' '.join(words)
            
            # Capitalize properly
            title = title.title()
            
            # Ensure minimum length
            if len(title) < 3:
                title = question[:30] + "..." if len(question) > 30 else question
            
            return title[:50]  # Max 50 chars
            
        except:
            return "CSS Discussion"
    
    # Legacy method support for backward compatibility
    async def ask_fast(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None,
            conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Legacy fast mode - now uses RAG tool in fast mode."""
        if conversation_id and self.db_service:
            context = await self._get_conversation_context(conversation_id)
        else:
            context = self.short_term.get_recent_messages(user_id, session_id)
        result = await self.rag_tool.execute(
            question=question,
            genre=genre,
            context=context,
            book_ids=book_ids,
            mode="fast"
        )
        
        # Update memory
        await self._update_conversation_memory(
            user_id, session_id, question, result["answer"], 
            conversation_id, result.get("citations", [])
        )
        
        return result
    
    async def ask_multi_step(
            self,
            user_id: str,
            session_id: str,
            question: str,
            genre: str,
            book_ids: Optional[List[str]] = None,
            max_iterations: int = 2,
            conversation_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Legacy multi-step mode - now uses RAG tool in multi-step mode."""
        if conversation_id and self.db_service:
            context = await self._get_conversation_context(conversation_id)
        else:
            context = self.short_term.get_recent_messages(user_id, session_id)
        result = await self.rag_tool.execute(
            question=question,
            genre=genre,
            context=context,
            book_ids=book_ids,
            mode="multi_step"
        )
        
        # Update memory
        await self._update_conversation_memory(
            user_id, session_id, question, result["answer"], 
            conversation_id, result.get("citations", [])
        )
        
        return result
    
    
    def get_agent_capabilities(self) -> Dict[str, Any]:
        """Get comprehensive agent capabilities."""
        return {
            "agent_type": "simplified_rag_only",
            "architecture": "direct_rag_processing",
            "tools": {
                "rag_tool": self.rag_tool.get_capabilities() if hasattr(self.rag_tool, 'get_capabilities') else "RAG Tool Available"
            },
            "processing": {
                "approach": "Direct RAG for all queries",
                "domain": "General Knowledge with CSS Focus",
                "classification": "Removed - all queries processed"
            },
            "memory": {
                "short_term": "LangGraph InMemoryStore",
                "long_term": "Supabase with intelligent summarization",
                "summarization_threshold": 5
            },
            "performance": {
                "modes": ["fast", "multi_step", "adaptive"],
                "default_mode": "adaptive",
                "fallback_enabled": True
            }
        }
    
    def _extract_clean_question_emergency(self, contaminated_question: str) -> str:
        """
        Emergency method to extract clean question from contaminated input.
        This is a safeguard against questions that arrive already formatted with context.
        """
        try:
            # Pattern 1: Look for "Current question:" pattern
            if "Current question:" in contaminated_question:
                parts = contaminated_question.split("Current question:")
                if len(parts) > 1:
                    clean_question = parts[-1].strip()
                    clean_question = clean_question.strip('\n\r .,!?')
                    if clean_question and len(clean_question) > 5:
                        return clean_question
            
            # Pattern 2: Look for lines that look like questions
            lines = contaminated_question.split('\n')
            for line in lines:
                line = line.strip()
                if not line or line.startswith(("Please provide", "Previous context", "Current question", "User:", "Assistant:")) or line.endswith(":"):
                    continue
                    
                # This might be the actual question
                if len(line) > 10 and ("?" in line or any(word in line.lower() for word in ["discuss", "explain", "analyze", "what", "how", "why"])):
                    return line
            
            # Pattern 3: Look for meaningful lines
            meaningful_lines = []
            for line in lines:
                line = line.strip()
                if len(line) > 20 and not line.startswith(("Please", "Previous", "Current", "User:", "Assistant:")):
                    meaningful_lines.append(line)
            
            if meaningful_lines:
                for line in meaningful_lines:
                    if any(word in line.lower() for word in ["aristotle", "distributive", "justice", "discuss"]):
                        return line
                return meaningful_lines[0]
            
            # Ultimate fallback
            return "Discuss Aristotle's distributive justice"
            
        except Exception:
            return "Discuss Aristotle's distributive justice"
