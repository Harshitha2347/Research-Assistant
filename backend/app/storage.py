from __future__ import annotations
import math
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from .config import get_supabase_client, settings


def _sb():
    return get_supabase_client()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


#storage 
def upload_pdf(user_id: str, filename: str, data: bytes) -> str:
    path = f"{user_id}/{uuid.uuid4()}_{filename}"
    sb = _sb()
    sb.storage.from_(settings.supabase_storage_bucket_pdfs).upload(
        path,
        data,
        file_options={
            "content-type": "application/pdf",
            "upsert": "true",
        },
    )
    return path


_IMAGE_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "webp": "image/webp",
    "gif": "image/gif",
    "bmp": "image/bmp",
    "tiff": "image/tiff",
    "jp2": "image/jp2",
}


def image_mime_type(ext: str) -> str:
    return _IMAGE_MIME_TYPES.get((ext or "png").lower().lstrip("."), "image/png")


def upload_image(user_id: str, doc_id: str, image_id: str, data: bytes, ext: str = "png") -> str:
  
    ext = (ext or "png").lower().lstrip(".")
    if ext not in _IMAGE_MIME_TYPES:
        ext = "png"
    path = f"{user_id}/{doc_id}/{image_id}.{ext}"
    _sb().storage.from_(settings.supabase_storage_bucket_images).upload(
        path, data, {"content-type": image_mime_type(ext)}
    )
    return path


def delete_pdf(path: str) -> None:
    if not path:
        return
    try:
        _sb().storage.from_(settings.supabase_storage_bucket_pdfs).remove([path])
    except Exception:
        pass


def delete_document_images(user_id: str, doc_id: str) -> None:
    
    bucket = _sb().storage.from_(settings.supabase_storage_bucket_images)
    prefix = f"{user_id}/{doc_id}"
    try:
        entries = bucket.list(prefix) or []
        paths = [f"{prefix}/{e['name']}" for e in entries if e.get("name")]
        if paths:
            bucket.remove(paths)
    except Exception:
        pass


def download_image(path: str) -> bytes:
    return _sb().storage.from_(settings.supabase_storage_bucket_images).download(path)


def signed_pdf_url(path: str, expires_in: int = 3600) -> str:
    res = _sb().storage.from_(settings.supabase_storage_bucket_pdfs).create_signed_url(path, expires_in)
    return res.get("signedURL") or res.get("signed_url", "")


#documents
def create_document(user_id: str, filename: str, storage_path: str) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "filename": filename,
        "storage_path": storage_path,
        "num_pages": 0,
        "num_chunks": 0,
        "num_figures": 0,
        "status": "processing",
        "created_at": now(),
    }
    _sb().table("documents").insert(row).execute()
    return row


def update_document(doc_id: str, **fields: Any) -> None:
    _sb().table("documents").update(fields).eq("id", doc_id).execute()


def get_document(doc_id: str) -> Optional[dict]:
    res = _sb().table("documents").select("*").eq("id", doc_id).limit(1).execute()
    return res.data[0] if res.data else None


def list_documents(user_id: str) -> list[dict]:
    res = (
        _sb()
        .table("documents")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


def delete_document(doc_id: str) -> None:
    _sb().table("documents").delete().eq("id", doc_id).execute()


def save_figures_bulk(pending: list[dict]) -> None:
    if not pending:
        return
    rows = [
        {
            "id": p["image_id"],
            "document_id": p["document_id"],
            "user_id": p["user_id"],
            "document_name": p["document_name"],
            "page_number": p["page_number"],
            "storage_path": p["storage_path"],
            "image_ext": p["image_ext"],
            "figure_caption": p["figure_caption"],
            "section_heading": p["section_heading"],
            "figure_text": p["figure_text"],
            "created_at": now(),
        }
        for p in pending
    ]
    _sb().table("figures").insert(rows).execute()


def list_figures(document_ids: Optional[list[str]] = None) -> list[dict]:
    q = _sb().table("figures").select("*")
    if document_ids:
        q = q.in_("document_id", document_ids)
    res = q.execute()
    return res.data


def delete_document_figures(doc_id: str) -> None:
    _sb().table("figures").delete().eq("document_id", doc_id).execute()


#conversations
def create_conversation(user_id: str, title: str) -> dict:
    row = {"id": str(uuid.uuid4()), "user_id": user_id, "title": title, "created_at": now()}
    _sb().table("conversations").insert(row).execute()
    return row


def get_conversation(conv_id: str) -> Optional[dict]:
    res = _sb().table("conversations").select("*").eq("id", conv_id).limit(1).execute()
    return res.data[0] if res.data else None


def update_conversation_title(conv_id: str, title: str) -> None:
    _sb().table("conversations").update({"title": title}).eq("id", conv_id).execute()


def list_conversations(user_id: str) -> list[dict]:
    res = (
        _sb()
        .table("conversations")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data


def add_message(conv_id: str, role: str, content: str, contexts: Optional[list] = None) -> None:
    _sb().table("messages").insert(
        {
            "id": str(uuid.uuid4()),
            "conversation_id": conv_id,
            "role": role,
            "content": content,
            "contexts": contexts or [],
            "created_at": now(),
        }
    ).execute()


def get_messages(conv_id: str, limit: int = 12) -> list[dict]:
    res = (
        _sb()
        .table("messages")
        .select("*")
        .eq("conversation_id", conv_id)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    return res.data





def _safe_float(value):
  
    try:
        value = float(value)
        if math.isnan(value) or math.isinf(value):
            return None
        return value
    except Exception:
        return None


def save_evaluation(conv_id: str, scores: dict, pair_indices: Optional[list] = None) -> dict:
    row = {
        "id": str(uuid.uuid4()),
        "conversation_id": conv_id,
        "faithfulness": _safe_float(scores.get("faithfulness")),
        "answer_relevancy": _safe_float(scores.get("answer_relevancy")),
        "context_precision": _safe_float(scores.get("context_precision")),
        "context_recall": _safe_float(scores.get("context_recall")),
        "pair_indices": sorted(pair_indices) if pair_indices else [],
        "created_at": now(),
    }

    try:
        _sb().table("evaluations").insert(row).execute()
    except Exception as e:
     
        msg = str(e)
        if "pair_indices" in msg and ("PGRST204" in msg or "schema cache" in msg or "column" in msg.lower()):
            print(
                "[storage] 'evaluations.pair_indices' column not found — saving without it. "
                "Run this once in the Supabase SQL editor to enable duplicate-evaluation "
                "detection and per-evaluation pair counts in History:\n"
                "    alter table evaluations add column pair_indices jsonb;"
            )
            row.pop("pair_indices")
            _sb().table("evaluations").insert(row).execute()
            row["pair_indices"] = []  # keep the return shape consistent for callers
        else:
            raise

    return row


def find_existing_evaluation(conversation_id: str, pair_indices: list) -> Optional[dict]:
   
    target = sorted(pair_indices)
    res = (
        _sb()
        .table("evaluations")
        .select("*")
        .eq("conversation_id", conversation_id)
        .execute()
    )
    for e in res.data:
        if sorted(e.get("pair_indices") or []) == target:
            return e
    return None


def list_evaluations(user_id: str) -> list[dict]:
   
    conv_titles = {c["id"]: c.get("title") for c in list_conversations(user_id)}
    res = _sb().table("evaluations").select("*").order("created_at", desc=True).execute()
    out = []
    for e in res.data:
        if e["conversation_id"] in conv_titles:
            row = dict(e)
            row["conversation_title"] = conv_titles[e["conversation_id"]]
            out.append(row)
    return out