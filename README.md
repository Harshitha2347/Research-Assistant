# Intelligent Multimodal Research Assistant

A full-stack RAG application for chatting with your own PDF library — text **and** figures/charts/diagrams — with hybrid retrieval, on-demand image understanding, and a web-search fallback for questions your documents can't answer.

```
research-assistant/
├── backend/     FastAPI + Qdrant + Supabase + Groq + Gemini
└── frontend/    React + TypeScript + Tailwind
```

---

## ✨ Features

- **Multi-PDF chat** — upload any number of PDFs and ask questions across all of them, or scope a conversation to specific documents.
- **Hybrid retrieval** — vector search (Gemini embeddings) + BM25, fused with Reciprocal Rank Fusion, cross-encoder reranked, with query expansion/decomposition for weak or multi-part questions.
- **Web-search fallback** — if your documents genuinely don't answer a question, the assistant says so and (unless you've scoped to specific documents or disabled it) falls back to a live web search via Tavily.
- **Document tools** — per-document summarise and cross-document compare, run as background jobs so the UI never blocks.
- **RAG evaluation** — RAGAS-based faithfulness / answer relevancy / context precision / context recall scoring on your own conversations.
- **Conversation memory** — follow-up questions ("what about the second one?") are automatically rewritten into standalone queries using recent chat history before retrieval.

---

## 🧱 Architecture

| Layer | Tech |
|---|---|
| Frontend | React 18, TypeScript, Vite, Tailwind, React Router |
| Backend | FastAPI, background thread-pool jobs |
| Vector store | Qdrant Cloud (text chunks only) |
| Relational + file storage | Supabase (Postgres + Storage) |
| Embeddings | Gemini API (`gemini-embedding-001`, hosted — no local model) |
| Answer generation | Groq (`llama-3.1-8b-instant` by default) |
| Vision (figures only) | Gemini 2.5 Flash, called only on demand |
| Web fallback | Tavily |
| Auth | Supabase Auth, verified locally via JWT |

### How a document gets processed

1. **Upload** → PDF is stored in Supabase Storage; ingestion runs as a background job.
2. **Text** is extracted page-by-page, chunked (sentence-window + structure-aware), and embedded in batches.
3. **Figures** are extracted, uploaded to Supabase Storage, and their metadata (page, caption, section heading) is saved as a plain row — **no embedding call, no vision call** at this stage.
4. Text chunks are upserted into Qdrant. The document is marked `ready`.

### How a question gets answered

1. The question is rewritten into a standalone query using recent conversation history (if any).
2. Hybrid retrieval (vector + BM25 + RRF + reranking) pulls the best-matching **text** chunks.
3. If the question mentions a figure/chart/diagram/image, candidate figures are shortlisted by cheap keyword overlap against their captions/headings — no API call — and only that shortlist is sent to Gemini vision to describe what's actually in the image.
4. If text + figure context together are still too weak (and no specific document scope was chosen), a web search fills the gap — and the answer says plainly that it came from the web, not your documents.
5. Groq generates the final answer from whatever context was gathered.

This "only process what's actually asked about" design keeps API usage low and avoids hitting provider rate limits on large or figure-heavy PDFs.

---

## 🚀 Getting started

### 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Create `backend/.env`:

```bash
# Qdrant Cloud
QDRANT_URL=
QDRANT_API_KEY=
QDRANT_COLLECTION=Research          # auto-created on first ingestion

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=               # service-role key — server-side only
SUPABASE_STORAGE_BUCKET_PDFS=pdfs
SUPABASE_STORAGE_BUCKET_IMAGES=images

# Groq — answer generation
GROQ_API_KEY=
GROQ_MODEL=llama-3.1-8b-instant

# Gemini — embeddings + on-demand figure vision
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
EMBEDDING_MODEL=models/gemini-embedding-001
EMBEDDING_OUTPUT_DIM=768

# Tavily — web-search fallback
TAVILY_API_KEY=

# Reranker (local, downloaded on first run)
RERANKER_MODEL=BAAI/bge-reranker-base

# App
JWT_SECRET=                         # Supabase project's JWT secret — see below
CORS_ORIGINS=http://localhost:5173
```

Run it:

```bash
uvicorn app.main:app --reload --port 8000
```

Check it's up: `GET http://localhost:8000/health` → `{"status": "ok"}`

> **`JWT_SECRET`**: set to your Supabase project's JWT secret (Dashboard → Project Settings → API → JWT Settings). This lets the backend verify tokens locally instead of calling Supabase Auth on every request. Auth still works without it, just slower.

### 2. Supabase — one-time setup

Run in the Supabase SQL editor:

```sql
create table documents (
  id uuid primary key, user_id uuid not null, filename text not null,
  storage_path text not null, num_pages int default 0, num_chunks int default 0,
  num_figures int default 0, status text default 'processing',
  created_at timestamptz default now()
);

create table figures (
  id uuid primary key, document_id uuid not null, user_id uuid not null,
  document_name text, page_number int, storage_path text, image_ext text,
  figure_caption text, section_heading text, figure_text text,
  created_at timestamptz default now()
);
create index on figures (document_id);

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
  context_recall float, pair_indices jsonb default '[]',
  created_at timestamptz default now()
);
```

Then create two **private** Storage buckets: `pdfs` and `images` (service-role access only).

### 3. Qdrant Cloud

Create a free cluster at [cloud.qdrant.io](https://cloud.qdrant.io). The collection is created automatically on first ingestion — no manual setup needed.

### 4. Frontend

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. Update `VITE_API_URL` (or the equivalent in `src/api/client.ts`) if your backend isn't on `localhost:8000`.

---

## 📁 Project structure

### Backend (`backend/app/`)

| File | Responsibility |
|---|---|
| `config.py` | Env settings + shared client singletons (Qdrant, Supabase, Groq, Gemini, Tavily, embeddings, reranker) |
| `models.py` | Pydantic request/response schemas |
| `storage.py` | Supabase Postgres + Storage access (documents, figures, conversations, messages, evaluations, PDFs, images) |
| `auth.py` | Supabase-auth signup/login + `get_current_user` dependency |
| `ingestion.py` | PDF text/image extraction, sentence-window + structure-aware chunking, batched text embedding, figure metadata storage, Qdrant indexing |
| `retrieval.py` | Hybrid (BM25 + vector) text retrieval with RRF fusion, reranking, query expansion/decomposition; keyword-ranked figure lookup |
| `chat.py` | Conversation orchestration: memory, on-demand figure vision analysis (rate-limited + retried), web fallback, answer generation |
| `documents.py` | Upload / list / delete / summarise / compare document endpoints |
| `evaluation.py` | RAGAS evaluation, run as a background job |
| `jobs.py` | Background thread pool + in-memory job status store |
| `main.py` | FastAPI app, router wiring, CORS, global exception handler |

### Frontend (`frontend/src/`)

| Path | Responsibility |
|---|---|
| `pages/Login.tsx` | Sign up / log in |
| `pages/Documents.tsx` | Upload, list, delete, summarise, compare documents |
| `pages/Chat.tsx` | Conversation UI, document scoping, web-search toggle, voice input |
| `pages/Evaluation.tsx` | Run and view RAGAS evaluations |
| `context/AuthContext.tsx` | Auth state + session |
| `context/JobsContext.tsx` | Upload progress / background job polling shared across pages |
| `hooks/useVoice.ts` | Web Speech API integration |
| `api/client.ts` | Backend API client |

---

## 🔒 Notes

- The Gemini vision call used for figures is rate-limited and retried with exponential backoff client-side, in addition to whatever Gemini enforces server-side — so a burst of visual questions won't hard-fail on a free-tier quota.
- Figures are never embedded or vision-processed at upload time — only their metadata is stored. This keeps ingestion of large, image-heavy PDFs fast and immune to embedding-rate-limit failures.
- `SUPABASE_SERVICE_KEY` and all API keys are server-side only — never expose them to the frontend.
