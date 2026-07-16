# Backend — Intelligent Multimodal Research Assistant

FastAPI backend for a hybrid-retrieval RAG assistant over multi-PDF corpora, with conditional figure/image analysis and web fallback.

## Structure

| File | Responsibility |
|---|---|
| `config.py` | Env settings + shared client singletons (Qdrant, Supabase, Groq, Gemini, Tavily, embeddings, reranker) |
| `models.py` | Pydantic request/response schemas |
| `storage.py` | Supabase Postgres + Storage access (documents, conversations, messages, evaluations, PDFs, images) |
| `auth.py` | Supabase-auth signup/login + `get_current_user` dependency |
| `ingestion.py` | PDF text/image extraction, sentence-window + structure-aware chunking, embedding, Qdrant indexing |
| `retrieval.py` | Hybrid (BM25 + vector) retrieval, RRF fusion, conditional query expansion/reranking, contextual compression |
| `chat.py` | Conversation orchestration: memory, conditional image analysis (Gemini), web fallback (Tavily), answer generation (Groq) |
| `documents.py` | Upload / list / delete / summarise / compare document endpoints |
| `evaluation.py` | RAGAS evaluation (faithfulness, answer relevancy, context precision/recall), run as a background job |
| `jobs.py` | Background thread pool + in-memory job status store, shared by ingestion, summarise/compare, and evaluation |
| `main.py` | FastAPI app, router wiring, CORS, global exception handler |

## Setup

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create a `.env` file in `backend/` with the variables below, then run:

```bash
uvicorn app.main:app --reload --port 8000
```

Check it's up: `GET http://localhost:8000/health` → `{"status": "ok"}`

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `QDRANT_URL` | ✅ | — | Qdrant Cloud cluster URL |
| `QDRANT_API_KEY` | ✅ | — | |
| `QDRANT_COLLECTION` | | `Research` | Created automatically on first ingestion |
| `SUPABASE_URL` | ✅ | — | |
| `SUPABASE_SERVICE_KEY` | ✅ | — | Service-role key (server-side only, never expose to a client) |
| `SUPABASE_STORAGE_BUCKET_PDFS` | | `pdfs` | |
| `SUPABASE_STORAGE_BUCKET_IMAGES` | | `images` | |
| `GROQ_API_KEY` | ✅ | — | Answer generation |
| `GROQ_MODEL` | | `llama-3.1-8b-instant` | |
| `GEMINI_API_KEY` | ✅ | — | Figure/chart vision analysis only |
| `GEMINI_MODEL` | | `gemini-2.5-flash` | Falls back to other current Flash models if this one is retired |
| `TAVILY_API_KEY` | ✅ | — | Web-search fallback |
| `EMBEDDING_MODEL` | | `BAAI/bge-m3` | Local, downloaded on first run |
| `RERANKER_MODEL` | | `BAAI/bge-reranker-base` | Local |
| `JWT_SECRET` | recommended | `dev-secret` | See below |
| `CORS_ORIGINS` | | `http://localhost:5173` | Comma-separated |

### JWT_SECRET

Set this to your Supabase project's JWT secret (dashboard → Project Settings → API → JWT Settings → "JWT Secret"). It lets the backend verify request tokens locally instead of calling Supabase Auth on every request — faster, and avoids a shared-client token-refresh issue that could otherwise invalidate a token shortly after signup. Without it, auth still works, just slower.

## Supabase — one-time setup

Run in the Supabase SQL editor:

```sql
create table documents (
  id uuid primary key, user_id uuid not null, filename text not null,
  storage_path text not null, num_pages int default 0, num_chunks int default 0,
  num_figures int default 0, status text default 'processing',
  created_at timestamptz default now()
);

create table conversations (
  id uuid primary key, user_id uuid not null, title text,
  created_at timestamptz default now()
);

create table messages (
  id uuid primary key, conversation_id uuid references conversations(id),
  role text not null, content text not null, contexts jsonb default '[]',
  created_at timestamptz default now()
);

create table evaluations (
  id uuid primary key, conversation_id uuid references conversations(id),
  faithfulness float, answer_relevancy float, context_precision float,
  context_recall float, created_at timestamptz default now()
);
```

Then create two **private** Storage buckets: `pdfs` and `images` (accessed via the service-role key only).

## Qdrant Cloud

Create a free cluster at [cloud.qdrant.io](https://cloud.qdrant.io). The collection (`Research` by default, or whatever you set `QDRANT_COLLECTION` to) is created automatically the first time a document is ingested — no manual setup needed.
