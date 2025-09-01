"""
LangSmith tracing utilities for InsightLLM agents.
Provides decorators and context managers for tracing agent operations.
"""
import os
import functools
import asyncio
from typing import Any, Dict, List, Optional, Callable, Union
from contextlib import asynccontextmanager, contextmanager
import logging

from backend.config import LANGSMITH_API_KEY, LANGSMITH_PROJECT, LANGSMITH_TRACING

logger = logging.getLogger(__name__)

# Initialize LangSmith client if tracing is enabled
langsmith_client = None
if LANGSMITH_TRACING and LANGSMITH_API_KEY:
    try:
        from langsmith import Client
        langsmith_client = Client(api_key=LANGSMITH_API_KEY)
        # Set environment variables for automatic tracing
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_API_KEY"] = LANGSMITH_API_KEY
        os.environ["LANGCHAIN_PROJECT"] = LANGSMITH_PROJECT
        logger.info(f"LangSmith tracing enabled for project: {LANGSMITH_PROJECT}")
    except ImportError:
        logger.warning("LangSmith not installed. Install with: pip install langsmith")
        langsmith_client = None
    except Exception as e:
        logger.error(f"Failed to initialize LangSmith client: {e}")
        langsmith_client = None
else:
    logger.info("LangSmith tracing disabled. Set LANGSMITH_TRACING=true and LANGSMITH_API_KEY to enable.")


class LangSmithTracer:
    """LangSmith tracing utilities for agent operations."""
    
    @staticmethod
    def is_enabled() -> bool:
        """Check if LangSmith tracing is enabled and properly configured."""
        return langsmith_client is not None
    
    @staticmethod
    @asynccontextmanager
    async def trace_run(
        name: str,
        run_type: str = "chain",
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ):
        """Async context manager for tracing a run with LangSmith."""
        if not LangSmithTracer.is_enabled():
            yield None
            return
        
        try:
            from langsmith import traceable
            
            # Create a traceable function
            @traceable(
                name=name,
                run_type=run_type,
                metadata=metadata or {},
                tags=tags or []
            )
            async def traced_operation():
                return None
            
            # Start the trace
            run_id = None
            try:
                # Execute the traceable function to start the trace
                await traced_operation()
                yield run_id
            except Exception as e:
                logger.error(f"LangSmith tracing error: {e}")
                yield None
                
        except ImportError:
            logger.warning("LangSmith traceable not available")
            yield None
        except Exception as e:
            logger.error(f"Error in LangSmith trace_run: {e}")
            yield None
    
    @staticmethod
    @contextmanager
    def trace_sync(
        name: str,
        run_type: str = "chain",
        inputs: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None
    ):
        """Synchronous context manager for tracing a run with LangSmith."""
        if not LangSmithTracer.is_enabled():
            yield None
            return
        
        try:
            from langsmith import traceable
            
            @traceable(
                name=name,
                run_type=run_type,
                metadata=metadata or {},
                tags=tags or []
            )
            def traced_operation():
                return None
            
            try:
                traced_operation()
                yield None
            except Exception as e:
                logger.error(f"LangSmith tracing error: {e}")
                yield None
                
        except ImportError:
            logger.warning("LangSmith traceable not available")
            yield None
        except Exception as e:
            logger.error(f"Error in LangSmith trace_sync: {e}")
            yield None


def trace_agent_method(
    name: Optional[str] = None,
    run_type: str = "chain",
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Decorator for tracing agent methods with LangSmith.
    
    Args:
        name: Custom name for the trace (defaults to method name)
        run_type: Type of run (chain, llm, tool, etc.)
        tags: Tags to add to the trace
        metadata: Additional metadata for the trace
    """
    def decorator(func: Callable) -> Callable:
        if not LangSmithTracer.is_enabled():
            return func
        
        trace_name = name or f"{func.__qualname__}"
        trace_tags = (tags or []) + ["agent", "insightLLM"]
        trace_metadata = metadata or {}
        
        if asyncio.iscoroutinefunction(func):
            @functools.wraps(func)
            async def async_wrapper(*args, **kwargs):
                try:
                    from langsmith import traceable
                    
                    @traceable(
                        name=trace_name,
                        run_type=run_type,
                        tags=trace_tags,
                        metadata=trace_metadata
                    )
                    async def traced_func(*args, **kwargs):
                        return await func(*args, **kwargs)
                    
                    return await traced_func(*args, **kwargs)
                except ImportError:
                    logger.warning("LangSmith not available, running without tracing")
                    return await func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"LangSmith tracing error in {trace_name}: {e}")
                    return await func(*args, **kwargs)
            
            return async_wrapper
        else:
            @functools.wraps(func)
            def sync_wrapper(*args, **kwargs):
                try:
                    from langsmith import traceable
                    
                    @traceable(
                        name=trace_name,
                        run_type=run_type,
                        tags=trace_tags,
                        metadata=trace_metadata
                    )
                    def traced_func(*args, **kwargs):
                        return func(*args, **kwargs)
                    
                    return traced_func(*args, **kwargs)
                except ImportError:
                    logger.warning("LangSmith not available, running without tracing")
                    return func(*args, **kwargs)
                except Exception as e:
                    logger.error(f"LangSmith tracing error in {trace_name}: {e}")
                    return func(*args, **kwargs)
            
            return sync_wrapper
    
    return decorator


def trace_llm_call(
    name: Optional[str] = None,
    model: Optional[str] = None,
    provider: str = "groq"
):
    """
    Decorator specifically for LLM calls with LangSmith.
    
    Args:
        name: Custom name for the trace
        model: Model name to include in metadata
        provider: LLM provider name
    """
    def decorator(func: Callable) -> Callable:
        if not LangSmithTracer.is_enabled():
            return func
        
        trace_name = name or f"{provider}_llm_call"
        trace_metadata = {"provider": provider}
        if model:
            trace_metadata["model"] = model
        
        return trace_agent_method(
            name=trace_name,
            run_type="llm",
            tags=["llm", provider],
            metadata=trace_metadata
        )(func)
    
    return decorator


def trace_retrieval(name: Optional[str] = None):
    """
    Decorator for tracing retrieval operations.
    
    Args:
        name: Custom name for the trace
    """
    def decorator(func: Callable) -> Callable:
        if not LangSmithTracer.is_enabled():
            return func
        
        trace_name = name or f"retrieval_{func.__name__}"
        
        return trace_agent_method(
            name=trace_name,
            run_type="retriever",
            tags=["retrieval", "rag"],
            metadata={"component": "retrieval"}
        )(func)
    
    return decorator


def log_to_langsmith(
    run_name: str,
    inputs: Dict[str, Any],
    outputs: Dict[str, Any],
    run_type: str = "chain",
    metadata: Optional[Dict[str, Any]] = None,
    tags: Optional[List[str]] = None
):
    """
    Manually log a run to LangSmith.
    
    Args:
        run_name: Name of the run
        inputs: Input data for the run
        outputs: Output data from the run
        run_type: Type of run (chain, llm, tool, etc.)
        metadata: Additional metadata
        tags: Tags for the run
    """
    if not LangSmithTracer.is_enabled():
        return
    
    try:
        langsmith_client.create_run(
            name=run_name,
            run_type=run_type,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata or {},
            tags=(tags or []) + ["insightLLM"]
        )
    except Exception as e:
        logger.error(f"Failed to log run to LangSmith: {e}")
