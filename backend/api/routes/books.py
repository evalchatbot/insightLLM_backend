"""
API routes for books and genres.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List
from backend.db.supabase_client import SupabaseDB

router = APIRouter(prefix="/books", tags=["books"])

db = SupabaseDB()

class GenreListResponse(BaseModel):
    genres: List[str]

class BookInfo(BaseModel):
    id: str
    title: str
    author: str = ""
    genre: str
    file_url: str = ""

class BookListResponse(BaseModel):
    books: List[BookInfo]

@router.get("/genres", response_model=GenreListResponse)
def get_genres() -> GenreListResponse:
    """Return a list of available genres."""
    res = db.select("books")
    if not hasattr(res, 'data') or not res.data:
        return GenreListResponse(genres=[])
    genres = sorted(list({b["genre"] for b in res.data if "genre" in b}))
    return GenreListResponse(genres=genres)

@router.get("/{genre}", response_model=BookListResponse)
def get_books_by_genre(genre: str) -> BookListResponse:
    """Return a list of books for a given genre."""
    res = db.select("books", {"genre": genre})
    if not hasattr(res, 'data') or not res.data:
        return BookListResponse(books=[])
    books = [BookInfo(**b) for b in res.data]
    return BookListResponse(books=books)
