# NotebookLM Backend

A FastAPI backend that powers a Pakistani competitive-exam study companion. The chatbot now uses a single large language model with a robust CSS/PMS-specific system prompt—no vector stores or RAG pipeline required. Conversation memory is still persisted through Supabase.

## Features
- CSS/PMS mentor chatbot with exam-focused system prompt and contextual memory
- Intelligent conversation summarisation (summaries after every 5 turns)
- Short-term memory (LangGraph InMemoryStore) plus long-term Supabase storage
- Optional OCR grading pipeline for annotated PDF feedback
- JWT authentication for private endpoints
- Modular layout with clear logging and configuration hooks

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
You must create (or adapt) the following tables in Supabase:
- `users`, `conversations`, `messages`, `long_term_memory`
- Optional: `books`, `document_chunks` if you keep the ingestion/OCR utilities
- See `backend/db/models.py` for field suggestions and expected columns


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
