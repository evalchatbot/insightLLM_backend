"""
Conversation summarization service for long-term memory optimization.
Summarizes conversations when they exceed the context threshold.
"""
import asyncio
from typing import List, Dict, Any, Optional
from datetime import datetime
import logging
from backend.config import GROQ_API_KEY, CHATBOT_LLM_MODEL
from backend.rag.telemetry.langsmith_tracer import trace_agent_method
import httpx

logger = logging.getLogger(__name__)

SUMMARIZATION_PROMPT = """You are a conversation summarizer. Your task is to create a concise summary of the conversation below.

REQUIREMENTS:
- Capture the main topics discussed
- Include key questions asked by the user
- Summarize the assistant's main points and recommendations
- Preserve important context for future conversations
- Keep the summary under 300 words
- Focus on actionable insights and user preferences

CONVERSATION:
{conversation_text}

SUMMARY:"""

class ConversationSummarizer:
    """
    Service for summarizing conversations when they exceed context limits.
    Uses LLM to create intelligent summaries for long-term storage.
    """
    
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or GROQ_API_KEY
        self.model = model or CHATBOT_LLM_MODEL
        self.context_threshold = 5  # Summarize after 5 conversation turns
        self.logger = logging.getLogger(__name__)
    
    def should_summarize(self, conversation_count: int) -> bool:
        """Check if conversation should be summarized based on count."""
        return conversation_count >= self.context_threshold
    
    def format_conversation(self, messages: List[Dict[str, Any]]) -> str:
        """Format conversation messages into a readable text."""
        conversation_lines = []
        for msg in messages:
            sender = msg.get("sender", "unknown")
            content = msg.get("message", "")
            timestamp = msg.get("timestamp", "")
            
            if sender == "user":
                conversation_lines.append(f"User: {content}")
            elif sender == "assistant":
                conversation_lines.append(f"Assistant: {content}")
            else:
                conversation_lines.append(f"{sender}: {content}")
        
        return "\n".join(conversation_lines)
    
    @trace_agent_method(name="conversation_summarization", tags=["memory", "summarization"])
    async def summarize_conversation(self, messages: List[Dict[str, Any]]) -> str:
        """
        Summarize a conversation using LLM.
        
        Args:
            messages: List of conversation messages with 'sender' and 'message' fields
            
        Returns:
            Summary string
        """
        if not messages:
            return "No conversation to summarize."
        
        if len(messages) < self.context_threshold:
            # Don't summarize short conversations
            return self.format_conversation(messages)
        
        conversation_text = self.format_conversation(messages)
        prompt = SUMMARIZATION_PROMPT.format(conversation_text=conversation_text)
        
        try:
            summary = await self._call_llm_async(prompt)
            
            # Add metadata to summary
            metadata = {
                "original_messages": len(messages),
                "summarized_at": datetime.utcnow().isoformat(),
                "summary_length": len(summary)
            }
            
            summary_with_metadata = f"{summary}\n\n[Metadata: {metadata}]"
            self.logger.info(f"Summarized {len(messages)} messages into {len(summary)} characters")
            return summary_with_metadata
            
        except Exception as e:
            self.logger.error(f"Failed to summarize conversation: {e}")
            # Fallback: return truncated conversation
            return f"[Summary failed] Last messages: {conversation_text[-500:]}"
    
    async def _call_llm_async(self, prompt: str) -> str:
        """Async LLM call for summarization."""
        if not self.api_key or not self.model:
            raise ValueError("API key and model required for summarization")
        
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a conversation summarizer. Be concise and capture key insights."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 400,  # Limit summary length
            "temperature": 0.3  # Lower temperature for more consistent summaries
        }
        
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
            return data["choices"][0]["message"]["content"].strip()
    
    def extract_key_topics(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Extract key topics from conversation for indexing."""
        topics = []
        for msg in messages:
            content = msg.get("message", "").lower()
            # Simple keyword extraction (could be enhanced with NLP)
            if "book" in content or "author" in content:
                topics.append("books")
            if "recommend" in content:
                topics.append("recommendations")
            if "question" in content or "quiz" in content:
                topics.append("quiz")
            if "genre" in content:
                topics.append("genre")
        
        return list(set(topics))  # Remove duplicates
    
    async def create_contextual_summary(
        self, 
        messages: List[Dict[str, Any]], 
        user_preferences: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Create a rich summary with context and metadata.
        
        Returns:
            Dictionary with summary, topics, preferences, and metadata
        """
        summary_text = await self.summarize_conversation(messages)
        topics = self.extract_key_topics(messages)
        
        return {
            "summary": summary_text,
            "topics": topics,
            "message_count": len(messages),
            "user_preferences": user_preferences or {},
            "created_at": datetime.utcnow().isoformat(),
            "summary_type": "conversation"
        }


# Global summarizer instance
_conversation_summarizer = None

def get_conversation_summarizer() -> ConversationSummarizer:
    """Get the global conversation summarizer instance."""
    global _conversation_summarizer
    if _conversation_summarizer is None:
        _conversation_summarizer = ConversationSummarizer()
    return _conversation_summarizer
