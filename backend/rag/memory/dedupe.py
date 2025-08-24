from __future__ import annotations
from typing import List, Dict

def dedupe_docs(docs: List[Dict]) -> List[Dict]:
    """Keep highest-score doc per (id, chunk_id)."""
    best: Dict[str, Dict] = {}
    for d in docs:
        key = f"{d.get('id')}:{d.get('chunk_id')}"
        cur = best.get(key)
        if cur is None or (d.get('score', 0) > cur.get('score', 0)):
            best[key] = d
    return list(best.values())
