# Backend Modules Documentation

This document provides detailed documentation for all backend modules, agents, services, and components.

---

## Table of Contents

1. [Agents](#agents)
2. [OCR System](#ocr-system)
3. [Memory Management](#memory-management)
4. [RAG System](#rag-system)
5. [Database Services](#database-services)
6. [Utilities](#utilities)
7. [Middleware](#middleware)

---

## Agents

### `chatbot_agent.py`

**Location**: `backend/agents/chatbot_agent.py`

**Purpose**: Main chatbot agent for CSS/PMS exam preparation guidance.

#### Class: `ChatbotAgent`

**Initialization**:

```python
agent = ChatbotAgent()
```

**Dependencies**:

- `ShortTermMemory`: In-memory conversation state
- `LongTermMemory`: Supabase-backed persistent memory
- `StreamingLLMClient`: LLM inference client
- `SupabaseService`: Database operations

#### Key Methods

##### `ask(user_id, session_id, question, genre, book_ids, conversation_id)`

Generate complete answer (non-streaming).

**Parameters**:

- `user_id` (str): User identifier
- `session_id` (str): Session identifier
- `question` (str): User's question
- `genre` (str): Question genre (default: "general")
- `book_ids` (List[str], optional): Book IDs for context
- `conversation_id` (str, optional): Conversation ID

**Returns**: `Dict[str, object]`

- `answer`: Generated answer
- `sources`: Source citations (empty for non-RAG)
- `citations`: Citations (empty)
- `context`: Conversation context
- `metadata`: Response metadata

**Features**:

- Question sanitization
- Question analysis
- Context retrieval from memory
- LLM generation with system prompt
- Memory updates

##### `ask_stream(user_id, session_id, question, genre, book_ids, conversation_id)`

Generate streaming answer.

**Returns**: `AsyncGenerator[str, None]` - Streaming text chunks

**Usage**:

```python
async for chunk in agent.ask_stream(
    user_id="user_123",
    session_id="session_456",
    question="What is CSS?"
):
    print(chunk, end="")
```

##### `ask_multi_step(user_id, session_id, question, genre, book_ids, conversation_id)`

Multi-step reasoning (currently delegates to `ask()`).

##### `ask_stream_multi(user_id, session_id, question, genre, book_ids, conversation_id)`

Multi-step streaming (currently delegates to `ask_stream()`).

#### System Prompt

The agent uses a CSS/PMS-focused system prompt:

- Pakistani competitive exam mentor
- Political Science and governance focus
- Scholarly yet approachable tone
- Evidence-based responses
- Analytical arguments

#### Memory Integration

- Updates short-term memory after each exchange
- Triggers long-term memory summarization when needed
- Maintains conversation context across sessions

---

### `conversational_agent.py`

**Location**: `backend/agents/conversational_agent.py`

**Purpose**: Conversational agent for general chat interactions.

**Note**: Check implementation for specific features.

---

### `intent_agent.py`

**Location**: `backend/agents/intent_agent.py`

**Purpose**: Intent classification for user queries.

**Features**:

- Classifies user intent
- Routes to appropriate handlers
- Supports multiple intent types

---

### `tools/rag_tool.py`

**Location**: `backend/agents/tools/rag_tool.py`

**Purpose**: RAG tool for agent-based retrieval.

**Features**:

- Document retrieval
- Context augmentation
- Source citation

---

## OCR System

### `service.py`

**Location**: `backend/ocr/service.py`

**Purpose**: OCR evaluation service wrapper.

#### Class: `OCRAnnotator`

**Initialization**:

```python
annotator = OCRAnnotator()
```

#### Methods

##### `annotate_pdf(pdf_bytes, original_filename, subject, user_id)`

Annotate PDF with AI evaluation.

**Parameters**:

- `pdf_bytes` (bytes): PDF file bytes
- `original_filename` (str): Original filename
- `subject` (str): Subject name for rubric
- `user_id` (str, optional): User ID for tracking

**Returns**: `Tuple[bytes, Dict[str, Any]]`

- Annotated PDF bytes
- Metadata dictionary with scores and feedback

**Features**:

- Temporary file management
- Calls `grade_pdf_answer()` function
- Error handling and logging
- Cleanup of temporary files

**Usage**:

```python
annotator = OCRAnnotator()
with open("answer.pdf", "rb") as f:
    pdf_bytes = f.read()

annotated_pdf, metadata = annotator.annotate_pdf(
    pdf_bytes=pdf_bytes,
    original_filename="answer.pdf",
    subject="Political Science",
    user_id="user_123"
)

# Save annotated PDF
with open("annotated.pdf", "wb") as f:
    f.write(annotated_pdf)

# Access metadata
scores = metadata.get("scores", {})
feedback = metadata.get("feedback", {})
```

##### `get_all_available_subjects()`

Get list of available subjects.

**Returns**: `List[Dict[str, str]]` - List of subject dictionaries

---

### `grade_pdf_answer.py`

**Location**: `backend/ocr/grade_pdf_answer.py`

**Purpose**: Core PDF grading logic using Grok API.

**Key Functions**:

- `grade_pdf_answer()`: Main grading function
- `run_ocr_on_pdf()`: OCR processing with timeout protection
- `_call_vision_with_timeout()`: Timeout wrapper for Vision API calls
- PDF text extraction
- Rubric-based evaluation
- Score calculation
- Feedback generation

**Features**:

- Uses Grok API for evaluation
- **Timeout Handling**: Per-page and overall timeouts prevent indefinite hangs
- **Retry Logic**: Exponential backoff with error classification for transient failures
- **Partial Success Support**: Continues processing even if some pages fail
- **Error Recovery**: Graceful handling of timeouts and API errors
- **Incremental PDF Writing**: Memory-efficient PDF generation using PyPDF2
- Rubric-based scoring
- Detailed feedback generation
- JSON metadata output
- Annotated PDF generation

#### Incremental PDF Writing

The PDF writing process uses incremental writing to avoid memory accumulation:

**Implementation**:

- Uses PyPDF2 `PdfWriter` for incremental PDF writing
- Converts each PIL Image to PDF bytes and adds immediately
- No re-accumulation of pages in memory
- Reduces peak memory during writing by ~40%

**Benefits**:

- Removed double accumulation (`all_pages` list)
- More memory-efficient than PIL's `append_images`
- Better scalability for larger PDFs (30+ pages)

**See Also**: [Incremental PDF Writing Implementation](./INCREMENTAL_PDF_WRITING_IMPLEMENTATION.md) for detailed documentation.

#### Timeout Handling

The OCR system includes comprehensive timeout protection to prevent indefinite hangs:

**Per-Page Timeout**:

- Each page OCR call has a maximum time limit (default: 120 seconds)
- If a page times out, processing continues with other pages
- Failed pages are tracked and reported in metadata

**Overall Timeout**:

- Entire OCR process has a maximum time limit (default: 1200 seconds / 20 minutes)
- Prevents jobs from running indefinitely
- Returns partial results if timeout is reached

**Configuration**:

```bash
# Environment variables in .env
OCR_PER_PAGE_TIMEOUT=180.0    # Seconds per page (default: 120)
OCR_OVERALL_TIMEOUT=1200.0     # Total seconds (default: 600)
```

**Error Handling**:

- Timeout errors are logged with page numbers and durations
- Partial results returned when some pages succeed
- Clear error messages for debugging

**See Also**: 
- [Timeout Handling Implementation](./TIMEOUT_HANDLING_IMPLEMENTATION.md) for detailed documentation
- [Retry Logic Implementation](./RETRY_LOGIC_IMPLEMENTATION.md) for retry mechanism details
- [Retry Policy](./RETRY_POLICY.md) for retry policy definition

---

#### Retry Logic

The OCR system includes comprehensive retry logic with exponential backoff to handle transient failures gracefully and improve overall reliability.

**Core Principle**: Retry transient failures, fail fast on permanent errors

**Implementation**: `_call_vision_with_retry()` function wraps `_call_vision_with_timeout()` with retry logic

##### Error Classification

Errors are automatically classified as **retryable** or **non-retryable**:

**Retryable Errors** (will retry):
- **Network/Connection Errors**: `ConnectionError`, `ConnectionResetError`, `TimeoutError` (within budget)
- **Rate Limit Errors**: HTTP 429, `RESOURCE_EXHAUSTED`, rate limit messages
- **Temporary Server Errors**: HTTP 500, 502, 503, 504, `UNAVAILABLE`, `DEADLINE_EXCEEDED`
- **Timeout Errors**: If retry budget allows and overall timeout permits

**Non-Retryable Errors** (fail fast):
- **Authentication Errors**: HTTP 401, 403, `PERMISSION_DENIED`
- **Invalid Request Errors**: HTTP 400, 422, `INVALID_ARGUMENT`, `INVALID_IMAGE`, `ValueError`
- **Resource Not Found**: HTTP 404, `NOT_FOUND`
- **Deterministic Failures**: Invalid image format, file corruption, size limits

**Error Classification Function**: `_is_retryable_error()` automatically classifies errors based on type, HTTP status codes, and error messages.

##### Exponential Backoff Formula

**Standard Backoff**:
```
delay = base_delay * (2 ^ (attempt_number - 1)) + jitter
```

**Steps**:
1. Calculate exponential delay: `base_delay * (2 ^ (attempt_number - 1))`
2. Cap at maximum: `min(exponential_delay, max_delay)`
3. Add jitter: `random.uniform(-jitter_range, jitter_range) * capped_delay`
4. Ensure non-negative: `max(0.0, final_delay)`

**Example Backoff Sequence** (base=1.0s, max=60.0s, jitter=0.2):
- Attempt 1: Immediate (0.0s)
- Attempt 2: ~1.6-2.4s (2.0s ± 20%)
- Attempt 3: ~3.2-4.8s (4.0s ± 20%)
- Attempt 4: ~6.4-9.6s (8.0s ± 20%)
- Attempt 5: ~12.8-19.2s (16.0s ± 20%)
- Attempt 6: ~25.6-38.4s (32.0s ± 20%)
- Attempt 7+: ~48.0-60.0s (capped at 60.0s ± 20%)

##### Rate Limit Handling

**Special Backoff for Rate Limits**:
- Uses separate `rate_limit_base_delay` (default: 5.0s) and `rate_limit_max_delay` (default: 300.0s)
- Longer delays to respect rate limits (5 minutes max)
- Same exponential formula applies

**Rate Limit Backoff Sequence** (base=5.0s, max=300.0s, jitter=0.2):
- Attempt 1: Immediate (0.0s)
- Attempt 2: ~8.0-12.0s (10.0s ± 20%)
- Attempt 3: ~16.0-24.0s (20.0s ± 20%)
- Attempt 4: ~32.0-48.0s (40.0s ± 20%)
- Attempt 5: ~64.0-96.0s (80.0s ± 20%)
- Attempt 6: ~128.0-192.0s (160.0s ± 20%)
- Attempt 7+: ~240.0-300.0s (capped at 300.0s ± 20%)

**Retry-After Header Support**: If API returns `Retry-After` header, uses that value directly (no calculation, no jitter).

##### Retry Budget Management

**Purpose**: Ensure retries don't exceed overall timeout budget

**Budget Calculation**:
```
retry_cost = backoff_delay + estimated_attempt_time + safety_margin
remaining_budget = overall_timeout - elapsed_time
```

**Check**: `retry_cost <= remaining_budget`

**Functions**:
- `_check_retry_budget()`: Validates if retry is allowed within budget
- `_estimate_attempt_time()`: Estimates time for retry attempt (uses previous attempt duration or per-page timeout)

**Behavior**:
- If budget allows: Retry with calculated backoff
- If budget exceeded: Fail immediately with `TimeoutError` (no retry)
- Safety margin: 5.0 seconds (default) to account for timing variations

##### Configuration

**Environment Variables** (in `.env`):

```bash
# Retry Configuration
OCR_MAX_RETRIES=3                    # Max retry attempts per page (default: 3)
OCR_RETRY_BASE_DELAY=1.0             # Base delay in seconds (default: 1.0)
OCR_RETRY_MAX_DELAY=60.0             # Max delay in seconds (default: 60.0)
OCR_RETRY_JITTER_RANGE=0.2           # Jitter range 0.0-1.0 (default: 0.2 = 20%)

# Rate Limit Configuration
OCR_RATE_LIMIT_BASE_DELAY=5.0        # Rate limit base delay (default: 5.0)
OCR_RATE_LIMIT_MAX_DELAY=300.0       # Rate limit max delay (default: 300.0 = 5 min)
```

**Configuration Loading**:
- Loaded in `backend/config.py` (centralized)
- Passed to `run_ocr_on_pdf()` function
- Available as function parameters with defaults

##### Logging and Metrics

**Per-Page Retry Statistics**:
- `total_attempts`: Total retry attempts for this page
- `successful_retries`: Whether page succeeded after retry
- `exhausted_retries`: Whether all retries were exhausted
- `rate_limit_events`: Number of rate limit errors
- `non_retryable_errors`: Non-retryable errors encountered
- `budget_exceeded`: Whether retry budget was exceeded
- `retry_attempts_by_category`: Breakdown by error category

**Aggregate Retry Statistics** (across all pages):
- `total_retry_attempts`: Total attempts across all pages
- `successful_retries`: Pages that succeeded after retry
- `retry_success_rate_percent`: Percentage of retries that succeeded
- `exhausted_retries`: Pages where retries were exhausted
- `rate_limit_events`: Total rate limit events
- `non_retryable_errors`: Total non-retryable errors
- `budget_exceeded`: Total budget exceeded events
- `retry_attempts_by_category`: Aggregate breakdown by category

**Log Events**:
- `ocr_retry_attempt`: Individual retry attempt (page, attempt number, error category, wait time)
- `ocr_retry_success`: Successful retry (page, attempt number, total attempts, duration)
- `ocr_retry_exhausted`: All retries exhausted (page, attempts, error category)
- `ocr_non_retryable`: Non-retryable error detected (page, error category)
- `ocr_rate_limit`: Rate limit detected (page, retry-after, wait time)
- `ocr_retry_budget_exceeded`: Retry budget exceeded (page, attempt, elapsed time, budget)
- `ocr_retry_stats`: Summary statistics for entire job

**Metadata Enhancement**:
- Retry statistics included in `run_ocr_on_pdf()` return value
- Available in `metadata.retry_statistics` field
- Includes all aggregate statistics and category breakdown

**Example Log Output**:
```
[INFO] request=abc123 ocr_retry_attempt page=5 attempt=2/3 error_category=timeout waiting_s=2.1
[INFO] request=abc123 ocr_retry_success page=5 attempt=2/3 total_attempts=2 duration_ms=4500
[INFO] request=abc123 ocr_retry_stats total_attempts=5 successful_retries=3 retry_success_rate_pct=60.0 exhausted=1 rate_limits=2 non_retryable=0 budget_exceeded=0 categories={"timeout":2,"rate_limit":2,"network_error":1}
```

**See Also**: 
- [Retry Policy](./RETRY_POLICY.md) for official retry policy definition
- [Error Classification Implementation](./ERROR_CLASSIFICATION_IMPLEMENTATION.md) for error classification details
- [Backoff Calculation Implementation](./BACKOFF_CALCULATION_IMPLEMENTATION.md) for backoff formula details
- [Timeout Integration Implementation](./TIMEOUT_INTEGRATION_IMPLEMENTATION.md) for retry budget management
- [Retry Wrapper Implementation](./RETRY_WRAPPER_IMPLEMENTATION.md) for retry wrapper function
- [Logging and Metrics Implementation](./LOGGING_AND_METRICS_IMPLEMENTATION.md) for logging details
- [Configuration Implementation](./CONFIGURATION_IMPLEMENTATION_SUMMARY.md) for configuration details

---

#### Progress Tracking

The OCR system includes comprehensive progress tracking to provide real-time feedback during processing.

**Purpose**: Expose page-level progress and clear messaging for long-running OCR jobs.

**Implementation**: `OCRProgressTracker` class in `backend/ocr/progress_tracker.py`

##### Features

- **File-based Storage**: Progress stored in JSON files (`logs/progress_{request_id}.json`)
- **Thread-safe Operations**: Safe for concurrent access
- **Automatic Cleanup**: Progress files deleted 5 seconds after completion
- **Never Fails Pipeline**: Errors handled silently, never break processing

##### Progress Updates

Progress is updated throughout the 11-step pipeline:

1. **Step 1: Convert PDF** (5%) - Converting PDF pages to images
2. **Step 2: OCR Processing** (15-45%) - Running OCR on PDF pages
   - Page-level updates: "Processing page X of Y..."
   - Details include `pages_completed` and `total_pages`
3. **Step 3: Detect sections** (50%) - Detecting sections and headings
4. **Step 4: Load rubric** (55%) - Loading subject rubric
5. **Step 5: Subject grading** (60%) - Grading with subject rubric
6. **Step 6: Render report** (70%) - Rendering subject report pages
7. **Step 7: Load refined rubric** (75%) - Loading refined rubric
8. **Step 8: Refined annotations** (80%) - Generating refined annotations
9. **Step 9: Page suggestions** (85%) - Generating page-wise suggestions
10. **Step 10: Annotate pages** (90%) - Annotating answer pages
11. **Step 11: Write PDF** (95%) - Writing final PDF
12. **Complete** (100%) - Evaluation complete

##### Progress Data Structure

```json
{
  "request_id": "192ebe95",
  "step": "OCR Processing",
  "step_number": 2,
  "total_steps": 11,
  "progress_percent": 31.7,
  "message": "Processing page 5 of 9...",
  "details": {
    "pages_completed": 5,
    "total_pages": 9
  },
  "timestamp": 1703568000.0,
  "updated_at": "2025-12-26T03:20:00Z"
}
```

##### API Endpoint

**GET `/api/ocr/progress/{request_id}`**:
- Returns current progress for a request
- Returns 404 if progress not found
- Used by frontend for polling

##### Integration

- Progress tracker initialized in `service.py` for synchronous processing
- Progress tracker initialized in `routes/ocr.py` for async job processing
- Progress updates throughout `grade_pdf_answer.py` pipeline
- Page-level updates during OCR processing in `run_ocr_on_pdf()`

**See Also**: 
- [Progress Reporting Implementation](./PROGRESS_REPORTING_IMPLEMENTATION.md) for detailed documentation

---

#### Job Management

The OCR system includes async background job processing to decouple OCR from HTTP requests.

**Purpose**: Enable instant API responses, better scalability, and improved user experience.

**Implementation**: `OCRJobManager` class in `backend/ocr/job_manager.py`

##### Features

- **File-based Persistence**: Jobs stored in JSON files (`logs/jobs/job_{job_id}.json`)
- **Thread-safe Tracking**: Safe for concurrent job management
- **Job Cancellation**: Cancel running jobs
- **Result Storage**: Store job results for retrieval
- **Automatic Cleanup**: Old jobs cleaned up automatically

##### Job Lifecycle

1. **Pending**: Job created, not started
2. **Running**: Job processing in background
3. **Completed**: Job finished successfully
4. **Failed**: Job failed with error
5. **Cancelled**: Job was cancelled

##### Job Data Structure

```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "request_id": "192ebe95",
  "user_id": "user_123",
  "filename": "document.pdf",
  "subject": "current-affairs",
  "status": "running",
  "created_at": 1703568000.0,
  "started_at": 1703568001.0,
  "completed_at": null,
  "error": null,
  "result_pdf_path": null,
  "result_json_path": null,
  "cancelled": false
}
```

##### API Endpoints

**POST `/api/ocr/submit`**:
- Submit job for background processing
- Returns job ID immediately
- Stores input PDF, initializes progress, starts background thread

**GET `/api/ocr/job/{job_id}`**:
- Get job status
- Returns job information and current status

**POST `/api/ocr/job/{job_id}/cancel`**:
- Cancel running job
- Sets cancellation flag, stops processing

**GET `/api/ocr/job/{job_id}/result`**:
- Get job results (PDF and metadata)
- Only works for completed jobs

##### Integration

- Job processing function: `process_ocr_job()` in `service.py`
- Integrates with progress tracking
- Handles cancellation checks
- Stores results for retrieval

##### File Storage

- **Input PDFs**: `logs/results/input_{job_id}.pdf` (stored during submission)
- **Result PDFs**: `logs/results/result_{job_id}.pdf` (generated during processing)
- **Result JSONs**: `logs/results/result_{job_id}.json` (generated during processing)
- **Job Files**: `logs/jobs/job_{job_id}.json` (job status and metadata)

##### Race Condition Fixes

**File Write Safety**:
- File flush and fsync to ensure write to disk
- File existence verification before job submission
- Small delay (100ms) before starting background thread
- Retry logic in background thread (5 attempts, 200ms delay)

**Progress Initialization**:
- Progress tracker initialized immediately when job is submitted
- Ensures progress is available for polling right away
- No more 404 errors on initial progress polls

**See Also**: 
- [Async Background Jobs Implementation](./ASYNC_BACKGROUND_JOBS_IMPLEMENTATION.md) for detailed documentation
- [Progress Endpoint 404 Fix](./PROGRESS_ENDPOINT_404_FIX.md) for progress endpoint fixes

---

### `annotate_pdf_with_rubric.py`

**Location**: `backend/ocr/annotate_pdf_with_rubric.py`

**Purpose**: PDF annotation with rubric-based feedback.

**Key Functions**:

- `annotate_pdf_answer_pages()`: Main annotation function with memory-efficient processing
- `_get_available_memory_mb()`: System memory monitoring
- `_get_process_memory_mb()`: Process memory monitoring
- `_estimate_memory_requirements()`: Memory requirement estimation
- `_check_memory_before_processing()`: Pre-processing memory validation

**Features**:

- PDF annotation with rubric-based feedback
- **Memory-Efficient Processing**: Pages processed one at a time to reduce peak memory usage
- **Memory Monitoring**: Proactive memory checks before and during processing
- **Graceful Failure**: Clear error messages when memory is insufficient
- Visual feedback overlay
- Score display
- Section-based annotation
- Page-wise improvement suggestions

#### Memory Management

The annotation system includes comprehensive memory management to prevent `MemoryError` failures:

**Solution 1: Process Pages One at a Time**:

- Pages are loaded and processed individually (not all at once)
- Memory is explicitly released after each page (`del` + `gc.collect()`)
- Early cleanup of `pix` and `img_bytes` after loading

**Solution 2: Image Downscaling**:

- Automatic downscaling for images exceeding 4000 pixels in any dimension
- Downscaling happens **BEFORE** memory-intensive operations (color conversion)
- Uses LANCZOS4 interpolation for high-quality downscaling
- Prevents allocation failures in `cv2.cvtColor()` and `Image.fromarray()`

**Solution 3: Optimized Color Conversion**:

- Uses `cv2.cvtColor()` instead of array slicing (`[:, :, ::-1]`)
- More memory-efficient (optimized in C)
- Avoids creating unnecessary copies

**Solution 4: Explicit Memory Management**:

- Explicitly deletes intermediate arrays immediately after use
- Calls `gc.collect()` after each page
- Frees memory before processing next page
- Prevents accumulation of all page images in memory
- Reduces peak memory usage by ~60-70%

**Solution 5: Memory Monitoring**:

- Pre-processing memory check validates available system memory
- Estimates memory requirements based on page count and PDF size
- Fails gracefully with clear error messages if memory is insufficient
- Periodic memory monitoring during processing (every 5 pages)
- Warns when memory is getting low

**Memory Check Functions**:

```python
# Check available system memory
available_mb = _get_available_memory_mb()

# Check current process memory usage
process_mb = _get_process_memory_mb()

# Estimate memory requirements
estimated_mb = _estimate_memory_requirements(page_count, pdf_size_mb)

# Pre-processing validation
should_proceed, message = _check_memory_before_processing(page_count, pdf_size_mb)
```

**Dependencies**:

- `psutil`: System and process memory monitoring (added to `requirements.txt`)

**Error Handling**:

- Memory errors are caught and reported with clear messages
- Processing fails gracefully if memory is insufficient
- Warnings logged when memory is getting low

**See Also**: 
- [Memory Monitoring Implementation](./MEMORY_MONITORING_IMPLEMENTATION.md) for detailed documentation
- [Memory Error Fixes Changelog](./CHANGELOG_MEMORY_FIXES.md) for complete memory management improvements
- [Memory Error Annotation Fix](./MEMORY_ERROR_ANNOTATION_FIX.md) for initial fix details
- [Memory Error cv2.cvtColor Fix](./MEMORY_ERROR_CVTCOLOR_FIX.md) for color conversion fix
- [Issue #7 Solutions](../Documents/ISSUE_7_MEMORY_ERROR_SOLUTIONS.md) for problem analysis

---

### Rubrics

**Location**: `backend/ocr/20marks_Rubrics/`

**Purpose**: Subject-specific rubrics for evaluation.

**Available Subjects**:

- Political Science
- History (British, European, Indo-Pak, Islamic, US)
- Law (Constitutional, International)
- Social Sciences (Sociology, Psychology, Anthropology)
- And more...

**Format**: Word documents (.docx) with rubric criteria.

---

## Memory Management

### `short_term.py`

**Location**: `backend/memory/short_term.py`

**Purpose**: Short-term in-memory conversation state.

#### Class: `ShortTermMemory`

**Initialization**:

```python
memory = ShortTermMemory(
    window_size=10,
    summarization_threshold=5
)
```

**Features**:

- Uses LangGraph's `InMemoryStore`
- Session-based organization
- Conversation count tracking
- Summarization triggers

#### Methods

##### `get_store(user_id, session_id)`

Get or create memory store for session.

**Returns**: `InMemoryStore`

##### `add_message(user_id, session_id, message)`

Add message to short-term memory.

**Parameters**:

- `message` (dict): Message dictionary

##### `get_recent_messages(user_id, session_id)`

Get recent messages from memory.

**Returns**: `List[dict]` - List of recent messages

##### `should_summarize(user_id, session_id)`

Check if conversation should be summarized.

**Returns**: `bool` - True if summarization needed

##### `reset_conversation_count(user_id, session_id)`

Reset conversation count after summarization.

##### `clear(user_id, session_id)`

Clear memory for a session.

**Usage**:

```python
memory = ShortTermMemory()

# Add message
memory.add_message(
    user_id="user_123",
    session_id="session_456",
    message={"role": "user", "content": "Hello"}
)

# Get recent messages
messages = memory.get_recent_messages("user_123", "session_456")

# Check if should summarize
if memory.should_summarize("user_123", "session_456"):
    # Trigger summarization
    pass
```

---

### `long_term.py`

**Location**: `backend/memory/long_term.py`

**Purpose**: Long-term persistent memory in Supabase.

#### Class: `LongTermMemory`

**Initialization**:

```python
memory = LongTermMemory()
```

**Features**:

- Supabase-backed storage
- Conversation summarization
- User ID normalization
- Fact storage

#### Methods

##### `save_fact(user_id, session_id, context, fact)`

Save a fact or context snippet.

**Parameters**:

- `context` (str): Context description
- `fact` (str): Fact to save

**Returns**: Database record

##### `save_conversation_summary(user_id, session_id, messages, context)`

Save conversation summary.

**Parameters**:

- `messages` (List[Dict]): Conversation messages
- `context` (str): Context description

**Returns**: Database record

##### `get_memory(user_id, session_id, context)`

Retrieve memory for context.

**Returns**: `List[Dict]` - Memory records

**Usage**:

```python
memory = LongTermMemory()

# Save fact
memory.save_fact(
    user_id="user_123",
    session_id="session_456",
    context="user_preferences",
    fact="Prefers detailed explanations"
)

# Save conversation summary
await memory.save_conversation_summary(
    user_id="user_123",
    session_id="session_456",
    messages=[...],
    context="chat"
)

# Retrieve memory
memories = memory.get_memory("user_123", "session_456", "chat")
```

---

### `conversation_summarizer.py`

**Location**: `backend/memory/conversation_summarizer.py`

**Purpose**: Intelligent conversation summarization.

**Features**:

- Summarizes conversations after N exchanges
- Maintains context quality
- Reduces storage by 95-99%
- Uses LLM for summarization

**Usage**:

```python
from backend.memory.conversation_summarizer import get_conversation_summarizer

summarizer = get_conversation_summarizer()
summary = await summarizer.summarize(messages)
```

---

## RAG System

### Overview

The RAG (Retrieval Augmented Generation) system provides document retrieval and context augmentation.

### Components

#### `adapters/`

**Location**: `backend/rag/adapters/`

**Purpose**: Storage adapters for RAG.

- `base.py`: Base adapter interface
- `supabase_store.py`: Supabase storage adapter

#### `llm/`

**Location**: `backend/rag/llm/`

**Purpose**: LLM clients for RAG.

- `streaming_client.py`: Streaming LLM client
- `groq_httpx.py`: Groq HTTP client
- `providers.py`: LLM provider abstraction

#### `memory/`

**Location**: `backend/rag/memory/`

**Purpose**: Memory components for RAG.

- `cache.py`: Embedding cache
- `context_state.py`: Context state management
- `dedupe.py`: Deduplication logic
- `embedding_cache.py`: Embedding caching

#### `planning/`

**Location**: `backend/rag/planning/`

**Purpose**: Query planning and decomposition.

- `dependency_tracker.py`: Dependency tracking
- `subquestion_generator.py`: Sub-question generation

#### `reasoning/`

**Location**: `backend/rag/reasoning/`

**Purpose**: Multi-step reasoning.

- `graph_controller.py`: Reasoning graph controller
- `synthesizer.py`: Response synthesis
- `validator.py`: Response validation

#### `retrieval/`

**Location**: `backend/rag/retrieval/`

**Purpose**: Document retrieval.

- `bm25.py`: BM25 retrieval
- `hybrid_retriever.py`: Hybrid retrieval (BM25 + embeddings)

#### `telemetry/`

**Location**: `backend/rag/telemetry/`

**Purpose**: Monitoring and tracing.

---

## Database Services

### `supabase_service.py`

**Location**: `backend/db/supabase_service.py`

**Purpose**: Service layer for Supabase database operations.

#### Class: `SupabaseService`

**Initialization**:

```python
service = SupabaseService(
    supabase_url="https://...",
    supabase_key="..."
)
```

#### Book Operations

##### `create_book(book_data)`

Create a new book record.

##### `get_book_by_id(book_id)`

Get book by ID.

##### `get_books_by_genre(genre)`

Get books by genre.

##### `get_books_by_ids(book_ids)`

Get multiple books by IDs.

#### Document Chunk Operations

##### `create_chunks(chunks)`

Create multiple document chunks.

##### `get_chunks_by_book_id(book_id)`

Get chunks for a book.

#### Conversation Operations

##### `create_conversation(conversation_data)`

Create a new conversation.

##### `get_conversation_by_id(conversation_id)`

Get conversation by ID.

##### `get_conversations_by_user_id(user_id, limit, offset)`

Get conversations for a user.

##### `update_conversation(conversation_id, updates)`

Update conversation.

##### `delete_conversation(conversation_id)`

Delete conversation.

#### Message Operations

##### `create_message(message_data)`

Create a message.

##### `get_messages_by_conversation_id(conversation_id)`

Get messages for a conversation.

##### `update_message(message_id, updates)`

Update message.

#### User Operations

##### `get_valid_user_id(user_id)`

Normalize and validate user ID.

**Usage**:

```python
service = SupabaseService(url, key)

# Create conversation
conversation = await service.create_conversation({
    "user_id": "user_123",
    "title": "My Chat",
    "is_pinned": False
})

# Get conversations
conversations = await service.get_conversations_by_user_id(
    user_id="user_123",
    limit=10,
    offset=0
)

# Create message
message = await service.create_message({
    "conversation_id": conversation["id"],
    "user_prompt": "Hello",
    "llm_response": "Hi there!"
})
```

---

### `storage.py`

**Location**: `backend/db/storage.py`

**Purpose**: File storage service for PDFs and documents.

#### Class: `StorageService`

**Methods**:

- `upload_pdf_and_get_signed_url()`: Upload PDF and get signed URL
- `delete_file()`: Delete file from storage

**Usage**:

```python
from backend.db.storage import StorageService

storage = StorageService()
url = storage.upload_pdf_and_get_signed_url(
    user_id="user_123",
    original_stem="answer",
    data=pdf_bytes
)
```

---

### `models.py`

**Location**: `backend/db/models.py`

**Purpose**: Pydantic models for data validation.

**Models**:

- `User`: User model
- `Book`: Book model
- `DocumentChunk`: Document chunk model
- `Conversation`: Conversation model
- `ConversationMessage`: Message model
- `Usage`: Usage tracking model

---

## Utilities

### `logging_config.py`

**Location**: `backend/utils/logging_config.py`

**Purpose**: Centralized logging configuration.

**Functions**:

- `setup_logging()`: Configure logging
- `get_logger()`: Get logger instance
- `log_supabase_request()`: Log Supabase requests
- `log_supabase_response()`: Log Supabase responses

**Usage**:

```python
from backend.utils.logging_config import get_logger

logger = get_logger(__name__)
logger.info("Message")
logger.error("Error message")
```

---

### `grok_client.py`

**Location**: `backend/utils/grok_client.py`

**Purpose**: Grok API client for OCR evaluation.

**Features**:

- API communication
- Error handling
- Request/response logging

---

### `pdf_utils.py`

**Location**: `backend/utils/pdf_utils.py`

**Purpose**: PDF processing utilities.

**Functions**:

- PDF text extraction
- PDF manipulation
- Page operations

---

### `pdf_renderer.py`

**Location**: `backend/utils/pdf_renderer.py`

**Purpose**: PDF rendering utilities.

**Features**:

- PDF generation
- Annotation rendering
- Visual feedback overlay

---

### `rubric_loader.py`

**Location**: `backend/utils/rubric_loader.py`

**Purpose**: Load rubrics from Word documents.

**Functions**:

- `load_rubric()`: Load rubric for subject
- `list_available_subjects()`: List available subjects

---

### `rubric_parser.py`

**Location**: `backend/utils/rubric_parser.py`

**Purpose**: Parse rubric documents.

**Features**:

- Document parsing
- Criteria extraction
- Structure analysis

---

### `rubric_evaluator.py`

**Location**: `backend/utils/rubric_evaluator.py`

**Purpose**: Evaluate answers against rubrics.

**Features**:

- Score calculation
- Feedback generation
- Criteria matching

---

### `report_builder_new.py`

**Location**: `backend/utils/report_builder_new.py`

**Purpose**: Generate evaluation reports.

**Features**:

- Report generation
- Score visualization
- Feedback formatting

---

### `usage_tracking.py`

**Location**: `backend/utils/usage_tracking.py`

**Purpose**: Usage tracking utilities.

**Features**:

- Token counting
- Usage recording
- Limit checking

---

## Middleware

### `logging_middleware.py`

**Location**: `backend/middleware/logging_middleware.py`

**Purpose**: API request/response logging middleware.

**Features**:

- Request logging
- Response logging
- Error logging
- Performance tracking

**Usage**: Automatically applied in `main.py`

---

## Best Practices

### Module Organization

1. **Single Responsibility**: Each module has one clear purpose
2. **Dependency Injection**: Services injected via constructors
3. **Error Handling**: Comprehensive error handling
4. **Logging**: All modules use centralized logging
5. **Type Hints**: Type hints for all functions

### Testing

- Write unit tests for each module
- Mock external dependencies
- Test error cases
- Use pytest for testing

---

**Last Updated**: 2025
