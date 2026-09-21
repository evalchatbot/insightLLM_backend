"""
The fixed test environment. Applied by conftest.py before any ``backend`` import so a
developer's shell / .env can never leak real credentials or change behaviour.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

SCRATCH_DIR = Path(tempfile.mkdtemp(prefix="insightllm-tests-"))

TEST_ENV = {
    "ENVIRONMENT": "test",
    "LOG_LEVEL": "WARNING",
    # 192.0.2.0/24 is TEST-NET-1 (RFC 5737): syntactically valid, never routable.
    "SUPABASE_URL": "http://192.0.2.10:54321",
    "SUPABASE_KEY": "test-anon-key",
    "JWT_SECRET_KEY": "test-jwt-secret-not-for-production",
    "FACTBOOK_SCHEDULER_ENABLED": "false",
    "CURRENT_AFFAIRS_SCHEDULER_ENABLED": "false",
    "FACTBOOK_SYNC_TOKEN": "factbook-test-token",
    "CURRENT_AFFAIRS_SYNC_TOKEN": "current-affairs-test-token",
    "FACTBOOK_FETCH_MIN_INTERVAL_SECONDS": "0",
    "LANGSMITH_TRACING": "false",
    "LCA_BRAND_ORIGINS": "lca-portal",
    "MAX_UPLOAD_MB": "20",
    # tiktoken would otherwise download its BPE file; an empty cache dir + blocked
    # network makes every run use the same len//4 fallback.
    "TIKTOKEN_CACHE_DIR": str(SCRATCH_DIR / "tiktoken-cache"),
    "HF_HUB_OFFLINE": "1",
    "TRANSFORMERS_OFFLINE": "1",
}

REMOVED_ENV = (
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SERVICE_KEY",
    "SUPABASE_AUDIENCE",
    "SUPABASE_ISSUER",
    "SUPABASE_STORAGE_BUCKET",
    "GROK_API",
    "Grok_API",
    "GROK_API_BASE_URL",
    "GROQ_API_KEY",
    "OPENAI_API_KEY",
    "LLM_PROVIDER",
    "LANGSMITH_API_KEY",
    "LANGCHAIN_API_KEY",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_PROJECT",
    "AZURE_ENDPOINT",
    "AZURE_KEY",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "FACTBOOK_FETCH_PROXY_TOKEN",
)


def apply_test_env() -> None:
    for name in REMOVED_ENV:
        os.environ.pop(name, None)
    os.environ.update(TEST_ENV)
