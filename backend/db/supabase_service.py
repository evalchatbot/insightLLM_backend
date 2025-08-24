from supabase import create_client, Client
from typing import List, Dict, Optional
import logging
from datetime import datetime
import uuid

logger = logging.getLogger(__name__)


class SupabaseService:
    def __init__(self, supabase_url: str, supabase_key: str):
        self.supabase: Client = create_client(supabase_url, supabase_key)

    # Book operations
    async def create_book(self, book_data: Dict) -> Dict:
        """Create a new book record"""
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
            return result.data[0] if result.data else None

        except Exception as e:
            logger.error(f"Error creating book: {e}")
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
        """
        try:
            query = self.supabase.rpc(
                'match_documents',
                {
                    'query_embedding': query_embedding,
                    'match_count': top_k,
                    'book_ids': book_ids
                }
            ).execute()
            return query.data if query.data else []
        except Exception as e:
            logger.error(f"Error in vector search: {e}")
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