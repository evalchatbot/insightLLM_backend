"""
Usage tracking utility for recording token usage in Supabase.
"""
from typing import Optional, Dict, Any
from supabase import create_client
from backend.config import SUPABASE_URL, SUPABASE_KEY
from loguru import logger
import tiktoken


def get_token_count(text: str, model: str = "gpt-4") -> int:
    """
    Calculate token count for a given text using tiktoken.
    
    Args:
        text: Text to count tokens for
        model: Model name to use for encoding (default: gpt-4)
        
    Returns:
        int: Number of tokens
    """
    try:
        encoding = tiktoken.encoding_for_model(model)
        return len(encoding.encode(text))
    except Exception as e:
        logger.warning(f"Failed to count tokens with tiktoken: {e}, using fallback")
        # Fallback: approximate token count (roughly 4 characters per token)
        return len(text) // 4


async def record_usage(
    user_id: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    pages: int = 0
) -> Optional[Dict[str, Any]]:
    """
    Record token usage for a user via Supabase RPC function.
    
    Args:
        user_id: UUID of the user
        input_tokens: Number of input tokens used
        output_tokens: Number of output tokens used
        pages: Number of pages processed (default: 0, typically not used)
        
    Returns:
        Dict with success status and usage info, or None on error
    """
    try:
        import asyncio
        # Run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        
        result = await loop.run_in_executor(
            None,
            lambda: supabase.rpc(
                'record_usage',
                {
                    'p_user_id': user_id,
                    'p_input_tokens': input_tokens,
                    'p_output_tokens': output_tokens
                }
            ).execute()
        )
        
        if result.data:
            logger.info(f"Usage recorded for user {user_id[:8]}...: {input_tokens} input, {output_tokens} output tokens")
            return result.data
        else:
            logger.warning(f"No data returned from record_usage for user {user_id[:8]}...")
            return None
            
    except Exception as e:
        logger.error(f"Failed to record usage for user {user_id[:8]}...: {e}")
        return None

