import logging
import os
import datetime

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks

from backend.api.routes import (
    assistant,
    books,
    chatbot,
    conversations,
    factbook,
    ingest,
    ocr,
    users,
    quiz,
    essay,
    ocr_regular,
)
from backend.api.routes import outline as outline_route
from backend.api.routes import precis as precis_route
from backend.utils.rubric_loader import list_subject_rubrics, list_available_subjects
from backend.api.routes.auth import get_current_user
from backend.middleware.logging_middleware import setup_api_logging
from backend.utils.logging_config import setup_logging

log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs", "insightllm.log")
setup_logging(os.getenv("LOG_LEVEL", "INFO"), log_file)

logger = logging.getLogger(__name__)

app = FastAPI(title="NotebookLM Backend", version="0.1.0")


class EndpointFilter(logging.Filter):
    def filter(self, record):
        return record.getMessage().find("/_debug/headers") < 0


logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_api_logging(app)

app.include_router(assistant.router)
app.include_router(books.router)
app.include_router(chatbot.router)
app.include_router(conversations.router)
app.include_router(factbook.router)
app.include_router(ingest.router)
app.include_router(ocr.router)
app.include_router(users.router)
app.include_router(quiz.router)
app.include_router(essay.router)
app.include_router(ocr_regular.router)
app.include_router(outline_route.router)
app.include_router(precis_route.router)


@app.get("/")
async def root():
    return {"message": "NotebookLM Backend is running"}


@app.get("/health")
async def health():
    return {"status": "healthy", "timestamp": datetime.datetime.utcnow().isoformat()}


@app.on_event("startup")
async def warm_subject_cache():
    try:
        subjects = list_available_subjects()
        logger.info(f"Warmed subject cache: {len(subjects)} subjects available")
    except Exception as e:
        logger.warning(f"Failed to warm subject cache: {e}")
