
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


_MODEL_CACHE_DIR = Path(__file__).resolve().parent.parent / ".model_cache"
_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(_MODEL_CACHE_DIR))
os.environ.setdefault("HF_HUB_CACHE", str(_MODEL_CACHE_DIR / "hub"))
os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", str(_MODEL_CACHE_DIR))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")


class Settings(BaseSettings):
    # Qdrant Cloud
    qdrant_url: str = os.getenv("QDRANT_URL", "")
    qdrant_api_key: str = os.getenv("QDRANT_API_KEY", "")
    qdrant_collection: str = os.getenv("QDRANT_COLLECTION", "Research")

    # Supabase
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    supabase_service_key: str = os.getenv("SUPABASE_SERVICE_KEY", "")
    supabase_storage_bucket_pdfs: str= os.getenv("SUPABASE_STORAGE_BUCKET_PDFS", "pdfs")
    supabase_storage_bucket_images: str = os.getenv("SUPABASE_STORAGE_BUCKET_IMAGES", "images")

    # Groq
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

    
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

    # Tavily
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")

    embedding_model: str = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
    embedding_output_dim: int = int(os.getenv("EMBEDDING_OUTPUT_DIM", "768"))

    reranker_model: str = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-base")

    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret")
    cors_origins: str = os.getenv("CORS_ORIGINS", "http://localhost:5173")

    class Config:
        env_file = ".env"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


@lru_cache
def get_qdrant_client():
    from qdrant_client import QdrantClient
    return QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)


@lru_cache
def get_supabase_client():
    from supabase import create_client
    return create_client(settings.supabase_url, settings.supabase_service_key)


@lru_cache
def get_supabase_auth_read_client():
   
    from supabase import create_client
    from supabase.lib.client_options import ClientOptions

    return create_client(
        settings.supabase_url,
        settings.supabase_service_key,
        options=ClientOptions(auto_refresh_token=False),
    )


@lru_cache
def get_groq_client():
    from groq import Groq
    return Groq(api_key=settings.groq_api_key)


@lru_cache
def get_gemini_model(model_name: Optional[str] = None):

    import google.generativeai as genai
    genai.configure(api_key=settings.gemini_api_key)
    return genai.GenerativeModel(model_name or settings.gemini_model)


@lru_cache
def get_tavily_client():
    from tavily import TavilyClient
    return TavilyClient(api_key=settings.tavily_api_key)


@lru_cache
def get_embed_model():

    from .gemini_embedding import GeminiEmbedding
    return GeminiEmbedding(
        api_key=settings.gemini_api_key,
        model_name=settings.embedding_model,
        output_dimensionality=settings.embedding_output_dim,
    )


@lru_cache
def get_reranker():
   
    from FlagEmbedding import FlagReranker
    return FlagReranker(settings.reranker_model, use_fp16=True)
