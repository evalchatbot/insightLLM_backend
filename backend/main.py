from fastapi import FastAPI, Depends, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from backend.api.routes import users, chatbot, books, ingest, conversations, ocr
from backend.api.routes.auth import get_current_user  # NEW
from backend.utils.logging_config import setup_logging
from backend.middleware.logging_middleware import setup_api_logging
import os
import os
import logging

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
app.include_router(chatbot.router)  # Removed JWT authentication for Clerk migration
app.include_router(conversations.router, dependencies=[Depends(get_current_user)])
app.include_router(books.router, dependencies=[Depends(get_current_user)])
app.include_router(ingest.router, dependencies=[Depends(get_current_user)])
app.include_router(ocr.router)  # Removed JWT authentication for Clerk migration

@app.get("/")
def root():
    logger.info("[API] Root endpoint accessed")
    return {"message": "NotebookLM Backend is vibing!"}
