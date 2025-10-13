"""
API routes for the Chatbot agent (RAG, memory management).
Now includes intent-based routing inside /chatbot/ask to support general conversation
via a ConversationalAgent and book-specific queries via RAG ChatbotAgent.
"""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, AsyncGenerator
import json
import asyncio
from backend.agents.chatbot_agent import ChatbotAgent
from backend.agents.conversational_agent import ConversationalAgent
from backend.agents.intent_agent import IntentAgent
from backend.utils.logging_config import get_logger

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = get_logger(__name__)

agent = ChatbotAgent()
convo_agent = ConversationalAgent()
intent_agent = IntentAgent()


# Local sanitizer to clean contaminated questions carrying previous context
def _sanitize_question(raw: str) -> str:
    try:
        if not raw:
            return raw
        txt = raw
        if ("Please provide a comprehensive" in txt) or ("Previous context:" in txt) or ("Current question:" in txt):
            # Try to extract after "Current question:" marker
            if "Current question:" in txt:
                parts = txt.split("Current question:")
                if len(parts) > 1:
                    candidate = parts[-1].strip().strip('\n\r .,!?')
                    if len(candidate) > 5:
                        return candidate
            # Otherwise, scan lines for likely question
            lines = [l.strip() for l in txt.splitlines()]
            for line in lines:
                if not line or line.endswith(":"):
                    continue
                if line.startswith(("User:", "Assistant:")):
                    # skip role-prefixed lines
                    continue
                if len(line) > 10 and ("?" in line or any(w in line.lower() for w in ["discuss", "explain", "analyze", "what", "how", "why"])):
                    return line
            # fallback: first meaningful line
            for line in lines:
                if len(line) > 20 and not line.startswith(("Please", "Previous", "Current", "User:", "Assistant:")):
                    return line
        return raw
    except Exception:
        return raw

class ChatbotAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None

class ChatbotAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]
    context: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class ChatbotMultiAskRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    book_ids: Optional[List[str]] = None
    max_iterations: Optional[int] = 3
    conversation_id: Optional[str] = None
    auto_create_conversation: Optional[bool] = False  # NEW: Auto-create conversation with title


class ChatbotMultiAskResponse(BaseModel):
    answer: str
    sources: List[Dict[str, Any]]  # resolved chunks (with book title/author if available)
    traces: List[Dict[str, Any]]  # per-iteration debug info


class ChatbotStreamRequest(BaseModel):
    user_id: str
    session_id: str
    question: str
    genre: str
    book_ids: Optional[List[str]] = None
    conversation_id: Optional[str] = None
    mode: Optional[str] = "adaptive"  # fast, multi_step, adaptive


@router.post("/ask", response_model=ChatbotAskResponse)
async def ask_chatbot(req: ChatbotAskRequest) -> ChatbotAskResponse:
    """Ask a question to the chatbot agent (RAG, memory, vector search, async)."""
    try:
        logger.info(f"[API] Chatbot ask request: user={req.user_id[:8]}..., question_len={len(req.question)}, genre={req.genre}")
        logger.info(f"[API] Incoming question preview: '{(req.question or '')[:500]}'")
        if req.book_ids:
            logger.info(f"[API] book_ids provided: count={len(req.book_ids)}")

        if req.conversation_id:
            logger.info(f"[API] Using existing conversation: {req.conversation_id}")
        else:
            logger.info(f"[API] No conversation ID provided - messages will only be stored in memory")

        # Sanitize incoming question if contaminated
        cleaned_q = _sanitize_question(req.question)
        if cleaned_q != req.question:
            logger.warning("[API] Sanitized incoming question to remove embedded context")
        # Intent-based routing (LLM-based with heuristic fallback)
        intent = await intent_agent.classify_async(cleaned_q, genre=req.genre, book_ids=req.book_ids)
        intent_label = intent.get("intent", "book_specific")
        logger.info(
            f"[API] Intent details: label={intent_label}, conf={intent.get('confidence'):.2f}, reason={intent.get('reason')}"
        )

        if intent_label == "general":
            logger.info("[API] Calling ConversationalAgent.ask (general intent)")
            result = await convo_agent.ask(
                user_id=req.user_id,
                session_id=req.session_id,
                question=cleaned_q,
                genre=req.genre,
                conversation_id=req.conversation_id,
            )
        else:
            logger.info(
                f"[API] Calling ChatbotAgent.ask (RAG) with book_ids={len(req.book_ids) if req.book_ids else 0}"
            )
            result = await agent.ask(
                user_id=req.user_id,
                session_id=req.session_id,
                question=cleaned_q,
                genre=req.genre,
                book_ids=req.book_ids,
                conversation_id=req.conversation_id,
            )

        # Annotate routing metadata + conversation id
        result.setdefault("metadata", {})
        result["metadata"].update({
            "router_intent": intent_label,
            "router_confidence": intent.get("confidence"),
            "router_reason": intent.get("reason"),
            "routed_to": "conversational" if intent_label == "general" else "chatbot",
        })
        if req.conversation_id:
            result["metadata"]["conversation_id"] = req.conversation_id

        logger.info(f"[API] Completed via: {result['metadata'].get('routed_to')} | answer_len={len(result.get('answer',''))} | sources={len(result.get('sources', []))}")
        return ChatbotAskResponse(**result)
        
    except Exception as e:
        logger.error(f"[API] ❌ Chatbot ask failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask-multistep", response_model=ChatbotMultiAskResponse)
async def ask_chatbot_multistep(req: ChatbotMultiAskRequest) -> ChatbotMultiAskResponse:
    """
    Ask a question using the Multi-Step RAG pipeline (plan → retrieve → validate → synthesize).
    Does not affect the existing /chatbot/ask route.
    """
    try:
        result = await agent.ask_multi_step(
            user_id=req.user_id,
            session_id=req.session_id,
            question=req.question,
            genre=req.genre,
            book_ids=req.book_ids,
            max_iterations=req.max_iterations or 3,
            conversation_id=req.conversation_id
        )
        # result already matches the response model keys
        return ChatbotMultiAskResponse(**result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask-stream")
async def ask_chatbot_stream(req: ChatbotStreamRequest) -> StreamingResponse:
    """Ask a question to the chatbot agent with streaming response."""
    try:
        logger.info(f"[API] Chatbot stream request: user={req.user_id[:8]}..., question_len={len(req.question)}, genre={req.genre}, mode={req.mode}")
        logger.info(f"[API] Stream incoming question preview: '{(req.question or '')[:500]}'")
        if req.book_ids:
            logger.info(f"[API] Stream book_ids provided: count={len(req.book_ids)}")
        
        if req.conversation_id:
            logger.info(f"[API] Using existing conversation: {req.conversation_id}")
        else:
            logger.info(f"[API] No conversation ID provided - messages will only be stored in memory")
        
        async def generate_stream() -> AsyncGenerator[str, None]:
            try:
                # Sanitize and classify intent for routing
                cleaned_q = _sanitize_question(req.question)
                if cleaned_q != req.question:
                    logger.warning("[API] Stream sanitized incoming question to remove embedded context")
                intent = await intent_agent.classify_async(cleaned_q, genre=req.genre, book_ids=req.book_ids)
                intent_label = intent.get("intent", "book_specific")
                logger.info(
                    f"[API] Stream intent: label={intent_label}, conf={intent.get('confidence'):.2f}, reason={intent.get('reason')}"
                )

                # Send initial metadata (include routing info)
                metadata = {
                    "type": "metadata",
                    "conversation_id": req.conversation_id,
                    "mode": req.mode,
                    "user_id": req.user_id,
                    "router_intent": intent_label,
                    "router_confidence": intent.get("confidence"),
                    "router_reason": intent.get("reason"),
                    "routed_to": "conversational" if intent_label == "general" else "chatbot",
                }
                yield f"data: {json.dumps(metadata)}\n\n"
                
                # Get the complete response first
                if intent_label == "general":
                    logger.info("[API] Stream calling ConversationalAgent.ask (general intent)")
                    result = await convo_agent.ask(
                        user_id=req.user_id,
                        session_id=req.session_id,
                        question=cleaned_q,
                        genre=req.genre,
                        conversation_id=req.conversation_id,
                    )
                else:
                    logger.info(
                        f"[API] Stream calling ChatbotAgent.ask (RAG) with book_ids={len(req.book_ids) if req.book_ids else 0}"
                    )
                    result = await agent.ask(
                        user_id=req.user_id,
                        session_id=req.session_id,
                        question=cleaned_q,
                        genre=req.genre,
                        book_ids=req.book_ids,
                        conversation_id=req.conversation_id,
                    )
                
                # Stream the answer in chunks
                answer = result.get("answer", "")
                
                # Stream answer word by word for a more natural experience
                words = answer.split()
                current_text = ""
                
                for i, word in enumerate(words):
                    current_text += word + " "
                    
                    chunk_data = {
                        "type": "chunk",
                        "content": word + " ",
                        "full_content": current_text.strip()
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                    
                    # Add small delay for streaming effect
                    await asyncio.sleep(0.05)  # 50ms delay between words
                
                # Send final response with all metadata
                final_data = {
                    "type": "complete",
                    "answer": result.get("answer", ""),
                    "sources": result.get("sources", []),
                    "citations": result.get("citations", []),
                    "context": result.get("context", []),
                    "metadata": result.get("metadata", {}),
                }
                
                if req.conversation_id:
                    final_data["metadata"]["conversation_id"] = req.conversation_id
                # Include routing metadata in final chunk as well
                final_data["metadata"].update({
                    "router_intent": intent_label,
                    "router_confidence": intent.get("confidence"),
                    "router_reason": intent.get("reason"),
                    "routed_to": "conversational" if intent_label == "general" else "chatbot",
                })
                
                yield f"data: {json.dumps(final_data)}\n\n"
                
                logger.info(f"[API] Stream completed via: {result['metadata'].get('routed_to')} | answer_len={len(result.get('answer',''))} | sources={len(result.get('sources', []))}")
                
            except Exception as e:
                logger.error(f"[API] ❌ Chatbot stream failed: {e}")
                error_data = {
                    "type": "error",
                    "error": str(e)
                }
                yield f"data: {json.dumps(error_data)}\n\n"
        
        return StreamingResponse(
            generate_stream(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
        
    except Exception as e:
        logger.error(f"[API] ❌ Chatbot stream setup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/ask-stream-enhanced")
async def ask_chatbot_stream_enhanced(req: ChatbotStreamRequest) -> StreamingResponse:
    """Ask a question to the chatbot agent with real LLM streaming response."""
    try:
        logger.info(f"[API] Enhanced chatbot stream request: user={req.user_id[:8]}..., question_len={len(req.question)}, genre={req.genre}, mode={req.mode}")
        
        if req.conversation_id:
            logger.info(f"[API] Using existing conversation: {req.conversation_id}")
        else:
            logger.info(f"[API] No conversation ID provided - messages will only be stored in memory")
        
        async def generate_enhanced_stream() -> AsyncGenerator[str, None]:
            try:
                from backend.rag.llm.streaming_client import get_streaming_llm_client
                from backend.agents.tools.rag_tool import get_rag_tool
                
                # Send initial metadata
                metadata = {
                    "type": "metadata",
                    "conversation_id": req.conversation_id,
                    "mode": req.mode,
                    "user_id": req.user_id
                }
                yield f"data: {json.dumps(metadata)}\n\n"
                
                # Get RAG tool for context retrieval
                rag_tool = get_rag_tool()
                
                # Get conversation context
                if req.conversation_id:
                    context = await agent._get_conversation_context(req.conversation_id)
                else:
                    context = agent.short_term.get_recent_messages(req.user_id, req.session_id)
                
                # For streaming, we'll use fast mode to get context quickly, then stream the generation
                # Get relevant chunks using the fast retrieval method
                import time
                start_time = time.time()
                
                # Generate query embedding
                query_embedding = await rag_tool.embedding.generate(req.question)
                
                # Get book IDs if not provided
                books_res = rag_tool.db.select("books", {"genre": req.genre})
                book_ids = [b["id"] for b in books_res.data] if hasattr(books_res, 'data') else []
                book_ids = book_ids[:5]  # Limit for faster retrieval
                
                # Retrieve relevant chunks
                chunks = await rag_tool.db.search_chunks_vector(query_embedding, book_ids, top_k=5)
                
                # Enrich chunks with book metadata
                if chunks:
                    unique_book_ids = list(set(chunk["book_id"] for chunk in chunks))
                    books_data = rag_tool.db.select("books", {"id": unique_book_ids})
                    book_map = {book["id"]: book for book in books_data.data} if hasattr(books_data, 'data') else {}
                    
                    for chunk in chunks:
                        book = book_map.get(chunk["book_id"])
                        if book:
                            chunk["book_title"] = book["title"]
                            chunk["book_author"] = book["author"]
                
                # Create context and compose prompt
                from backend.rag.context import create_context_from_chunks
                context_str = create_context_from_chunks(chunks)
                prompt = rag_tool._compose_css_prompt(req.question, context, context_str)
                
                # Send sources information
                sources_data = {
                    "type": "sources",
                    "sources": chunks,
                    "source_count": len(chunks)
                }
                yield f"data: {json.dumps(sources_data, default=str)}\n\n"
                
                # Initialize streaming LLM client
                streaming_client = get_streaming_llm_client()
                
                # Stream the answer generation in real-time
                full_answer = ""
                async for chunk in streaming_client.generate_stream(
                    prompt=prompt,
                    temperature=0.4,
                    max_tokens=2048
                ):
                    full_answer += chunk
                    
                    chunk_data = {
                        "type": "chunk",
                        "content": chunk,
                        "full_content": full_answer
                    }
                    yield f"data: {json.dumps(chunk_data)}\n\n"
                
                # Update memory with conversation after streaming is complete
                await agent._update_conversation_memory(
                    req.user_id, req.session_id, req.question, full_answer, 
                    req.conversation_id, []
                )
                
                # Create citations from chunks
                from backend.rag.models.schemas import Citation
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
                
                # Send final completion data
                final_data = {
                    "type": "complete",
                    "answer": full_answer,
                    "sources": chunks,
                    "citations": [c.__dict__ for c in citations],
                    "context": context,
                    "metadata": {
                        "mode": "streaming_enhanced",
                        "retrieved_chunks": len(chunks),
                        "book_ids": book_ids,
                        "execution_time": execution_time,
                        "conversation_id": req.conversation_id
                    }
                }
                
                yield f"data: {json.dumps(final_data, default=str)}\n\n"
                
                logger.info(f"[API] Enhanced stream completed: answer_len={len(full_answer)}, sources={len(chunks)}, time={execution_time:.2f}s")
                
            except Exception as e:
                logger.error(f"[API] ❌ Enhanced chatbot stream failed: {e}")
                import traceback
                logger.error(f"[API] Traceback: {traceback.format_exc()}")
                error_data = {
                    "type": "error",
                    "error": str(e)
                }
                yield f"data: {json.dumps(error_data)}\n\n"
        
        return StreamingResponse(
            generate_enhanced_stream(),
            media_type="text/plain",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Headers": "*",
            }
        )
        
    except Exception as e:
        logger.error(f"[API] ❌ Enhanced chatbot stream setup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
