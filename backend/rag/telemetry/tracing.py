import time, json, logging
from contextlib import contextmanager
from typing import Dict, Any

logger = logging.getLogger("rag.tracing")

@contextmanager
def span(name: str, **fields: Any):
    start = time.time()
    try:
        yield
    finally:
        dur_ms = int((time.time() - start) * 1000)
        payload: Dict[str, Any] = {"event": "span", "name": name, "duration_ms": dur_ms}
        if fields:
            payload.update(fields)
        logger.info(json.dumps(payload))
