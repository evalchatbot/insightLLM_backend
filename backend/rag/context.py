"""
Context construction utilities for RAG pipeline.
"""
from typing import List, Dict

def create_context_from_chunks(chunks: List[Dict]) -> str:
    """
    Create context string from retrieved chunks, including book title and page numbers.
    """
    context_parts = []
    for chunk in chunks:
        book_title = chunk.get("book_title", "Unknown Book")
        page_start = chunk.get("page_start", "?")
        page_end = chunk.get("page_end", "?")
        content = chunk.get("content") or chunk.get("text") or ""
        context_part = f"[From {book_title}, pages {page_start}-{page_end}]\n{content}\n"
        context_parts.append(context_part)
    return "\n".join(context_parts)
