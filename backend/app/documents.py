from __future__ import annotations
import traceback

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from . import jobs, storage
from .auth import get_current_user
from .config import get_groq_client, settings
from .ingestion import delete_document_vectors, extract_pdf
from .models import CompareRequest, DocumentRecord, SummariseRequest, UploadResponse
from .retrieval import retrieve

router = APIRouter(prefix="/documents", tags=["documents"])


def _process_document(doc_id: str, user_id: str, filename: str, data: bytes) -> None:
   
    try:
        stats = extract_pdf(doc_id, user_id, filename, data)
        storage.update_document(doc_id, status="ready", **stats)
    except Exception as e:
        print(f"Background ingestion failed for {filename} ({doc_id}): {type(e).__name__}: {e}")
        traceback.print_exc()
        try:
            storage.update_document(doc_id, status="failed")
        except Exception:
            traceback.print_exc()


@router.post("/upload", response_model=UploadResponse)
async def upload_documents(
    files: list[UploadFile],
    user_id: str = Depends(get_current_user),
):
    records: list[DocumentRecord] = []

    for f in files:
        if not f.filename.lower().endswith(".pdf"):
            continue

        try:
            data = await f.read()
            storage_path = storage.upload_pdf(user_id, f.filename, data)
            doc = storage.create_document(user_id, f.filename, storage_path)
        except Exception as e:
            print(f"Upload failed for {f.filename}: {type(e).__name__}: {e}")
            traceback.print_exc()
            continue

        jobs.submit_background(_process_document, doc["id"], user_id, f.filename, data)
        records.append(DocumentRecord(**doc))

    return UploadResponse(documents=records)


@router.get("", response_model=list[DocumentRecord])
def list_user_documents(user_id: str = Depends(get_current_user)):
    return [DocumentRecord(**d) for d in storage.list_documents(user_id)]


@router.delete("/{document_id}")
def delete_user_document(document_id: str, user_id: str = Depends(get_current_user)):
    doc = storage.get_document(document_id)
    if not doc or doc["user_id"] != user_id:
        raise HTTPException(404, "Document not found")
  
    delete_document_vectors(document_id)
    storage.delete_document_figures(document_id)
    storage.delete_document_images(user_id, document_id)
    storage.delete_pdf(doc.get("storage_path", ""))
    storage.delete_document(document_id)
    return {"status": "deleted"}


def _run_summarise(document_id: str, filename: str) -> dict:
    chunks = retrieve(f"key points and overview of {filename}", document_ids=[document_id])
    context = "\n\n".join(c.text for c in chunks if c.content_type == "text")
    if not context:
        return {"summary": "Not enough extracted text to summarise this document."}

    client = get_groq_client()
    resp = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {
                "role": "system",
                "content": "Write a concise, well-structured summary of the document context provided. "
                "Do not mention sources or page numbers.",
            },
            {"role": "user", "content": context},
        ],
        temperature=0.2,
        max_tokens=500,
    )
    return {"summary": resp.choices[0].message.content.strip()}


@router.post("/summarise")
def summarise_document(req: SummariseRequest, user_id: str = Depends(get_current_user)):
    doc = storage.get_document(req.document_id)
    if not doc or doc["user_id"] != user_id:
        raise HTTPException(404, "Document not found")

    job_id = jobs.create_job("summarise", meta={"document_id": req.document_id, "filename": doc["filename"]})
    jobs.run_in_background(job_id, _run_summarise, req.document_id, doc["filename"])
    return {"job_id": job_id}


def _run_compare(docs: list[dict], aspect: str) -> dict:
    sections = []
    for d in docs:
        chunks = retrieve(aspect, document_ids=[d["id"]])
        context = "\n\n".join(c.text for c in chunks if c.content_type == "text")
        sections.append(f"### {d['filename']}\n{context}")

    client = get_groq_client()
    resp = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {
                "role": "system",
                "content": f"Compare the following documents with respect to: {aspect}. "
                "Produce a concise structured comparison (similarities, differences, notable gaps). "
                "Do not mention sources or page numbers.",
            },
            {"role": "user", "content": "\n\n".join(sections)},
        ],
        temperature=0.2,
        max_tokens=700,
    )
    return {"comparison": resp.choices[0].message.content.strip()}


@router.post("/compare")
def compare_documents(req: CompareRequest, user_id: str = Depends(get_current_user)):
    docs = []
    for did in req.document_ids:
        d = storage.get_document(did)
        if not d or d["user_id"] != user_id:
            raise HTTPException(404, f"Document {did} not found")
        docs.append(d)

    aspect = req.aspect or "key findings, methodology, and conclusions"
    job_id = jobs.create_job("compare", meta={"document_ids": req.document_ids, "aspect": aspect})
    jobs.run_in_background(job_id, _run_compare, docs, aspect)
    return {"job_id": job_id}


@router.get("/jobs/{job_id}")
def get_document_job(job_id: str, user_id: str = Depends(get_current_user)):
    """Polled by the frontend (from any tab) to recover the status/result
    of a summarise or compare job started earlier, independent of the
    original request's lifetime."""
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job