# NotebookLM Backend – Detailed Guide

A modular backend for an agentic book chatbot platform, featuring advanced RAG-based chat with intelligent conversation summarization. Built with FastAPI, Supabase, and LangGraph.

---

## Table of Contents
- [Features](#features)
- [Requirements](#requirements)
- [Environment Variables](#environment-variables)
- [Supabase Table Setup](#supabase-table-setup)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [API Usage](#api-usage)
  - [JWT Authentication](#jwt-authentication)
  - [User & Session](#user--session)
  - [Chatbot](#chatbot)
  - [Books & Genres](#books--genres)
- [Performance Features](#performance-features)
- [Troubleshooting](#troubleshooting)
- [Directory Structure](#directory-structure)

---

## Features
- Advanced chatbot agent with RAG pipeline and multi-step reasoning
- Intelligent conversation summarization (auto-summarizes after 5 exchanges)
- Short-term memory (LangGraph InMemoryStore) and long-term memory (Supabase)
- Performance optimizations with caching and parallel processing
- LangSmith tracing for monitoring and debugging
- JWT authentication for all endpoints
- Modular, scalable, and well-documented codebase

## Requirements
- Python 3.13+
- Docker (for containerized deployment)
- Supabase project (credentials via environment variables)

## Environment Variables
Set these in a `.env` file or as Docker/container environment variables:
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_KEY`: Your Supabase service role key
- `JWT_SECRET_KEY`: Secret key for JWT authentication (choose a strong value)

## Supabase Table Setup
Create these tables in your Supabase project (see `backend/db/models.py` for field suggestions):
- `users`, `books`, `chat_messages`, `document_chunks`, `sessions`, `long_term_memory`

## Local Development
1. **Clone the repository**
   ```sh
   git clone <repo-url>
   cd notebookLM_backend
   ```
2. **Install dependencies**
   ```sh
   pip install -r requirements.txt
   ```
3. **Configure environment variables**
   - Create a `.env` file or set env vars in your shell:
     ```sh
     export SUPABASE_URL=your_url
     export SUPABASE_KEY=your_key
     export JWT_SECRET_KEY=your_secret
     ```
4. **Run the app**
   ```sh
   uvicorn backend.main:app --reload
   ```
5. **Access API docs**
   - Open [http://localhost:8000/docs](http://localhost:8000/docs) for Swagger UI.

## Docker Deployment
1. **Build the Docker image**
   ```sh
   docker build -t notebooklm-backend .
   ```
2. **Run the container**
   ```sh
   docker run -d -p 8000:8000 \
     -e SUPABASE_URL=your_url \
     -e SUPABASE_KEY=your_key \
     -e JWT_SECRET_KEY=your_secret \
     notebooklm-backend
   ```

---

## API Usage
All endpoints (except `/user/token`) require a valid JWT Bearer token in the `Authorization` header.

### JWT Authentication
1. **Obtain a JWT token**
   - Use the `/user/token` endpoint:
     ```http
     POST /user/token
     Content-Type: application/json
     {
       "user_id": "your_user_id"
     }
     ```
   - Response:
     ```json
     {
       "access_token": "<JWT_TOKEN>",
       "token_type": "bearer"
     }
     ```
2. **Use the token**
   - Add to all requests:
     ```http
     Authorization: Bearer <JWT_TOKEN>
     ```

### User & Session
- `POST /user/session/create` – Create a new session
- `GET /user/session/{id}` – Get session info

### Chatbot
- `POST /chatbot/ask` – Ask a question (requires `user_id`, `session_id`, `question`, `genre`)



### Books & Genres
- `GET /books/genres` – List genres
- `GET /books/{genre}` – List books by genre
- `POST /ingest/upload` – Upload and process new books

---

## Performance Features

### Conversation Summarization
- Automatically summarizes conversations after 5 exchanges
- Stores intelligent summaries instead of raw messages
- 95-99% storage reduction for long conversations
- Maintains context quality while improving performance

### RAG Optimizations
- Multi-step reasoning with parallel processing
- Embedding caching for faster retrieval
- Early stopping when sufficient evidence is found
- Adaptive mode that balances speed vs quality
- LangSmith tracing for performance monitoring

### Configuration
```env
# Performance settings
USE_ADAPTIVE_RAG=true
LANGSMITH_TRACING=true
ENABLE_CACHE=true
MAX_ITERATIONS=2
TOP_K=5
```

---

## Troubleshooting
- **Supabase errors**: Ensure all required tables exist and credentials are correct.
- **JWT errors**: Check your `JWT_SECRET_KEY` and token validity.
- **CORS**: FastAPI allows CORS configuration if needed for frontend.
- **API not reachable**: Ensure port 8000 is open and not blocked by firewall.

## Directory Structure
```
backend/
  agents/
    chatbot_agent.py

  memory/
    short_term.py
    long_term.py
  db/
    models.py
    supabase_client.py
  api/
    routes/
      chatbot.py
      users.py
      books.py
      ingest.py
      auth.py
  main.py
  config.py
  requirements.txt
  Dockerfile
  README_backend.md
```

---

**For more, see the OpenAPI docs at `/docs` after running the backend!**
