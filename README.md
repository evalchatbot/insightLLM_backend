# NotebookLM Backend

A modular backend for an agentic book chatbot platform, featuring advanced RAG-based chat with intelligent conversation summarization. Built with FastAPI, Supabase, and LangGraph.

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
- `SUPABASE_URL`: Your Supabase project URL
- `SUPABASE_KEY`: Your Supabase service role key
- `JWT_SECRET_KEY`: Secret key for JWT authentication

## Setup (Local)
1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Configure environment variables (see `config.py` or use a `.env` file)
4. Run the app: `uvicorn backend.main:app --reload`

## Deployment (Docker)
1. Build the image:
   ```sh
   docker build -t notebooklm-backend .
   ```
2. Run the container (set env vars as needed):
   ```sh
   docker run -d -p 8000:8000 \
     -e SUPABASE_URL=your_url \
     -e SUPABASE_KEY=your_key \
     -e JWT_SECRET_KEY=your_secret \
     notebooklm-backend
   ```

## API Documentation
- Interactive OpenAPI docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- Redoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

## Supabase Table Requirements
You must create the following tables in your Supabase project:
- `users`, `books`, `chat_messages`, `document_chunks`, `sessions`, `long_term_memory`
- See `backend/db/models.py` for field suggestions.
- For conversation summarization, add `content_type`, `metadata`, `created_at`, `archived_at` columns to `long_term_memory`

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
  README.md
```

---

**Start vibing with your books!**
