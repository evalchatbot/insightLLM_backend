# backend/rag/retrieval/bm25.py
from __future__ import annotations
from typing import List, Dict
from rank_bm25 import BM25Okapi

def _tokenize(text: str) -> List[str]:
    return [t for t in text.lower().split() if t.strip()]

def rerank_with_bm25(query: str, docs: List[Dict], top_k: int = 20) -> List[Dict]:
    """
    Rerank given docs (each with 'content') using BM25 on content only.
    Returns a new list with 'bm25_score' and sorted by it desc.
    """
    if not docs:
        return []

    corpus = [_tokenize(d.get("content", "")) for d in docs]
    bm25 = BM25Okapi(corpus)
    scores = bm25.get_scores(_tokenize(query))

    ranked = []
    for d, s in zip(docs, scores):
        nd = dict(d)
        nd["bm25_score"] = float(s)
        ranked.append(nd)

    ranked.sort(key=lambda x: x.get("bm25_score", 0.0), reverse=True)
    return ranked[:top_k]
