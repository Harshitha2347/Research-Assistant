
from __future__ import annotations

import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .auth import router as auth_router
from .chat import router as chat_router
from .config import settings
from .documents import router as documents_router
from .evaluation import router as evaluation_router

app = FastAPI(
    title="Intelligent Multimodal Research Assistant",
    description="Hybrid-retrieval RAG assistant over multi-PDF corpora with conditional image analysis and web fallback.",
    version="1.0.0",
)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(evaluation_router)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
   
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on our end. Please try again."},
    )


@app.get("/health")
def health():
    return {"status": "ok"}
