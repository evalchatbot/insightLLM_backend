#!/usr/bin/.env python3
"""
Bulk-ingest all PDFs in a folder into Supabase (books + document_chunks).

Hardcoded config at the top:
- FOLDER_PATH: directory containing PDFs
- DEFAULT_GENRE: stored in books.genre for every PDF
- DEFAULT_AUTHOR: stored in books.author
- EMBED_MODEL: embedding model for fastembed
- BATCH_SIZE: insert chunk rows in batches
- SKIP_EXISTING: if True, skip a PDF when a book with same title already exists

Env (..env):
  SUPABASE_URL=
  SUPABASE_KEY=
  SUPABASE_SERVICE_ROLE_KEY=
"""

import os
import sys
import json
import time
import glob
import logging
from typing import Dict, List, Any

from dotenv import load_dotenv
from supabase import create_client, Client

# ----- HARD-CODED CONFIG -----
FOLDER_PATH     = r"C:\Users\khana\Downloads\Political Science Books Batch II\Not done"  # <-- put your folder path here
DEFAULT_GENRE   = "Political-Science"                               # <-- put your genre here
DEFAULT_AUTHOR  = "Unknown Author"
EMBED_MODEL     = "BAAI/bge-small-en-v1.5"
BATCH_SIZE      = 200
SKIP_EXISTING   = True
# -----------------------------

# Reuse your existing processor (same chunking + embedding behavior)
# Ensure document_processor.py is in the same folder or on PYTHONPATH.
from backend.ingest.document_processor import DocumentProcessor  # uses your chunking + BGE small v1.5

logger = logging.getLogger("bulk_ingest_fixed")
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
logger.addHandler(handler)
logger.setLevel(logging.INFO)


def get_supabase_client() -> Client:
    url = os.getenv("SUPABASE_URL")
    service_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    if not url or not service_key:
        raise RuntimeError("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in environment.")
    return create_client(url, service_key)


def find_existing_book_id(supabase: Client, title: str) -> str | None:
    resp = supabase.table("books").select("id").eq("title", title).limit(1).execute()
    data = getattr(resp, "data", None) or []
    return data[0]["id"] if data else None


def create_book(
    supabase: Client,
    title: str,
    author: str,
    genre: str,
    total_pages: int | None,
) -> str:
    payload = {
        "title": title,
        "author": author,
        "genre": genre,
        "total_pages": total_pages or 0,
    }
    # Insert without chaining .select()
    resp = supabase.table("books").insert(payload).execute()

    data = getattr(resp, "data", None)
    if isinstance(data, list) and data and "id" in data[0]:
        return data[0]["id"]

    # Fallback: fetch back by title
    check = supabase.table("books").select("id").eq("title", title).limit(1).execute()
    rows = getattr(check, "data", []) or []
    if rows:
        return rows[0]["id"]

    raise RuntimeError(f"Failed to create book for title={title!r}")



def insert_chunks_batched(
    supabase: Client,
    book_id: str,
    chunks: List[Dict[str, Any]],
    batch_size: int = 200,
) -> int:
    rows = []
    for ch in chunks:
        rows.append({
            "book_id": book_id,
            "content": ch["content"],
            "page_start": ch["page_start"],
            "page_end": ch["page_end"],
            "chunk_index": ch["chunk_index"],
            "embedding": ch["embedding"],        # pgvector column: list[float]
            "metadata": ch.get("metadata", {}),  # jsonb
        })

    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        resp = supabase.table("document_chunks").insert(batch).execute()
        if getattr(resp, "error", None):
            raise RuntimeError(f"Failed chunk insert: {resp.error}")
        total += len(batch)
        logger.info(f"Inserted {total}/{len(rows)} chunks...")
    return total


def process_one_pdf(
    supabase: Client,
    processor: DocumentProcessor,
    pdf_path: str,
    genre: str,
    author: str,
    skip_existing: bool,
    batch_size: int,
) -> Dict[str, Any]:
    title = os.path.splitext(os.path.basename(pdf_path))[0]

    if skip_existing:
        existing = find_existing_book_id(supabase, title)
        if existing:
            logger.info(f"Skipping (exists): {title}  -> book_id={existing}")
            return {"title": title, "book_id": existing, "chunks": 0, "skipped": True}

    logger.info(f"Processing: {title}")

    # Chunk + embed via your pipeline
    chunks = processor.process_document(pdf_path)
    if not chunks:
        logger.warning(f"No chunks produced for {title}; skipping.")
        return {"title": title, "book_id": None, "chunks": 0, "skipped": True}

    total_pages = 0
    try:
        total_pages = max(ch["page_end"] for ch in chunks)
    except Exception:
        pass

    book_id = create_book(supabase, title=title, author=author, genre=genre, total_pages=total_pages)
    inserted = insert_chunks_batched(supabase, book_id, chunks, batch_size=batch_size)

    logger.info(f"Done: {title} -> book_id={book_id}, chunks={inserted}")
    return {"title": title, "book_id": book_id, "chunks": inserted, "skipped": False}


def main():
    load_dotenv()
    supabase = get_supabase_client()

    # Initialize your existing document processor with your hardcoded embed model
    processor = DocumentProcessor(embedding_model=EMBED_MODEL)

    pdf_paths = sorted(glob.glob(os.path.join(FOLDER_PATH, "*.pdf")))
    if not pdf_paths:
        logger.error(f"No PDFs found in FOLDER_PATH: {FOLDER_PATH}")
        sys.exit(1)

    logger.info(f"Found {len(pdf_paths)} PDFs in: {FOLDER_PATH}")
    logger.info(f"Using genre: {DEFAULT_GENRE!r}, author: {DEFAULT_AUTHOR!r}, model: {EMBED_MODEL}")

    results = []
    t0 = time.time()
    for p in pdf_paths:
        try:
            res = process_one_pdf(
                supabase=supabase,
                processor=processor,
                pdf_path=p,
                genre=DEFAULT_GENRE,
                author=DEFAULT_AUTHOR,
                skip_existing=SKIP_EXISTING,
                batch_size=BATCH_SIZE,
            )
            results.append(res)
        except Exception as e:
            logger.exception(f"Failed to ingest {p}: {e}")
            results.append({"title": os.path.basename(p), "book_id": None, "chunks": 0, "error": str(e)})

    elapsed = time.time() - t0
    logger.info("----------- SUMMARY -----------")
    total_books = sum(0 if r.get("skipped") else 1 for r in results if r.get("book_id"))
    total_chunks = sum(r.get("chunks", 0) for r in results)
    skipped = sum(1 for r in results if r.get("skipped"))
    failed = [r for r in results if r.get("error")]

    logger.info(f"Ingested books: {total_books}")
    logger.info(f"Skipped (existing/no chunks): {skipped}")
    logger.info(f"Total chunks inserted: {total_chunks}")
    logger.info(f"Failed: {len(failed)}")
    logger.info(f"Elapsed: {elapsed:.1f}s")

    print(json.dumps({
        "ingested_books": total_books,
        "skipped": skipped,
        "total_chunks": total_chunks,
        "failed": len(failed),
        "elapsed_sec": round(elapsed, 1),
        "details": results
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
