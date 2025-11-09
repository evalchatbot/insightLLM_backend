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

