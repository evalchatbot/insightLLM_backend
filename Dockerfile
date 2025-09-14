# Use Python 3.11 for better stability in production
FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# Create non-root user for security
RUN groupadd -r appuser && useradd -r -g appuser appuser

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create directories
WORKDIR /app
RUN mkdir -p /app/logs && chown -R appuser:appuser /app

# Copy and install Python dependencies
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Set default environment variables for production
ENV PYTHONPATH=/app
ENV LOG_LEVEL=INFO
ENV ENABLE_LOGGING=true
ENV WORKERS=2
ENV MAX_WORKERS=4
ENV TIMEOUT_KEEP_ALIVE=5

# Environment variables for streaming and LLM functionality
ENV SUPABASE_URL=""
ENV SUPABASE_KEY=""
ENV SUPABASE_SERVICE_ROLE_KEY=""
ENV JWT_SECRET_KEY="supersecret"
ENV GROQ_API_KEY=""
ENV OPENAI_API_KEY=""
ENV CHATBOT_LLM_MODEL="llama-3.3-70b-versatile"
ENV LLM_PROVIDER="groq"

# Streaming and RAG configuration
ENV USE_ADAPTIVE_RAG="true"
ENV USE_MULTI_STEP_RAG="true"
ENV ENABLE_STREAMING="true"
ENV STREAMING_TIMEOUT=60
ENV MAX_TOKENS=2048

# LangSmith telemetry (optional)
ENV LANGSMITH_API_KEY=""
ENV LANGSMITH_PROJECT="insightLLM_production"
ENV LANGSMITH_TRACING="false"

# Performance settings
ENV UVICORN_LIMIT_CONCURRENCY=1000
ENV UVICORN_LIMIT_MAX_REQUESTS=10000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/ || exit 1

EXPOSE 8000

# Production command with optimized settings for streaming
CMD ["uvicorn", "backend.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "${WORKERS}", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--timeout-keep-alive", "${TIMEOUT_KEEP_ALIVE}", \
     "--limit-concurrency", "${UVICORN_LIMIT_CONCURRENCY}", \
     "--limit-max-requests", "${UVICORN_LIMIT_MAX_REQUESTS}", \
     "--log-level", "info"]
