
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


# auth
class SignupRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    access_token: str
    user_id: str
    email: str


# documents
class DocumentRecord(BaseModel):
    id: str
    user_id: str
    filename: str
    storage_path: str
    num_pages: int
    num_chunks: int
    num_figures: int
    status: Literal["processing", "ready", "failed"]
    created_at: str


class UploadResponse(BaseModel):
    documents: list[DocumentRecord]


class SummariseRequest(BaseModel):
    document_id: str


class CompareRequest(BaseModel):
    document_ids: list[str] = Field(min_length=2)
    aspect: Optional[str] = None


# chat
class ChatRequest(BaseModel):
    conversation_id: Optional[str] = None
    message: str
    document_ids: Optional[list[str]] = None  
    
    use_web_search: Optional[bool] = None


class ChatResponse(BaseModel):
    conversation_id: str
    answer: str
    used_web_search: bool = False
    used_image_analysis: bool = False


class ConversationSummary(BaseModel):
    id: str
    title: str
    created_at: str


#internal use
class RetrievedChunk(BaseModel):
    text: str
    score: float
    document_name: str
    page_number: int
    chunk_id: str
    content_type: Literal["text", "figure"]
    image_id: Optional[str] = None
    figure_caption: Optional[str] = None
    section_heading: Optional[str] = None
    storage_path: Optional[str] = None
    image_ext: Optional[str] = None


# evaluation
class EvaluationRequest(BaseModel):
    conversation_id: str
    pair_indices: list[int] | None = None

class EvaluationResult(BaseModel):
    id: str
    conversation_id: str
    faithfulness: Optional[float] = None
    answer_relevancy: Optional[float] = None
    context_precision: Optional[float] = None
    context_recall: Optional[float] = None
    pair_indices: Optional[list[int]] = None
    conversation_title: Optional[str] = None
    created_at: str
