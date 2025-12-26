import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# HS256 verification (matches your token’s alg)
SUPABASE_JWT_SECRET = os.getenv("JWT_SECRET_KEY")
SUPABASE_ISSUER = f"{SUPABASE_URL}/auth/v1"
SUPABASE_AUDIENCE = os.getenv("SUPABASE_AUDIENCE", "authenticated")
#LLM
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CHATBOT_LLM_MODEL = os.getenv("CHATBOT_LLM_MODEL", "llama-3.1-8b-instant")

# Grok API (for OCR/PDF evaluation)
GROK_API = os.getenv("GROK_API") or os.getenv("Grok_API")
GROK_API_BASE_URL = os.getenv("GROK_API_BASE_URL", "https://api.x.ai/v1")

# LangSmith Configuration
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "insightLLM")
LANGSMITH_TRACING = os.getenv("LANGSMITH_TRACING", "false").lower() in ("true", "1", "yes", "on")

# OCR Retry Configuration
OCR_MAX_RETRIES = int(os.getenv("OCR_MAX_RETRIES", "3"))
OCR_RETRY_BASE_DELAY = float(os.getenv("OCR_RETRY_BASE_DELAY", "1.0"))
OCR_RETRY_MAX_DELAY = float(os.getenv("OCR_RETRY_MAX_DELAY", "60.0"))
OCR_RETRY_JITTER_RANGE = float(os.getenv("OCR_RETRY_JITTER_RANGE", "0.2"))
OCR_RATE_LIMIT_BASE_DELAY = float(os.getenv("OCR_RATE_LIMIT_BASE_DELAY", "5.0"))
OCR_RATE_LIMIT_MAX_DELAY = float(os.getenv("OCR_RATE_LIMIT_MAX_DELAY", "300.0"))

# OCR Parallel Processing Configuration
OCR_CONCURRENT_PAGES = int(os.getenv("OCR_CONCURRENT_PAGES", "1"))  # Number of pages to process in parallel
OCR_BATCH_SIZE = int(os.getenv("OCR_BATCH_SIZE", "5"))  # Number of pages to process per batch
OCR_BATCH_FAILURE_THRESHOLD = float(os.getenv("OCR_BATCH_FAILURE_THRESHOLD", "0.5"))  # Stop if batch failure rate exceeds this (0.0-1.0)

# OCR Adaptive Concurrency Configuration
OCR_ADAPTIVE_CONCURRENCY_ENABLED = os.getenv("OCR_ADAPTIVE_CONCURRENCY_ENABLED", "true").lower() in ("true", "1", "yes", "on")
OCR_ADAPTIVE_MIN_CONCURRENCY = int(os.getenv("OCR_ADAPTIVE_MIN_CONCURRENCY", "1"))  # Minimum concurrency (never go below this)
OCR_ADAPTIVE_MAX_CONCURRENCY = int(os.getenv("OCR_ADAPTIVE_MAX_CONCURRENCY", "4"))  # Maximum concurrency (never go above this)
OCR_ADAPTIVE_LATENCY_THRESHOLD_MS = float(os.getenv("OCR_ADAPTIVE_LATENCY_THRESHOLD_MS", "90000.0"))  # Reduce concurrency if average latency exceeds this (ms)
OCR_ADAPTIVE_STABLE_BATCHES = int(os.getenv("OCR_ADAPTIVE_STABLE_BATCHES", "2"))  # Number of stable batches before increasing concurrency

# OCR Image Optimization Configuration
OCR_IMAGE_OPTIMIZATION_ENABLED = os.getenv("OCR_IMAGE_OPTIMIZATION_ENABLED", "true").lower() in ("true", "1", "yes", "on")
OCR_IMAGE_MAX_DIMENSION = int(os.getenv("OCR_IMAGE_MAX_DIMENSION", "2048"))  # Maximum width or height (downscale if larger)
OCR_IMAGE_MIN_DIMENSION_FOR_OPTIMIZATION = int(os.getenv("OCR_IMAGE_MIN_DIMENSION_FOR_OPTIMIZATION", "1500"))  # Only optimize if dimension exceeds this

