import fitz  # PyMuPDF
import PyPDF2
from typing import List, Dict, Tuple
import re
from fastembed import TextEmbedding
import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
import logging

# Configure logging
logger = logging.getLogger(__name__)


class DocumentProcessor:
    def __init__(self, embedding_model: str = "BAAI/bge-small-en-v1.5"):
        self.embedding_model = TextEmbedding(embedding_model)
        self.text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100,
            separators=["\n\n", "\n", ". ", "! ", "? ", " ", ""]
        )

    def extract_text_from_pdf(self, file_path: str) -> List[Tuple[str, int]]:
        """
        Extract text from PDF with page numbers
        Returns: List of (text, page_number) tuples
        """
        try:
            doc = fitz.open(file_path)
            pages = []

            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text()

                # Clean text
                text = self._clean_text(text)
                if text.strip():
                    pages.append((text, page_num + 1))

            doc.close()
            return pages

        except Exception as e:
            logger.error(f"Error processing PDF {file_path}: {e}")
            raise

    def _clean_text(self, text: str) -> str:
        """Clean and normalize text"""
        # Remove extra whitespace
        text = re.sub(r'\s+', ' ', text)
        # Remove special characters but keep basic punctuation
        text = re.sub(r'[^\w\s\.\,\!\?\;\:\-\(\)\[\]\{\}]', '', text)
        return text.strip()

    def create_chunks(self, pages: List[Tuple[str, int]]) -> List[Dict]:
        """
        Create chunks from pages with metadata
        Returns: List of chunk dictionaries
        """
        chunks = []
        chunk_index = 0

        for page_text, page_num in pages:
            # Split page into chunks
            page_chunks = self.text_splitter.split_text(page_text)

            for i, chunk_text in enumerate(page_chunks):
                chunk = {
                    "content": chunk_text,
                    "page_start": page_num,
                    "page_end": page_num,
                    "chunk_index": chunk_index,
                    "metadata": {
                        "page_number": page_num,
                        "chunk_in_page": i,
                        "total_chunks_in_page": len(page_chunks)
                    }
                }
                chunks.append(chunk)
                chunk_index += 1

        return chunks

    def generate_embeddings(self, chunks: List[Dict]) -> List[Dict]:
        """
        Generate embeddings for chunks
        Returns: List of chunks with embeddings
        """
        try:
            # Extract text content for embedding
            texts = [chunk["content"] for chunk in chunks]

            # Generate embeddings
            embeddings = list(self.embedding_model.embed(texts))

            # Add embeddings to chunks
            for chunk, embedding in zip(chunks, embeddings):
                chunk["embedding"] = embedding.tolist()

            return chunks

        except Exception as e:
            logger.error(f"Error generating embeddings: {e}")
            raise

    def process_document(self, file_path: str) -> List[Dict]:
        """
        Complete document processing pipeline
        Returns: List of processed chunks with embeddings
        """
        logger.info(f"Processing document: {file_path}")

        # Extract text from PDF
        pages = self.extract_text_from_pdf(file_path)
        logger.info(f"Extracted {len(pages)} pages")

        # Create chunks
        chunks = self.create_chunks(pages)
        logger.info(f"Created {len(chunks)} chunks")

        # Generate embeddings
        chunks_with_embeddings = self.generate_embeddings(chunks)
        logger.info(f"Generated embeddings for {len(chunks_with_embeddings)} chunks")

        return chunks_with_embeddings