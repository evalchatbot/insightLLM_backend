# Backend API Routes Documentation

This document provides detailed documentation for all FastAPI routes in the backend.

---

## Table of Contents

1. [Authentication Routes](#authentication-routes)
2. [Chatbot Routes](#chatbot-routes)
3. [OCR Routes](#ocr-routes)
4. [Conversation Routes](#conversation-routes)
5. [User Routes](#user-routes)
6. [Book Routes](#book-routes)
7. [Quiz Routes](#quiz-routes)
8. [Ingest Routes](#ingest-routes)
9. [Assistant Routes](#assistant-routes)
10. [Error Handling](#error-handling)

---

## Authentication Routes

### `POST /user/token`

**Location**: `backend/api/routes/auth.py`

**Purpose**: Generate JWT token for authentication.

**Authentication**: Not required (public endpoint)

**Request Body**:

```json
{
  "user_id": "string"
}
```

**Response**:

```json
{
  "access_token": "string",
  "token_type": "bearer"
}
```

**Usage**:

```python
import requests

response = requests.post(
    "http://localhost:8000/user/token",
    json={"user_id": "user_123"}
)
token = response.json()["access_token"]
```

---

## Chatbot Routes

### `POST /chatbot/ask`

**Location**: `backend/api/routes/chatbot.py`

**Purpose**: Non-streaming chatbot query with memory updates.

**Authentication**: Not required (public endpoint)

**Request Body**:

```json
{
  "user_id": "string",
  "session_id": "string",
  "question": "string",
  "genre": "string (optional, default: 'general')",
  "book_ids": ["string"] (optional),
  "conversation_id": "string (optional)"
}
```

**Response**:

```json
{
  "answer": "string",
  "sources": [],
  "citations": [],
  "context": [],
  "metadata": {
    "mode": "single_llm",
    "system_prompt": "css-pol-sci.v3",
    "context_messages": 0,
    "response_time": 1.234,
    "question_analysis": {},
    "token_usage": {}
  }
}
```

**Features**:

- Maintains conversation context
- Updates short-term and long-term memory
- Returns metadata about the response
- CSS/PMS-focused system prompt

**Usage**:

```python
response = requests.post(
    "http://localhost:8000/chatbot/ask",
    json={
        "user_id": "user_123",
        "session_id": "session_456",
        "question": "What is the structure of CSS exam?",
        "genre": "general"
    }
)
answer = response.json()["answer"]
```

---

### `POST /chatbot/ask-multi`

**Location**: `backend/api/routes/chatbot.py`

**Purpose**: Multi-step chatbot query (backwards compatibility).

**Authentication**: Not required

**Request Body**: Same as `/chatbot/ask`

**Response**: Same as `/chatbot/ask`

**Note**: Currently delegates to standard `ask()` method.

---

### `POST /chatbot/stream`

**Location**: `backend/api/routes/chatbot.py`

**Purpose**: Streaming chatbot response.

**Authentication**: Not required

**Request Body**: Same as `/chatbot/ask`

**Response**: Streaming text response (Server-Sent Events)

**Features**:

- Real-time token streaming
- Maintains conversation context
- Updates memory after completion

**Usage**:

```python
import requests

response = requests.post(
    "http://localhost:8000/chatbot/stream",
    json={
        "user_id": "user_123",
        "session_id": "session_456",
        "question": "Explain CSS exam structure"
    },
    stream=True
)

for chunk in response.iter_content(chunk_size=None):
    if chunk:
        print(chunk.decode(), end="")
```

---

### `POST /chatbot/stream-multi`

**Location**: `backend/api/routes/chatbot.py`

**Purpose**: Multi-step streaming chatbot response.

**Authentication**: Not required

**Request Body**: Same as `/chatbot/ask`

**Response**: Streaming text response

---

## OCR Routes

### `POST /api/ocr/annotate`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Annotate PDF with AI evaluation and feedback.

**Authentication**: Not required (Clerk migration removed JWT)

**Request**: `multipart/form-data`

- `file`: PDF file (UploadFile)
- `user_id`: User ID (Form field)
- `subject`: Subject name (Form field)

**Response**:

```json
{
  "pdf_base64": "base64_encoded_pdf",
  "pdf_url": "signed_url_to_pdf",
  "metadata": {
    "subject": "string",
    "scores": {},
    "feedback": {},
    "total_marks": 0
  },
  "filename": "annotated_filename.pdf"
}
```

**Features**:

- PDF evaluation using Grok API
- Rubric-based scoring
- Annotated PDF generation
- Storage in Supabase
- Metadata extraction

**Error Responses**:

- `400`: Invalid file format or missing subject
- `413`: File size exceeds limit (default: 50MB)
- `500`: Evaluation failed

**Usage**:

```python
import requests

with open("answer.pdf", "rb") as f:
    files = {"file": f}
    data = {
        "user_id": "user_123",
        "subject": "Political Science"
    }
    response = requests.post(
        "http://localhost:8000/api/ocr/annotate",
        files=files,
        data=data
    )
    result = response.json()
    pdf_base64 = result["pdf_base64"]
```

---

### `POST /api/ocr/annotate/json`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Get evaluation results as JSON only (no PDF).

**Authentication**: Not required

**Request**: Same as `/api/ocr/annotate`

**Response**:

```json
{
  "metadata": {
    "subject": "string",
    "scores": {},
    "feedback": {},
    "total_marks": 0
  }
}
```

**Usage**: Same as `/api/ocr/annotate` but returns JSON only.

---

### `POST /api/ocr/submit`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Submit an OCR job for background processing. Returns job ID immediately.

**Authentication**: Not required (public endpoint)

**Request**: Form data (multipart/form-data)

- `file`: PDF file (required)
- `user_id`: User ID (required)
- `subject`: Subject name (required)

**Response**:

```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "request_id": "192ebe95",
  "status": "pending",
  "message": "Job submitted successfully. Use /api/ocr/job/{job_id} to check status."
}
```

**Features**:
- Returns immediately (< 1 second)
- Stores input PDF for background processing
- Initializes progress tracking
- Submits job to background thread pool

**Usage**:

```python
import requests

with open("document.pdf", "rb") as f:
    response = requests.post(
        "http://localhost:8000/api/ocr/submit",
        files={"file": f},
        data={
            "user_id": "user_123",
            "subject": "current-affairs"
        }
    )
result = response.json()
job_id = result["job_id"]
request_id = result["request_id"]
```

---

### `GET /api/ocr/job/{job_id}`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Get status of an OCR job.

**Authentication**: Not required (public endpoint)

**Path Parameters**:
- `job_id`: Job identifier (required)

**Response**:

```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "request_id": "192ebe95",
  "status": "running",
  "filename": "document.pdf",
  "subject": "current-affairs",
  "created_at": 1703568000.0,
  "started_at": 1703568001.0,
  "completed_at": null,
  "error": null,
  "result_available": false,
  "result_pdf_path": null,
  "result_json_path": null
}
```

**Status Values**:
- `pending`: Job created but not started
- `running`: Job is processing
- `completed`: Job completed successfully
- `failed`: Job failed with error
- `cancelled`: Job was cancelled

**Usage**:

```python
import requests

response = requests.get(
    "http://localhost:8000/api/ocr/job/a1b2c3d4e5f6g7h8"
)
status = response.json()
print(f"Job status: {status['status']}")
```

---

### `POST /api/ocr/job/{job_id}/cancel`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Cancel a running OCR job.

**Authentication**: Not required (public endpoint)

**Path Parameters**:
- `job_id`: Job identifier (required)

**Response**:

```json
{
  "job_id": "a1b2c3d4e5f6g7h8",
  "status": "cancelled",
  "message": "Job cancelled successfully"
}
```

**Usage**:

```python
import requests

response = requests.post(
    "http://localhost:8000/api/ocr/job/a1b2c3d4e5f6g7h8/cancel"
)
result = response.json()
print(result["message"])
```

---

### `GET /api/ocr/job/{job_id}/result`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Get result of a completed OCR job.

**Authentication**: Not required (public endpoint)

**Path Parameters**:
- `job_id`: Job identifier (required)

**Response**:

```json
{
  "pdf_base64": "base64_encoded_pdf_string",
  "metadata": {
    "detected_question": "...",
    "answer_summary": "...",
    "strengths": [...],
    "improvements": [...],
    "final_comments": "...",
    "score": {...},
    "metadata": {...}
  },
  "pdf_url": "/api/ocr/job/a1b2c3d4e5f6g7h8/result/pdf"
}
```

**Note**: Only works for completed jobs. Returns 404 if job not found or not completed.

**Usage**:

```python
import requests
import base64

response = requests.get(
    "http://localhost:8000/api/ocr/job/a1b2c3d4e5f6g7h8/result"
)
result = response.json()

# Decode PDF
pdf_bytes = base64.b64decode(result["pdf_base64"])
with open("result.pdf", "wb") as f:
    f.write(pdf_bytes)

# Access metadata
metadata = result["metadata"]
print(f"Score: {metadata['score']}")
```

---

### `GET /api/ocr/progress/{request_id}`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Get real-time progress for an OCR job.

**Authentication**: Not required (public endpoint)

**Path Parameters**:
- `request_id`: Request identifier (required)

**Response**:

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

**Progress Steps**:
1. Convert PDF (5%)
2. OCR Processing (15-45%) - with page-level updates
3. Detect sections (50%)
4. Load rubric (55%)
5. Subject grading (60%)
6. Render report (70%)
7. Load refined rubric (75%)
8. Refined annotations (80%)
9. Page suggestions (85%)
10. Annotate pages (90%)
11. Write PDF (95%)
12. Complete (100%)

**Usage**:

```python
import requests

response = requests.get(
    "http://localhost:8000/api/ocr/progress/192ebe95"
)
progress = response.json()
print(f"Progress: {progress['progress_percent']}%")
print(f"Step: {progress['step']}")
if progress.get("details", {}).get("pages_completed"):
    print(f"Pages: {progress['details']['pages_completed']}/{progress['details']['total_pages']}")
```

**Note**: Returns 404 if progress not found (job not started or completed > 5 seconds ago).

---

### `GET /api/ocr/subjects`

**Location**: `backend/api/routes/ocr.py`

**Purpose**: Get list of available subjects for evaluation.

**Authentication**: Not required

**Response**:

```json
[
  {
    "value": "Political Science",
    "label": "Political Science"
  },
  {
    "value": "History",
    "label": "History"
  }
]
```

**Usage**:

```python
response = requests.get("http://localhost:8000/api/ocr/subjects")
subjects = response.json()
```

---

## Conversation Routes

### `POST /conversations/new-chat`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Create a new empty chat conversation.

**Authentication**: Required (JWT)

**Request Body**:

```json
{
  "user_id": "string",
  "title": "string (optional, default: 'New Chat')",
  "icon": "string (optional)",
  "is_pinned": false
}
```

**Response**:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "chat_id": "string",
  "title": "string",
  "icon": "string",
  "is_pinned": false,
  "created_at": "iso_timestamp",
  "updated_at": "iso_timestamp"
}
```

**Usage**:

```python
headers = {"Authorization": f"Bearer {token}"}
response = requests.post(
    "http://localhost:8000/conversations/new-chat",
    json={"user_id": "user_123", "title": "My New Chat"},
    headers=headers
)
conversation = response.json()
```

---

### `POST /conversations/`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Create conversation with auto-generated title from first Q&A.

**Authentication**: Required

**Request Body**:

```json
{
  "user_id": "string",
  "question": "string",
  "answer": "string"
}
```

**Response**: Same as `/conversations/new-chat`

**Features**:

- Auto-generates title using chatbot agent
- Creates conversation with first message

---

### `GET /conversations/`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: List all conversations for a user.

**Authentication**: Required

**Query Parameters**:

- `user_id`: User ID (required)
- `limit`: Number of results (optional, default: 50)
- `offset`: Pagination offset (optional, default: 0)

**Response**:

```json
{
  "conversations": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "chat_id": "string",
      "title": "string",
      "icon": "string",
      "is_pinned": false,
      "created_at": "iso_timestamp",
      "updated_at": "iso_timestamp"
    }
  ],
  "total": 10
}
```

**Usage**:

```python
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:8000/conversations/?user_id=user_123&limit=10",
    headers=headers
)
data = response.json()
conversations = data["conversations"]
```

---

### `GET /conversations/{id}`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Get conversation details.

**Authentication**: Required

**Response**: Conversation object

---

### `PUT /conversations/{id}`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Update conversation (title, icon, pin status).

**Authentication**: Required

**Request Body**:

```json
{
  "title": "string (optional)",
  "icon": "string (optional)",
  "is_pinned": false
}
```

**Response**: Updated conversation object

---

### `DELETE /conversations/{id}`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Delete a conversation.

**Authentication**: Required

**Response**: `{"success": true}`

---

### `GET /conversations/{id}/messages`

**Location**: `backend/api/routes/conversations.py`

**Purpose**: Get all messages in a conversation.

**Authentication**: Required

**Response**:

```json
{
  "conversation": {
    "id": "uuid",
    "title": "string",
    ...
  },
  "messages": [
    {
      "id": "uuid",
      "conversation_id": "uuid",
      "user_prompt": "string",
      "llm_response": "string",
      "img_name": "string",
      "created_at": "iso_timestamp",
      "updated_at": "iso_timestamp"
    }
  ]
}
```

---

## User Routes

### `POST /user/session/create`

**Location**: `backend/api/routes/users.py`

**Purpose**: Create a new user session.

**Authentication**: Required

**Request Body**:

```json
{
  "user_id": "string"
}
```

**Response**:

```json
{
  "session_id": "uuid",
  "user_id": "string",
  "created_at": "iso_timestamp"
}
```

---

### `GET /user/session/{id}`

**Location**: `backend/api/routes/users.py`

**Purpose**: Get session information.

**Authentication**: Required

**Response**: Session object

---

## Book Routes

### `GET /books/genres`

**Location**: `backend/api/routes/books.py`

**Purpose**: Get list of available book genres.

**Authentication**: Required

**Response**:

```json
{
  "genres": ["Political Science", "History", "Economics", ...]
}
```

**Usage**:

```python
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:8000/books/genres",
    headers=headers
)
genres = response.json()["genres"]
```

---

### `GET /books/{genre}`

**Location**: `backend/api/routes/books.py`

**Purpose**: Get all books in a specific genre.

**Authentication**: Required

**Response**:

```json
{
  "books": [
    {
      "id": "uuid",
      "title": "string",
      "author": "string",
      "genre": "string",
      "file_url": "string"
    }
  ]
}
```

**Usage**:

```python
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    "http://localhost:8000/books/Political Science",
    headers=headers
)
books = response.json()["books"]
```

---

## Quiz Routes

### `GET /quiz/mcqs`

**Location**: `backend/api/routes/quiz.py`

**Purpose**: Get random MCQ questions for a genre.

**Authentication**: Not required

**Query Parameters**:

- `genre_id`: Genre ID (required)
- `limit`: Number of MCQs (optional, default: 20)

**Response**:

```json
[
  {
    "id": "uuid",
    "question": "string",
    "option_a": "string",
    "option_b": "string",
    "option_c": "string",
    "option_d": "string",
    "correct_answer": "a|b|c|d",
    "genre_id": "string"
  }
]
```

**Features**:

- Random selection of MCQs
- Returns correct answers for frontend grading
- Filters by genre

**Usage**:

```python
response = requests.get(
    "http://localhost:8000/quiz/mcqs?genre_id=pol_sci&limit=10"
)
mcqs = response.json()
```

---

## Ingest Routes

### `POST /ingest/upload`

**Location**: `backend/api/routes/ingest.py`

**Purpose**: Upload and process a document for ingestion.

**Authentication**: Required

**Request**: `multipart/form-data`

- `file`: Document file (PDF, DOCX, etc.)
- `title`: Document title
- `author`: Author name
- `genre`: Genre/category

**Response**:

```json
{
  "book_id": "uuid",
  "title": "string",
  "chunks_created": 100,
  "status": "success"
}
```

**Features**:

- Document parsing and chunking
- Embedding generation
- Storage in database

---

## Assistant Routes

### Assistant Endpoints

**Location**: `backend/api/routes/assistant.py`

**Purpose**: Assistant-related endpoints (if implemented).

**Note**: Check implementation for specific endpoints.

---

## Error Handling

### Standard Error Response Format

```json
{
  "detail": "Error message"
}
```

### HTTP Status Codes

- `200`: Success
- `201`: Created
- `400`: Bad Request (invalid input)
- `401`: Unauthorized (missing/invalid token)
- `404`: Not Found
- `413`: Payload Too Large (file size exceeded)
- `500`: Internal Server Error
- `503`: Service Unavailable

### Common Error Scenarios

#### Authentication Errors

```json
{
  "detail": "Missing Bearer token"
}
```

or

```json
{
  "detail": "Invalid or expired token"
}
```

#### Validation Errors

```json
{
  "detail": "Subject selection is required."
}
```

#### File Errors

```json
{
  "detail": "Only PDF files are supported."
}
```

or

```json
{
  "detail": "File size exceeds 50 MB."
}
```

#### Database Errors

```json
{
  "detail": "Failed to create conversation"
}
```

---

## API Testing

### Using FastAPI Docs

Access interactive API documentation:

- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`

### Using curl

```bash
# Get token
curl -X POST http://localhost:8000/user/token \
  -H "Content-Type: application/json" \
  -d '{"user_id": "user_123"}'

# Use token
curl -X GET http://localhost:8000/conversations/?user_id=user_123 \
  -H "Authorization: Bearer <token>"
```

### Using Python requests

```python
import requests

BASE_URL = "http://localhost:8000"

# Get token
token_response = requests.post(
    f"{BASE_URL}/user/token",
    json={"user_id": "user_123"}
)
token = token_response.json()["access_token"]

# Make authenticated request
headers = {"Authorization": f"Bearer {token}"}
response = requests.get(
    f"{BASE_URL}/conversations/",
    params={"user_id": "user_123"},
    headers=headers
)
```

---

## Rate Limiting

Currently, rate limiting is handled by:

- Frontend usage tracking
- Supabase RPC functions
- Application-level checks

Future enhancements may include:

- Per-endpoint rate limits
- User-tier based limits
- IP-based rate limiting

---

## CORS Configuration

CORS is configured in `main.py`:

- **Allowed Origins**: Frontend URLs (localhost, Vercel)
- **Credentials**: Enabled
- **Methods**: All methods
- **Headers**: All headers

---

**Last Updated**: 2025
