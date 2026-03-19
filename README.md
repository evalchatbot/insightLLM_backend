# Insight LLM Backend

FastAPI backend for CSS/PMS-focused chat, OCR, grading, and annotation workflows.

## Start

```powershell
cd insightLLM_backend
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

## API Docs

- OpenAPI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## Structure

```text
insightLLM_backend/
|- README.md
|- Documents/
|  |- BACKEND_TECHNICAL_NOTES.md
|- backend/
|  |- api/
|  |- db/
|  |- eng_essay/
|  |- ocr/
|  |- scripts/
|  |  |- update_progress_messages.py
|- requirements.txt
```

## Consolidated Documentation

All backend markdown documentation has been consolidated into:

- Documents/BACKEND_TECHNICAL_NOTES.md

This includes previously scattered OCR, grading, deterministic-evaluation, and annotation-fix notes.
