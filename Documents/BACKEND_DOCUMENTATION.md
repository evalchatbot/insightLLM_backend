# Backend Documentation - Rubrik AI

## Table of Contents

1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [Technology Stack](#technology-stack)
4. [Project Structure](#project-structure)
5. [API Routes](#api-routes)
6. [Modules & Components](#modules--components)
7. [Database & Storage](#database--storage)
8. [Authentication & Security](#authentication--security)
9. [Configuration](#configuration)
10. [Development Guidelines](#development-guidelines)
11. [Deployment](#deployment)
12. [Troubleshooting](#troubleshooting)

---

## Project Overview

**Rubrik AI Backend** is a FastAPI-based backend service that powers an AI-powered essay evaluation and feedback platform for CSS exam preparation. The backend provides:

- AI-powered chatbot for exam preparation guidance
- OCR-based PDF evaluation and annotation system
- Conversation memory management (short-term and long-term)
- User management and authentication
- Book/document ingestion and management
- Quiz/MCQ generation
- Usage tracking and analytics

---

## Architecture

### Framework

- **FastAPI**: Modern, fast web framework for building APIs
- **Python 3.13+**: Programming language
- **Async/Await**: Asynchronous request handling
- **Modular Design**: Separated concerns (agents, routes, services, utils)

### Key Architectural Patterns

1. **RESTful API Design**: Standard HTTP methods and status codes
2. **Dependency Injection**: FastAPI's dependency system for auth and services
3. **Service Layer**: Business logic separated from routes
4. **Repository Pattern**: Database operations abstracted in services
5. **Agent Pattern**: AI agents for chatbot and evaluation
6. **Memory Management**: Two-tier memory system (short-term + long-term)

### Request Flow

```
Client Request
    ↓
FastAPI Middleware (CORS, Logging)
    ↓
Authentication (JWT/Clerk)
    ↓
API Route Handler
    ↓
Service Layer / Agent
    ↓
Database (Supabase)
    ↓
Response
```

---

## Technology Stack

### Core Dependencies

- **FastAPI 0.116.1**: Web framework
- **Uvicorn**: ASGI server
- **Pydantic 2.11.7**: Data validation
- **Python-dotenv**: Environment variable management

### Database & Storage

- **Supabase 2.18.1**: Database and storage service
- **Supabase Client**: Python client for database operations

### AI & LLM

- **LangChain 0.3.27**: LLM framework
- **FastEmbed 0.7.1**: Embedding generation
- **Tiktoken**: Token counting
- **Grok API**: OCR evaluation (via Google Cloud Vision)
- **Groq API**: LLM inference

### Document Processing

- **PyMuPDF 1.26.4**: PDF processing
- **PyPDF2 3.0.1**: PDF manipulation
- **python-docx**: Word document processing
- **Pillow**: Image processing
- **OpenCV**: Computer vision

### Utilities

- **httpx 0.28.1**: HTTP client
- **python-jose 3.5.0**: JWT handling
- **loguru 0.7.3**: Logging
- **rank-bm25 0.2.2**: BM25 retrieval
- **numpy 2.3.2**: Numerical operations
- **requests 2.32.3**: HTTP requests
- **langsmith 0.4.14**: LLM tracing

---

## Project Structure

```
insightLLM_backend/
├── backend/
│   ├── main.py                    # FastAPI application entry point
│   ├── config.py                  # Configuration and environment variables
│   │
│   ├── api/                       # API routes
│   │   └── routes/
│   │       ├── auth.py            # Authentication routes
│   │       ├── chatbot.py         # Chatbot endpoints
│   │       ├── ocr.py              # OCR evaluation endpoints
│   │       ├── users.py            # User management
│   │       ├── conversations.py   # Conversation management
│   │       ├── books.py            # Book management
│   │       ├── ingest.py           # Document ingestion
│   │       ├── quiz.py             # Quiz/MCQ endpoints
│   │       └── assistant.py       # Assistant endpoints
│   │
│   ├── agents/                    # AI agents
│   │   ├── chatbot_agent.py       # Main chatbot agent
│   │   ├── conversational_agent.py # Conversational agent
│   │   ├── intent_agent.py         # Intent classification
│   │   └── tools/
│   │       └── rag_tool.py         # RAG tool for agents
│   │
│   ├── db/                        # Database layer
│   │   ├── models.py              # Pydantic models
│   │   ├── supabase_client.py     # Supabase client setup
│   │   ├── supabase_service.py   # Database service layer
│   │   └── storage.py             # File storage service
│   │
│   ├── memory/                     # Memory management
│   │   ├── short_term.py          # In-memory conversation state
│   │   ├── long_term.py           # Supabase-backed long-term memory
│   │   └── conversation_summarizer.py # Conversation summarization
│   │
│   ├── ocr/                       # OCR evaluation system
│   │   ├── service.py             # OCR service wrapper
│   │   ├── grade_pdf_answer.py   # PDF grading logic
│   │   ├── annotate_pdf_with_rubric.py # PDF annotation
│   │   └── 20marks_Rubrics/       # Subject rubrics
│   │
│   ├── rag/                       # RAG (Retrieval Augmented Generation)
│   │   ├── adapters/              # Storage adapters
│   │   ├── llm/                   # LLM clients
│   │   ├── memory/                # Memory components
│   │   ├── planning/              # Query planning
│   │   ├── reasoning/             # Reasoning components
│   │   ├── retrieval/            # Retrieval components
│   │   └── telemetry/             # Monitoring
│   │
│   ├── utils/                     # Utility functions
│   │   ├── logging_config.py     # Logging setup
│   │   ├── grok_client.py        # Grok API client
│   │   ├── pdf_utils.py           # PDF utilities
│   │   ├── pdf_renderer.py        # PDF rendering
│   │   ├── rubric_loader.py       # Rubric loading
│   │   ├── rubric_parser.py       # Rubric parsing
│   │   ├── rubric_evaluator.py   # Rubric evaluation
│   │   ├── report_builder_new.py  # Report generation
│   │   └── usage_tracking.py     # Usage tracking
│   │
│   ├── middleware/                # Middleware
│   │   └── logging_middleware.py # API logging middleware
│   │
│   ├── ingest/                    # Document ingestion
│   │   └── document_processor.py # Document processing
│   │
│   ├── tests/                     # Test files
│   │   └── test_*.py              # Various test files
│   │
│   └── migrations/                # Database migrations
│       └── *.sql                  # SQL migration files
│
├── requirements.txt               # Python dependencies
├── README.md                      # Project README
└── .env.example                   # Environment variables template
```

---

## API Routes

### Base URL

- **Development**: `http://localhost:8000`
- **Production**: [Production URL]

### Authentication

Most endpoints require JWT authentication via Bearer token in the `Authorization` header:

```
Authorization: Bearer <JWT_TOKEN>
```

### Route Categories

#### Chatbot Routes (`/chatbot`)

- `POST /chatbot/ask` - Non-streaming chatbot query
- `POST /chatbot/ask-multi` - Multi-step chatbot query
- `POST /chatbot/stream` - Streaming chatbot response
- `POST /chatbot/stream-multi` - Multi-step streaming

#### OCR Routes (`/api/ocr`)

- `POST /api/ocr/annotate` - Annotate PDF with evaluation
- `POST /api/ocr/annotate/json` - Get evaluation as JSON
- `GET /api/ocr/subjects` - Get available subjects

#### User Routes (`/user`)

- `POST /user/token` - Generate JWT token
- `GET /user/session/{id}` - Get session info
- `POST /user/session/create` - Create session

#### Conversation Routes (`/conversations`)

- `GET /conversations` - List conversations
- `POST /conversations` - Create conversation
- `GET /conversations/{id}` - Get conversation
- `PUT /conversations/{id}` - Update conversation
- `DELETE /conversations/{id}` - Delete conversation
- `GET /conversations/{id}/messages` - Get messages

#### Book Routes (`/books`)

- `GET /books/genres` - List genres
- `GET /books/{genre}` - Get books by genre
- `GET /books/{id}` - Get book details

#### Ingest Routes (`/ingest`)

- `POST /ingest/upload` - Upload and process document

#### Quiz Routes (`/quiz`)

- `GET /quiz/mcqs` - Get MCQ questions

#### Assistant Routes (`/assistant`)

- Assistant-related endpoints

---

## Modules & Components

### Agents

#### `chatbot_agent.py`

Main chatbot agent for exam preparation guidance.

**Key Features**:

- CSS/PMS-focused system prompt
- Conversation memory management
- Streaming and non-streaming responses
- Question analysis and context building

**Methods**:

- `ask()` - Generate complete answer
- `ask_fast()` - Fast mode (backwards compatibility)
- `ask_multi_step()` - Multi-step reasoning
- `ask_stream()` - Streaming response
- `ask_stream_multi()` - Multi-step streaming

#### `conversational_agent.py`

Conversational agent for general chat.

#### `intent_agent.py`

Intent classification for user queries.

### OCR System

#### `service.py`

OCR service wrapper that orchestrates PDF evaluation.

**Key Features**:

- PDF annotation with rubrics
- Subject-based evaluation
- Metadata generation
- Error handling and logging
- Memory-efficient processing

**Methods**:

- `annotate_pdf()` - Main annotation method
- `get_all_available_subjects()` - List subjects

#### `grade_pdf_answer.py`

Core PDF grading logic using Grok API.

**Key Features**:

- OCR processing with timeout protection
- Retry logic with exponential backoff
- Incremental PDF writing (memory-efficient)
- Partial success support
- Comprehensive error handling

**Memory Optimizations**:

- Incremental PDF writing using PyPDF2
- No double accumulation of pages
- ~40% reduction in peak memory during writing

#### `annotate_pdf_with_rubric.py`

PDF annotation with rubric-based feedback.

**Key Features**:

- Memory-efficient page processing (one at a time)
- Memory monitoring and validation
- Graceful failure handling
- Section-based annotation
- Page-wise improvement suggestions

**Memory Optimizations**:

- Pages processed individually (not all at once)
- Explicit memory cleanup after each page
- Pre-processing memory validation
- Periodic memory monitoring
- ~60-70% reduction in peak memory usage

PDF annotation with rubric-based feedback.

### Memory Management

#### `short_term.py`

In-memory conversation state using LangGraph InMemoryStore.

**Features**:

- Fast access to recent conversation
- Session-based storage
- Automatic cleanup

#### `long_term.py`

Supabase-backed long-term memory storage.

**Features**:

- Persistent conversation history
- Conversation summarization
- Efficient storage

#### `conversation_summarizer.py`

Intelligent conversation summarization.

**Features**:

- Summarizes after N exchanges
- Maintains context quality
- Reduces storage by 95-99%

### RAG System

The RAG (Retrieval Augmented Generation) system provides:

- **Retrieval**: Hybrid retrieval (BM25 + embeddings)
- **Planning**: Query decomposition and sub-question generation
- **Reasoning**: Multi-step reasoning with validation
- **Memory**: Embedding cache and deduplication
- **LLM**: Streaming LLM clients (Groq, OpenAI)

### Database Services

#### `supabase_service.py`

Service layer for Supabase operations.

**Features**:

- Book operations (CRUD)
- Document chunk management
- Conversation management
- Message storage
- User operations
- Usage tracking

#### `storage.py`

File storage service for PDFs and documents.

**Features**:

- PDF upload to Supabase Storage
- Signed URL generation
- File management

---

## Database & Storage

> **Note:** For complete and detailed database documentation including all tables, functions, relationships, and business logic, see [`Documents/DATABASE_DOCUMENTATION.md`](../../Documents/DATABASE_DOCUMENTATION.md).

### Supabase Tables

#### `users`

- `id` (UUID, primary key, references `auth.users.id`)
- `email` (VARCHAR, unique, not null)
- `full_name` (VARCHAR, nullable)
- `created_at`, `updated_at` (timestamps)

#### `conversations`

- `id` (UUID, primary key)
- `user_id` (VARCHAR, not null) - **Note:** VARCHAR type (Clerk user ID), not UUID
- `chat_id` (VARCHAR, unique, not null)
- `title` (VARCHAR, nullable)
- `icon` (VARCHAR, nullable)
- `is_pinned` (BOOLEAN, default: false)
- `created_at`, `updated_at` (timestamps)

#### `messages`

- `id` (UUID, primary key)
- `conversation_id` (UUID, foreign key → `conversations.id`)
- `user_prompt` (TEXT, nullable)
- `llm_response` (TEXT, nullable)
- `img_name` (VARCHAR, nullable)
- `created_at`, `updated_at` (timestamps)

#### `books`

- `id` (UUID, primary key)
- `title` (VARCHAR, not null)
- `author` (VARCHAR, not null)
- `genre` (USER-DEFINED type: `genre_type`, default: 'other') - **Note:** Enum type, not string
- `total_pages` (INTEGER, nullable)
- `created_at`, `updated_at` (timestamps)

#### `document_chunks`

- `id` (UUID, primary key)
- `book_id` (UUID, foreign key → `books.id`)
- `content` (TEXT, not null)
- `page_start`, `page_end` (INTEGER, not null)
- `chunk_index` (INTEGER, not null)
- `embedding` (vector type, nullable) - For RAG/semantic search
- `metadata` (JSONB, default: '{}')
- `created_at` (timestamp)

#### `genres`

- `id` (UUID, primary key)
- `name` (TEXT, unique, not null)
- `description` (TEXT, nullable)
- `created_at` (timestamp)

#### `mcqs`

- `id` (UUID, primary key)
- `genre_id` (UUID, foreign key → `genres.id`, nullable)
- `question` (TEXT, not null)
- `option_a`, `option_b`, `option_c`, `option_d` (TEXT, nullable)
- `correct_answer` (TEXT, not null)
- `difficulty` (SMALLINT, default: 1)
- `question_hash` (TEXT, unique, not null) - Prevents duplicate questions
- `metadata` (JSONB, nullable)
- `created_at` (timestamp)

#### `sessions`

- `id` (TEXT, primary key) - **Note:** TEXT type, not UUID
- `user_id` (UUID, foreign key → `users.id`, nullable)
- `created_at` (timestamp)

#### `long_term_memory`

- `id` (UUID, primary key)
- `user_id` (UUID, not null)
- `session_id` (TEXT, not null)
- `context` (TEXT, nullable)
- `fact` (TEXT, not null)
- `created_at`, `updated_at` (timestamps)

#### `keys` - Subscription Keys

- `id` (UUID, primary key)
- `key` (TEXT, unique, not null) - Subscription key string
- `is_used` (BOOLEAN, default: false)
- `used_by` (UUID, foreign key → `users.id`, nullable)
- `expiry_date` (TIMESTAMP WITH TIME ZONE, not null)
- `duration_days` (INTEGER, default: 30)
- `created_at`, `updated_at` (timestamps)

**Business Logic:**
- Active subscription = `is_used = true` AND `expiry_date > CURRENT_TIMESTAMP`
- Keys can only be used once
- Used for Pro tier access management
- **⚠️ Renewal Support DISABLED**: Renewal functionality is currently disabled. Users with active subscriptions are blocked from activating new keys. The database migrations (016, 017) are in place but the API blocks renewals.
- **Audit Trail**: `subscription_renewals` table exists (Migration 017) but is not currently used (renewal disabled)

#### `usage_free` - Free Tier Usage Tracking

- `user_id` (UUID, primary key, foreign key → `users.id`)
- `period_start` (DATE, primary key) - First day of month
- `tokens_input_used` (BIGINT, default: 0)
- `tokens_output_used` (BIGINT, default: 0)
- `ocr_count` (INTEGER, default: 0) - PDF generation count
- `last_used` (TIMESTAMP WITH TIME ZONE, default: CURRENT_TIMESTAMP)
- `created_at`, `updated_at` (timestamps)

**Composite Primary Key:** `(user_id, period_start)`

**Business Logic:**
- Resets to 0 on 1st of each month (automatic via `reset_monthly_free_usage()`)
- Only for users without active Pro subscriptions
- **Usage Limits:** 250K input tokens, 500K output tokens, 2 PDFs per month

#### `usage_pro` - Pro Tier Usage Tracking

- `user_id` (UUID, primary key, foreign key → `users.id`)
- `period_start` (DATE, primary key) - Activation date (30-day period)
- `tokens_input_used` (BIGINT, default: 0)
- `tokens_output_used` (BIGINT, default: 0)
- `ocr_count` (INTEGER, default: 0) - PDF generation count
- `last_used` (TIMESTAMP WITH TIME ZONE, default: CURRENT_TIMESTAMP)
- `created_at`, `updated_at` (timestamps)

**Composite Primary Key:** `(user_id, period_start)`

**Business Logic:**
- Period starts on key activation date (not month start)
- Period lasts 30 days from activation
- Resets to 0 when new key is activated (new activations only)
- **⚠️ Renewals DISABLED**: Renewal functionality is currently disabled. Users must wait until subscription expires before activating a new key.
- Auto-downgrade to free if limits exceeded
- **Usage Limits:** 1M input tokens, 3M output tokens, 20 PDFs per period

#### `subscription_renewals` - Renewal Audit Trail

- `id` (UUID, primary key)
- `user_id` (UUID, foreign key → `users.id`)
- `old_expiry_date` (TIMESTAMP WITH TIME ZONE, not null)
- `new_expiry_date` (TIMESTAMP WITH TIME ZONE, not null)
- `key_id` (UUID, foreign key → `keys.id`) - The renewal key used
- `duration_added_days` (INTEGER, not null)
- `was_capped` (BOOLEAN, default: false) - Whether expiry was capped at 12 months
- `renewed_at` (TIMESTAMP WITH TIME ZONE, default: CURRENT_TIMESTAMP)

**Business Logic:**
- Automatically created when `activate_pro_key` detects a renewal
- One record per renewal
- Provides complete audit trail for support and analytics
- Never deleted (permanent history)

**Indexes:**
- Primary key on `id`
- Index on `user_id` (for user renewal history)
- Index on `key_id` (for key-based queries)
- Index on `renewed_at DESC` (for date range queries)

**Use Cases:**
- Track renewal history for users
- Analytics and reporting
- Support ticket resolution
- Debugging subscription issues

### Database Functions (RPC)

The database includes several PostgreSQL functions for business logic:

1. **`activate_pro_key(key_id UUID, user_identifier UUID)`**
   - Activates a Pro subscription key (Migration 016: supports renewals, Migration 017: logs to audit trail)
   - **⚠️ Renewal DISABLED**: The database function supports renewals, but the API blocks users with active subscriptions from reaching this function
   - **New Activation Only**: If no active subscription, creates new activation (resets usage)
   - Expiry cap logic exists in function but is not used (renewal disabled)
   - Creates/updates `usage_pro` record (new activations only)
   - Resets usage counters to 0 (new activations only)
   - Clears free usage when upgrading
   - **Audit Trail**: `subscription_renewals` table exists (Migration 017) but is not currently used (renewal disabled)
   - Returns activation information only (renewal responses disabled in API)

2. **`record_usage(p_user_id UUID, p_input_tokens INTEGER, p_output_tokens INTEGER)`**
   - Records token usage (Pro or Free)
   - Enforces usage limits
   - Handles auto-downgrade when Pro limits exceeded

3. **`check_usage_limit(p_user_id UUID, p_input_tokens INTEGER, p_output_tokens INTEGER)`**
   - Pre-flight check before operations
   - Returns `can_proceed: false` if limits would be exceeded

4. **`check_ocr_limit(p_user_id UUID)`**
   - Checks if user can generate another PDF
   - Enforces OCR count limits (Free: 2, Pro: 20)

5. **`record_ocr_usage(p_user_id UUID)`**
   - Records OCR usage after PDF generation
   - Handles auto-downgrade if Pro OCR limit reached

6. **`reset_monthly_free_usage()`**
   - Automatically resets free user usage on 1st of each month
   - Scheduled via `pg_cron` (00:05 UTC on 1st of month)

7. **`trigger_monthly_reset(secret_key TEXT)`**
   - HTTP-triggerable monthly reset (for external cron services)

**Usage Limits:**
- **Free Tier:** 250K input tokens, 500K output tokens, 2 PDFs/month
- **Pro Tier:** 1M input tokens, 3M output tokens, 20 PDFs/30-day period

**Auto-Downgrade:**
- Pro users who exceed limits are automatically downgraded to free tier
- Key `expiry_date` set to `CURRENT_TIMESTAMP`
- `usage_pro` record deleted, `usage_free` record created with 0 usage

### Storage Buckets

- **PDFs**: User-uploaded and annotated PDFs
- **Documents**: Ingested documents

---

## Authentication & Security

### JWT Authentication

- Uses `python-jose` for JWT handling
- HS256 algorithm
- Supabase-compatible tokens
- Token validation via `get_current_user` dependency

### Authentication Flow

1. User authenticates via Clerk (frontend)
2. Frontend receives JWT token
3. Token sent in `Authorization: Bearer <token>` header
4. Backend validates token using Supabase JWT secret
5. User ID extracted from token payload

### Protected Routes

Most routes use `Depends(get_current_user)` for authentication:

```python
from backend.api.routes.auth import get_current_user

@router.get("/protected")
async def protected_route(user: AuthUser = Depends(get_current_user)):
    # user.user_id and user.email available
    pass
```

### CORS Configuration

Configured in `main.py`:

- Allowed origins: Frontend URLs
- Credentials: Enabled
- Methods: All methods
- Headers: All headers

---

## Configuration

### Environment Variables

#### Required

- `SUPABASE_URL`: Supabase project URL
- `SUPABASE_KEY`: Supabase service role key
- `JWT_SECRET_KEY`: JWT secret for token validation
- `SUPABASE_AUDIENCE`: JWT audience (default: "authenticated")

#### LLM Configuration

- `GROQ_API_KEY`: Groq API key for LLM inference
- `CHATBOT_LLM_MODEL`: Model name (default: "llama-3.1-8b-instant")
- `GROK_API`: Grok API key for OCR evaluation
- `GROK_API_BASE_URL`: Grok API base URL

#### OCR Timeout Configuration

- `OCR_PER_PAGE_TIMEOUT`: Maximum seconds per page OCR call (default: 120.0)
- `OCR_OVERALL_TIMEOUT`: Maximum seconds for entire OCR process (default: 600.0)

**Recommended Values**:

- Small files (<5 pages): `OCR_PER_PAGE_TIMEOUT=60-90`, `OCR_OVERALL_TIMEOUT=300`
- Medium files (5-20 pages): `OCR_PER_PAGE_TIMEOUT=120`, `OCR_OVERALL_TIMEOUT=600` (default)
- Large files (20+ pages): `OCR_PER_PAGE_TIMEOUT=180`, `OCR_OVERALL_TIMEOUT=1200`

**See Also**: [Timeout Handling Implementation](./TIMEOUT_HANDLING_IMPLEMENTATION.md) for detailed configuration and troubleshooting.

#### LangSmith (Optional)

- `LANGSMITH_API_KEY`: LangSmith API key
- `LANGSMITH_PROJECT`: Project name (default: "insightLLM")
- `LANGSMITH_TRACING`: Enable tracing (default: "false")

#### Other

- `MAX_UPLOAD_MB`: Maximum upload size in MB (default: 20)
- `LOG_LEVEL`: Logging level (default: "INFO")

### Configuration File

`backend/config.py` loads and validates environment variables.

---

## Development Guidelines

### Code Style

- Follow PEP 8 Python style guide
- Use type hints for all functions
- Document complex logic with docstrings
- Use async/await for I/O operations

### Project Structure

- Routes in `api/routes/`
- Business logic in services/agents
- Database operations in `db/`
- Utilities in `utils/`
- Models in `db/models.py`

### Error Handling

- Use FastAPI's `HTTPException` for API errors
- Log errors with appropriate levels
- Return meaningful error messages
- Handle edge cases gracefully

### Logging

- Use centralized logging via `utils/logging_config.py`
- Log all API requests/responses
- Include request IDs for tracing
- Use appropriate log levels (DEBUG, INFO, WARNING, ERROR)

### Testing

- Write tests for critical functionality
- Use pytest for testing
- Mock external services in tests
- Test error cases

### Best Practices

1. **Async First**: Use async/await for I/O
2. **Type Safety**: Use Pydantic models
3. **Error Handling**: Always handle exceptions
4. **Logging**: Log important operations
5. **Documentation**: Document complex logic
6. **Security**: Validate all inputs
7. **Performance**: Optimize database queries

---

## Deployment

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variables
export SUPABASE_URL=your_url
export SUPABASE_KEY=your_key
export JWT_SECRET_KEY=your_secret

# Run development server
uvicorn backend.main:app --reload
```

### Docker Deployment

```bash
# Build image
docker build -t rubrik-ai-backend .

# Run container
docker run -d -p 8000:8000 \
  -e SUPABASE_URL=your_url \
  -e SUPABASE_KEY=your_key \
  -e JWT_SECRET_KEY=your_secret \
  rubrik-ai-backend
```

### Production Considerations

- Use environment variables for secrets
- Enable HTTPS
- Configure CORS properly
- Set up monitoring and logging
- Use connection pooling for database
- Implement rate limiting
- Set up health checks

---

## Troubleshooting

### Common Issues

#### Supabase Connection Errors

- Verify `SUPABASE_URL` and `SUPABASE_KEY`
- Check network connectivity
- Verify table schemas match models

#### JWT Authentication Failures

- Verify `JWT_SECRET_KEY` matches frontend
- Check token expiration
- Verify token audience and issuer

#### OCR Evaluation Failures

- Check Grok API key
- Verify PDF format
- Check subject availability
- Review logs for errors

**Timeout Issues**:

- **Per-page timeouts**: Increase `OCR_PER_PAGE_TIMEOUT` if pages consistently timeout
- **Overall timeouts**: Increase `OCR_OVERALL_TIMEOUT` for large files
- **Partial success**: System continues processing even if some pages timeout
- Check logs in `logs/log.txt` for timeout details and page numbers

**Common Timeout Scenarios**:

- Large/complex PDFs may need increased timeouts
- Network issues can cause timeouts (check connectivity)
- Google Vision API rate limits may cause delays
- Very high-resolution images take longer to process

**See Also**: [Timeout Handling Implementation](./TIMEOUT_HANDLING_IMPLEMENTATION.md) for detailed timeout troubleshooting.

#### Memory Issues

- Check conversation summarization
- Monitor database storage
- Review memory cleanup logic

### Debugging

- Enable debug logging: `LOG_LEVEL=DEBUG`
- Check logs in `logs/insightllm.log`
- Use FastAPI's `/docs` endpoint for API testing
- Enable LangSmith tracing for LLM debugging

---

## Additional Resources

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [Supabase Python Client](https://supabase.com/docs/reference/python/introduction)
- [LangChain Documentation](https://python.langchain.com/)
- [Pydantic Documentation](https://docs.pydantic.dev/)

---

**Last Updated**: 2025
**Maintained By**: Development Team
