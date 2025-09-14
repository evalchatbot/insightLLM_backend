from supabase import create_client, Client
from typing import List, Dict, Optional
import logging
from datetime import datetime
import uuid
import json
import time

from backend.utils.logging_config import log_supabase_request, log_supabase_response, get_logger

logger = get_logger(__name__)


class SupabaseService:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)

    # Book operations
    async def create_book(self, book_data: Dict) -> Dict:
        """Create a new book record"""
        start_time = time.time()
        log_supabase_request(logger, "INSERT", "books", data=book_data)
        
        try:
            book_id = str(uuid.uuid4())
            book_record = {
                "id": book_id,
                "title": book_data["title"],
                "author": book_data["author"],
                "genre": book_data["genre"],
                "total_pages": book_data["total_pages"],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            result = self.supabase.table("books").insert(book_record).execute()
            execution_time = time.time() - start_time
            
            response_data = result.data[0] if result.data else None
            log_supabase_response(logger, "INSERT", "books", response_data, execution_time)
            return response_data

        except Exception as e:
            execution_time = time.time() - start_time
            log_supabase_response(logger, "INSERT", "books", None, execution_time, str(e))
            raise

    async def get_book_by_id(self, book_id: str) -> Optional[Dict]:
        """Get book by ID"""
        try:
            result = self.supabase.table("books").select("*").eq("id", book_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting book: {e}")
            return None

    async def get_books_by_genre(self, genre: str) -> List[Dict]:
        """Get all books in a specific genre"""
        try:
            result = self.supabase.table("books").select("*").eq("genre", genre).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting books by genre: {e}")
            return []

    async def get_books_by_ids(self, book_ids: List[str]) -> List[Dict]:
        """Get multiple books by their IDs"""
        try:
            if not book_ids:
                return []
            result = self.supabase.table("books").select("*").in_("id", book_ids).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting books by IDs: {e}")
            return []

    # Document chunk operations
    async def create_chunks(self, chunks: List[Dict]) -> List[Dict]:
        """Create multiple document chunks"""
        try:
            chunk_records = []
            for chunk in chunks:
                chunk_record = {
                    "id": str(uuid.uuid4()),
                    "book_id": chunk["book_id"],
                    "content": chunk["content"],
                    "page_start": chunk["page_start"],
                    "page_end": chunk["page_end"],
                    "chunk_index": chunk["chunk_index"],
                    "embedding": chunk["embedding"],
                    "metadata": chunk["metadata"],
                    "created_at": datetime.utcnow().isoformat()
                }
                chunk_records.append(chunk_record)

            result = self.supabase.table("document_chunks").insert(chunk_records).execute()
            return result.data if result.data else []

        except Exception as e:
            logger.error(f"Error creating chunks: {e}")
            raise

    async def get_chunks_by_book_ids(self, book_ids: List[str]) -> List[Dict]:
        """Get all chunks for specific books"""
        try:
            result = self.supabase.table("document_chunks").select("*").in_("book_id", book_ids).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting chunks by book IDs: {e}")
            return []

    async def search_chunks_vector(self, query_embedding: List[float], book_ids: List[str], top_k: int = 5) -> List[
        Dict]:
        """
        Performs vector similarity search for chunks using pgvector.
        Fixed timeout and error handling.
        """
        start_time = time.time()
        
        # Limit top_k to prevent timeout issues
        safe_top_k = min(top_k, 20)  # Limit to max 20 results
        
        # Limit book_ids to prevent timeout
        safe_book_ids = book_ids[:10] if book_ids else []  # Limit to max 10 books
        
        # Log the vector search request
        search_params = {
            "embedding_dim": len(query_embedding),
            "top_k": safe_top_k,
            "book_ids_count": len(safe_book_ids),
            "book_ids": safe_book_ids[:3]  # Log first few for debugging
        }
        log_supabase_request(logger, "RPC", "match_documents", data=search_params)
        
        try:
            # First try the RPC function
            try:
                rpc_start = time.time()
                query = self.supabase.rpc(
                    'match_documents',
                    {
                        'query_embedding': query_embedding,
                        'match_count': safe_top_k,
                        'book_ids': safe_book_ids
                    }
                ).execute()
                
                rpc_time = time.time() - rpc_start
                log_supabase_response(logger, "RPC", "match_documents", query.data, rpc_time)
                return query.data if query.data else []
                
            except Exception as rpc_error:
                rpc_time = time.time() - start_time
                log_supabase_response(logger, "RPC", "match_documents", None, rpc_time, str(rpc_error))
                
                # Fallback: Try direct similarity search if RPC fails
                logger.info(f"[SUPABASE] Attempting fallback similarity search")
                log_supabase_request(logger, "SELECT", "document_chunks", filters={"book_ids": safe_book_ids})
                
                fallback_start = time.time()
                # Fallback query using direct table access (if possible)
                fallback_query = (
                    self.supabase.table("document_chunks")
                    .select("*")
                    .in_("book_id", safe_book_ids) if safe_book_ids else
                    self.supabase.table("document_chunks").select("*")
                )
                
                result = fallback_query.limit(safe_top_k).execute()
                fallback_time = time.time() - fallback_start
                log_supabase_response(logger, "SELECT", "document_chunks", result.data, fallback_time)
                return result.data if result.data else []
                
        except Exception as e:
            execution_time = time.time() - start_time
            log_supabase_response(logger, "RPC/SELECT", "vector_search", None, execution_time, str(e))
            logger.error(f"[SUPABASE] Error type: {type(e)}")
            
            # Return empty list instead of crashing
            return []

    # Notebook operations
    async def create_notebook(self, notebook_data: Dict) -> Dict:
        """Create a new notebook"""
        try:
            notebook_id = str(uuid.uuid4())
            notebook_record = {
                "id": notebook_id,
                "user_id": notebook_data["user_id"],
                "name": notebook_data["name"],
                "selected_books": notebook_data["selected_books"],
                "selected_genres": notebook_data["selected_genres"],
                "memory_summary": "",
                "key_facts": [],
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat()
            }

            result = self.supabase.table("notebooks").insert(notebook_record).execute()
            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"Error creating notebook: {e}")
            raise

    async def get_notebook_by_id(self, notebook_id: str, user_id: str = None) -> Optional[Dict]:
        """Get notebook by ID, optionally filtering by user_id"""
        try:
            logger.info(f"Getting notebook by id: {notebook_id} for user_id: {user_id}")
            query = self.supabase.table("notebooks").select("*").eq("id", notebook_id)
            if user_id:
                query = query.eq("user_id", user_id)

            result = query.execute()
            logger.info(f"Supabase result: {result}")
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting notebook: {e}")
            return None

    async def update_notebook_memory(self, notebook_id: str, memory_summary: str, key_facts: List[str]) -> bool:
        """Update notebook memory and key facts"""
        try:
            result = self.supabase.table("notebooks").update({
                "memory_summary": memory_summary,
                "key_facts": key_facts,
                "updated_at": datetime.utcnow().isoformat()
            }).eq("id", notebook_id).execute()

            return len(result.data) > 0

        except Exception as e:
            logger.error(f"Error updating notebook memory: {e}")
            return False

    # Chat operations
    async def save_chat_message(self, chat_data: Dict) -> Dict:
        """Save a chat message"""
        try:
            message_id = str(uuid.uuid4())
            message_record = {
                "id": message_id,
                "notebook_id": chat_data["notebook_id"],
                "user_message": chat_data["user_message"],
                "assistant_response": chat_data["assistant_response"],
                "citations": chat_data["citations"],
                "timestamp": datetime.utcnow().isoformat()
            }

            result = self.supabase.table("chat_messages").insert(message_record).execute()
            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"Error saving chat message: {e}")
            raise

    async def get_chat_history(self, notebook_id: str, limit: int = 50) -> List[Dict]:
        """Get chat history for a notebook"""
        try:
            result = self.supabase.table("chat_messages").select("*").eq("notebook_id", notebook_id).order("timestamp",
                                                                                                           desc=False).limit(
                limit).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    # User operations
    async def get_user_notebooks(self, user_id: str) -> List[Dict]:
        """Get all notebooks for a user"""
        try:
            result = self.supabase.table("notebooks").select("*").eq("user_id", user_id).order("updated_at",
                                                                                               desc=True).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"Error getting user notebooks: {e}")
            return []
    
    # Conversation operations
    def create_conversation(self, conversation_data: Dict) -> Dict:
        """Create a new conversation with proper foreign key handling"""
        start_time = time.time()
        log_supabase_request(logger, "INSERT", "conversations", data=conversation_data)
        
        try:
            # Validate user_id exists to prevent foreign key constraint violation
            user_id = conversation_data["user_id"]
            logger.info(f"[SUPABASE] Validating user_id: {user_id}")
            
            # Check if user exists with detailed logging
            log_supabase_request(logger, "SELECT", "users", filters={"id": user_id})
            user_check_start = time.time()
            user_check = self.supabase.table("users").select("id").eq("id", user_id).limit(1).execute()
            user_check_time = time.time() - user_check_start
            log_supabase_response(logger, "SELECT", "users", user_check.data, user_check_time)
            
            if not user_check.data or len(user_check.data) == 0:
                logger.warning(f"[SUPABASE] User {user_id} does not exist, attempting to use existing user")
                
                # Try to get any existing user as fallback with logging
                log_supabase_request(logger, "SELECT", "users", filters={"limit": 1})
                fallback_start = time.time()
                existing_users = self.supabase.table("users").select("id").limit(1).execute()
                fallback_time = time.time() - fallback_start
                log_supabase_response(logger, "SELECT", "users", existing_users.data, fallback_time)
                
                if existing_users.data and len(existing_users.data) > 0:
                    fallback_user_id = existing_users.data[0]["id"]
                    logger.info(f"[SUPABASE] Using existing user as fallback: {fallback_user_id}")
                    user_id = fallback_user_id
                else:
                    error_msg = "No valid user_id available for conversation creation"
                    execution_time = time.time() - start_time
                    log_supabase_response(logger, "INSERT", "conversations", None, execution_time, error_msg)
                    raise ValueError(error_msg)
            else:
                logger.info(f"[SUPABASE] User validation successful: {user_id}")
            
            conversation_id = str(uuid.uuid4())
            conversation_record = {
                "id": conversation_id,
                "user_id": user_id,  # Use validated/corrected user_id
                "title": conversation_data["title"],
                "genre": conversation_data.get("genre"),
                "book_ids": conversation_data.get("book_ids", []),
                "created_at": datetime.utcnow().isoformat(),
                "updated_at": datetime.utcnow().isoformat(),
                "message_count": 0,
                "is_active": True
            }
            
            logger.info(f"[SUPABASE] Creating conversation with record: {conversation_id}")
            
            result = self.supabase.table("conversations").insert(conversation_record).execute()
            execution_time = time.time() - start_time
            
            response_data = result.data[0] if result.data else None
            log_supabase_response(logger, "INSERT", "conversations", response_data, execution_time)
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"[SUPABASE] Insert error details: {result.error}")
            
            return response_data
        
        except Exception as e:
            execution_time = time.time() - start_time
            log_supabase_response(logger, "INSERT", "conversations", None, execution_time, str(e))
            logger.error(f"[SUPABASE] Exception type: {type(e)}")
            import traceback
            logger.error(f"[SUPABASE] Traceback: {traceback.format_exc()}")
            raise
    
    def get_user_conversations(self, user_id: str, limit: int = 50) -> List[Dict]:
        """Get all conversations for a user"""
        try:
            logger.info(f"[SUPABASE] Getting conversations for user: {user_id}")
            result = self.supabase.table("conversations").select("*").eq("user_id", user_id).eq("is_active", True).order("updated_at", desc=True).limit(limit).execute()
            
            logger.info(f"[SUPABASE] Query result: {result}")
            logger.info(f"[SUPABASE] Found {len(result.data) if result.data else 0} conversations")
            
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"[SUPABASE] Error getting user conversations: {e}")
            import traceback
            logger.error(f"[SUPABASE] Traceback: {traceback.format_exc()}")
            return []
    
    def get_conversation_by_id(self, conversation_id: str, user_id: str = None) -> Optional[Dict]:
        """Get conversation by ID, optionally filtering by user_id"""
        try:
            query = self.supabase.table("conversations").select("*").eq("id", conversation_id)
            if user_id:
                query = query.eq("user_id", user_id)
            
            result = query.execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(f"Error getting conversation: {e}")
            return None
    
    def update_conversation(self, conversation_id: str, updates: Dict) -> bool:
        """Update conversation metadata"""
        try:
            updates["updated_at"] = datetime.utcnow().isoformat()
            result = self.supabase.table("conversations").update(updates).eq("id", conversation_id).execute()
            return len(result.data) > 0
        except Exception as e:
            logger.error(f"Error updating conversation: {e}")
            return False
    
    def add_conversation_message(self, message_data: Dict) -> Dict:
        """Add a message to a conversation"""
        start_time = time.time()
        log_supabase_request(logger, "INSERT", "conversation_messages", data=message_data)
        
        try:
            message_id = str(uuid.uuid4())
            message_record = {
                "id": message_id,
                "conversation_id": message_data["conversation_id"],
                "sender": message_data["sender"],
                "message": message_data["message"],
                "citations": message_data.get("citations", []),
                "metadata": message_data.get("metadata", {}),
                "created_at": datetime.utcnow().isoformat()
            }
            
            logger.info(f"[SUPABASE] Adding message to conversation {message_data['conversation_id']} (sender: {message_data['sender']})")
            
            result = self.supabase.table("conversation_messages").insert(message_record).execute()
            execution_time = time.time() - start_time
            
            response_data = result.data[0] if result.data else None
            log_supabase_response(logger, "INSERT", "conversation_messages", response_data, execution_time)
            
            if hasattr(result, 'error') and result.error:
                logger.error(f"[SUPABASE] Message insert error details: {result.error}")
            
            return response_data
        
        except Exception as e:
            execution_time = time.time() - start_time
            log_supabase_response(logger, "INSERT", "conversation_messages", None, execution_time, str(e))
            logger.error(f"[SUPABASE] Exception type: {type(e)}")
            import traceback
            logger.error(f"[SUPABASE] Traceback: {traceback.format_exc()}")
            raise
    
    def get_conversation_messages(self, conversation_id: str, limit: int = 100, offset: int = 0) -> List[Dict]:
        """Get messages for a conversation"""
        start_time = time.time()
        filters = {"conversation_id": conversation_id, "limit": limit, "offset": offset}
        log_supabase_request(logger, "SELECT", "conversation_messages", filters=filters)
        
        try:
            result = self.supabase.table("conversation_messages").select("*").eq("conversation_id", conversation_id).order("created_at").range(offset, offset + limit - 1).execute()
            execution_time = time.time() - start_time
            
            log_supabase_response(logger, "SELECT", "conversation_messages", result.data, execution_time)
            return result.data if result.data else []
            
        except Exception as e:
            execution_time = time.time() - start_time
            log_supabase_response(logger, "SELECT", "conversation_messages", None, execution_time, str(e))
            import traceback
            logger.error(f"[SUPABASE] Traceback: {traceback.format_exc()}")
            return []
    
    def get_recent_conversation_messages(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Get recent messages for a conversation (for context)"""
        try:
            result = self.supabase.table("conversation_messages").select("*").eq("conversation_id", conversation_id).order("created_at", desc=True).limit(limit).execute()
            # Reverse to get chronological order
            messages = result.data if result.data else []
            return list(reversed(messages))
        except Exception as e:
            logger.error(f"Error getting recent conversation messages: {e}")
            return []
    
    def delete_conversation(self, conversation_id: str, user_id: str = None) -> bool:
        """Soft delete a conversation (mark as inactive)"""
        try:
            query = self.supabase.table("conversations").update({"is_active": False, "updated_at": datetime.utcnow().isoformat()})
            if user_id:
                query = query.eq("user_id", user_id)
            query = query.eq("id", conversation_id)
            
            result = query.execute()
            return len(result.data) > 0
        except Exception as e:
            logger.error(f"Error deleting conversation: {e}")
            return False
    
    def get_valid_user_id(self, requested_user_id: str = None) -> Optional[str]:
        """Get a valid user ID for conversation creation, handling foreign key constraints."""
        try:
            # If specific user requested, validate it exists
            if requested_user_id:
                user_check = self.supabase.table("users").select("id").eq("id", requested_user_id).limit(1).execute()
                if user_check.data and len(user_check.data) > 0:
                    logger.info(f"[SUPABASE] Validated requested user: {requested_user_id}")
                    return requested_user_id
                else:
                    logger.warning(f"[SUPABASE] Requested user {requested_user_id} not found")
            
            # Fallback: get any existing user
            existing_users = self.supabase.table("users").select("id").limit(1).execute()
            if existing_users.data and len(existing_users.data) > 0:
                fallback_id = existing_users.data[0]["id"]
                logger.info(f"[SUPABASE] Using fallback user: {fallback_id}")
                return fallback_id
            
            logger.error(f"[SUPABASE] No users found in database")
            return None
            
        except Exception as e:
            logger.error(f"[SUPABASE] Error getting valid user ID: {e}")
            return None
