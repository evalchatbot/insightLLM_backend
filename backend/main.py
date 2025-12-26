import logging
import os

from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import BackgroundTasks

from backend.api.routes import assistant, books, chatbot, conversations, ingest, ocr, users, quiz
from backend.utils.rubric_loader import list_subject_rubrics, list_available_subjects
from backend.api.routes.auth import get_current_user
from backend.middleware.logging_middleware import setup_api_logging
from backend.utils.logging_config import setup_logging

# Initialize centralized logging
log_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'logs', 'insightllm.log')
setup_logging(log_level=os.getenv("LOG_LEVEL", "INFO"), log_file=log_file)
logger = logging.getLogger(__name__)

debug = APIRouter()
@debug.get("/_debug/headers")
async def dbg_headers(request: Request):
    return {
        "authorization": request.headers.get("authorization"),
        "x-forwarded-authorization": request.headers.get("x-forwarded-authorization"),
    }

app = FastAPI(title="NotebookLM Backend", version="0.1.0")

# Set up comprehensive API logging
setup_api_logging(app)

# CORS (set your frontend origin)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://insight-llm-frontend.vercel.app", "http://localhost:5173" , "http://localhost:3000" , "https://insight-llm-frontend-2-0.vercel.app" , "https://insight-llm-frontend-2-0.vercel.app/app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.include_router(debug)  #
# Protect all “app” routers by default (leave root public)
app.include_router(users.router, dependencies=[Depends(get_current_user)])
app.include_router(chatbot.router)
app.include_router(assistant.router)
app.include_router(conversations.router, dependencies=[Depends(get_current_user)])
app.include_router(books.router, dependencies=[Depends(get_current_user)])
app.include_router(ingest.router, dependencies=[Depends(get_current_user)])
app.include_router(ocr.router)  # Removed JWT authentication for Clerk migration
app.include_router(quiz.router)

@app.get("/")
def root():
    logger.info("[API] Root endpoint accessed")
    return {"message": "NotebookLM Backend is vibing!"}


# Warm caches on startup to avoid first-request latency
@app.on_event("startup")
async def warm_subject_cache() -> None:
    try:
        subjects = list_subject_rubrics()
        _ = list_available_subjects()  # populate lru_cache
        logger.info("[Startup] Warmed rubric cache with %d subjects", len(subjects))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Startup] Failed to warm rubric cache: %s", exc)
