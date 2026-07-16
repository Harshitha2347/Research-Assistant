from __future__ import annotations

import threading
import time
from typing import Optional

from fastapi import APIRouter, Depends

from . import storage
from .auth import get_current_user
from .config import get_gemini_model, get_groq_client, get_tavily_client, settings
from .models import ChatRequest, ChatResponse, ConversationSummary, RetrievedChunk
from .retrieval import retrieve, retrieve_figures, query_mentions_visual

router = APIRouter(prefix="/chat", tags=["chat"])


LOW_CONFIDENCE_THRESHOLD = 0.2
MIN_CONTEXT_CHARS = 40
MAX_IMAGES_ANALYSED = 3


def _contextualize_query(query: str, memory: str) -> str:
    """Rewrites the question into a standalone one using recent
    conversation history, so retrieval has an actual subject to search
    for — e.g. "Where did both study?" contains no named entity at all;
    "both" only means something in light of the prior turns, so retrieve()
    would otherwise only be able to match generic "study/education"
    chunks. Rather than guess which questions need this from surface
    patterns (pronoun keywords, capitalization, word count — all
    English-only and brittle), the prompt itself instructs the LLM to
    return the question unchanged when it's already standalone, so this
    is safe to call any time there's prior conversation to draw on. It
    only runs when `memory` is non-empty (see the call site in
    handle_chat), and the answer is still generated against the user's
    ORIGINAL question, not this rewrite — only retrieval uses it."""
    if not memory:
        return query
    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Given this conversation history:\n" + memory + "\n\n"
                        "If the question below relies on the conversation above "
                        "to make sense (e.g. it uses a pronoun or reference like "
                        "'both'/'they'/'it' standing in for something named "
                        "earlier), rewrite it as a fully standalone question "
                        "with that reference resolved. If it's already "
                        "standalone, return it completely unchanged. Return "
                        "ONLY the question, nothing else.\n\n"
                        f"Question: {query}"
                    ),
                }
            ],
            temperature=0,
            max_tokens=60,
        )
        rewritten = resp.choices[0].message.content.strip().strip('"')
        return rewritten or query
    except Exception:
        return query


def _build_memory_block(conv_id: str) -> str:
    history = storage.get_messages(conv_id, limit=8)
    if not history:
        return ""
    lines = [f"{m['role']}: {m['content']}" for m in history]
    return "\n".join(lines)

_GEMINI_FALLBACK_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.5-flash",
    "gemini-3.1-flash-lite",
]
_working_gemini_model: Optional[str] = None
_GEMINI_RPM_LIMIT = 5
_GEMINI_WINDOW_SECONDS = 60.0
_gemini_call_times: list[float] = []
_gemini_rate_lock = threading.Lock()

_VISION_MAX_RETRIES = 4
_RETRYABLE_MARKERS = ("429", "quota", "rate limit", "resourceexhausted", "503", "unavailable")


def _is_retryable(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _RETRYABLE_MARKERS)


def _wait_for_gemini_slot() -> None:
    while True:
        with _gemini_rate_lock:
            now = time.monotonic()
            while _gemini_call_times and now - _gemini_call_times[0] > _GEMINI_WINDOW_SECONDS:
                _gemini_call_times.pop(0)
            if len(_gemini_call_times) < _GEMINI_RPM_LIMIT:
                _gemini_call_times.append(now)
                return
            sleep_for = _GEMINI_WINDOW_SECONDS - (now - _gemini_call_times[0]) + 0.1
        time.sleep(max(sleep_for, 0.1))


def _generate_with_gemini(image_bytes: bytes, mime_type: str, prompt: str) -> str:
    global _working_gemini_model
    candidates = [settings.gemini_model, *_GEMINI_FALLBACK_MODELS]
    if _working_gemini_model:
        candidates = [_working_gemini_model, *[c for c in candidates if c != _working_gemini_model]]

    last_err: Optional[Exception] = None
    for name in dict.fromkeys(candidates):
        model = get_gemini_model(name)
        delay = 2.0
        for attempt in range(_VISION_MAX_RETRIES):
            _wait_for_gemini_slot()
            try:
                response = model.generate_content([{"mime_type": mime_type, "data": image_bytes}, prompt])
                _working_gemini_model = name
                return (response.text or "").strip()
            except Exception as e:
                last_err = e
                if attempt < _VISION_MAX_RETRIES - 1 and _is_retryable(e):
                    time.sleep(delay)
                    delay *= 2
                    continue
                break  
    raise last_err or RuntimeError("No Gemini model candidate succeeded")


def _analyse_figures(chunks: list[RetrievedChunk], query: str) -> tuple[str, bool]:
   
    seen: set[str] = set()
    figures: list[RetrievedChunk] = []
    for c in chunks:
        if c.content_type != "figure" or not c.storage_path or c.storage_path in seen:
            continue
        seen.add(c.storage_path)
        figures.append(c)
        if len(figures) >= MAX_IMAGES_ANALYSED:
            break

    if not figures:
        return "", False

    notes = []
    for fig in figures:
        try:
            image_bytes = storage.download_image(fig.storage_path)
            location = f"page {fig.page_number}" if fig.page_number else "the document"
            heading = f' in the section "{fig.section_heading}"' if fig.section_heading else ""
            caption = fig.figure_caption or "no caption available"

            prompt = (
                f"This image was extracted from {location} of a research paper"
                f"{heading}. Its nearby caption text (if any) is: \"{caption}\".\n\n"
                f'The reader\'s question is: "{query}"\n\n'
                "Describe ONLY what is literally visible in THIS image. If it's "
                "a chart/plot: actual axis labels, legend entries, numbers, and "
                "plotted trends. If it's a diagram/flowchart/architecture "
                "figure: the actual boxes/components shown, their labels, and "
                "the arrows/connections between them (what feeds into what, in "
                "what order/direction) — a step-by-step account of the visual "
                "structure, not a general explanation of the concept it depicts. "
                "Do not describe a generic or typical figure of this kind, and "
                "do not invent values, labels, components, or trends you can't "
                "actually read in the image. If this particular image does not "
                "show what the question is asking about, say so plainly (e.g. "
                "'this figure doesn't show that — it shows X instead') rather "
                "than guessing. Answer in 3-6 concise sentences."
            )
           
            mime_type = storage.image_mime_type(fig.image_ext or "png")
            note = _generate_with_gemini(image_bytes, mime_type, prompt)
            if note:
                notes.append(f'[Figure — {location}, caption: "{caption}"]\n{note}')
        except Exception as e:
           
            print(f"[chat] figure analysis failed for storage_path={fig.storage_path!r}: {type(e).__name__}: {e}")
            continue
    return "\n\n".join(notes), bool(notes)


def _web_search_fallback(query: str) -> str:
    try:
        client = get_tavily_client()
        res = client.search(query=query, max_results=4, search_depth="basic")
        snippets = [r.get("content", "") for r in res.get("results", [])]
        return "\n".join(snippets[:4])
    except Exception:
        return ""


def _context_is_weak(chunks: list[RetrievedChunk], text_context: str) -> bool:
    if not chunks:
        return True
    if len((text_context or "").strip()) < MIN_CONTEXT_CHARS:
        return True
    best = max((c.score for c in chunks), default=0.0)
    return best < LOW_CONFIDENCE_THRESHOLD


def _generate_answer(
    query: str,
    memory: str,
    text_context: str,
    image_context: str,
    web_context: str,
    used_web: bool,
    announce_web_fallback: bool = False,
) -> str:
    client = get_groq_client()
    parts = []
    if memory:
        parts.append(f"Conversation so far:\n{memory}")
    if text_context:
        parts.append(f"Relevant document context:\n{text_context}")
    if image_context:
        parts.append(f"Relevant figure/image understanding:\n{image_context}")
    if web_context:
        parts.append(f"Web search results:\n{web_context}")
    context_block = "\n\n".join(parts) if parts else "No additional context available."

    system = (
        "You are a precise research assistant. Answer the user's question "
        "using ONLY the provided context below — never fall back on general "
        "knowledge, training data, or a plausible-sounding guess to fill a "
        "gap in the context, even for well-known facts. Every claim in your "
        "answer must be traceable to something actually stated in the "
        "context.\n\n"
        "Strict grounding rules:\n"
        "- If the context fully answers the question, answer directly and "
        "concisely from it.\n"
        "- If the context only partially answers it, answer the part it "
        "supports and explicitly say which part is not covered, rather than "
        "completing the gap yourself.\n"
        "- If the context doesn't address the question at all, say so "
        "plainly in one short sentence instead of guessing — do not "
        "invent numbers, names, dates, or conclusions that aren't in the "
        "context.\n"
        "- Document context below may be broken into chunks labeled "
        "'[Section name]' — a fact under one label belongs ONLY to that "
        "section/person/item, never to a different one, even if two "
        "labeled chunks appear next to each other or use similar wording. "
        "If the question asks about a specific named person/item, use "
        "only the chunk(s) actually labeled with that name.\n"
        "- Never mention sources, citations, scores, or document names "
        "explicitly unless the user asks for them (the UI already shows "
        "whether an answer came from documents or the web, so don't repeat "
        "that in the text) — except where the web-fallback instruction "
        "below overrides this.\n\n"
        "Structure your response for readability:\n"
        "- Lead with a direct 1-2 sentence answer to the question.\n"
        "- If the answer has multiple distinct parts, steps, or comparable "
        "items, follow with a short bulleted or numbered list — otherwise "
        "keep it to a short paragraph.\n"
        "- Use **bold** only for key terms, not whole sentences.\n"
        "- Keep the whole answer concise; avoid filler like 'Based on the "
        "provided context' or restating the question.\n"
        "- If the figure/image understanding notes say a figure doesn't show "
        "what was asked, or is uncertain, pass that along honestly instead of "
        "filling in a confident-sounding guess.\n"
        "- If the question is asking about a specific figure/diagram/image AND "
        "figure/image understanding notes are present below: build your answer "
        "primarily from those notes (the actual components, labels, arrows, or "
        "data points that were read off the image) rather than from the "
        "surrounding document prose, even if that prose also happens to "
        "describe the same general topic — the notes describe what the figure "
        "actually shows, which is what was asked for."
    )
    if announce_web_fallback:
     
        system += (
            "\n\nImportant: the user's uploaded documents did NOT contain a "
            "confident answer to this question, so the context above comes "
            "from a web search instead. Begin your answer by clearly stating "
            "that this wasn't found in their documents, then answer from the "
            "web search results — e.g. start with something like "
            "\"This isn't covered in your uploaded documents. From a web "
            "search: ...\". If the web results also don't answer it, say so "
            "plainly rather than guessing."
        )

    user_msg = f"{context_block}\n\nQuestion: {query}"

    resp = client.chat.completions.create(
        model=settings.groq_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
       
        temperature=0.1,
        max_tokens=700,
    )
    return resp.choices[0].message.content.strip()


def _generate_title(message: str) -> str:
    fallback = message.strip()[:60] or "New conversation"
    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Summarize the following user message as a short chat "
                        "title, at most 6 words, no quotes, no trailing "
                        "punctuation, no markdown:\n\n" + message.strip()[:500]
                    ),
                }
            ],
            temperature=0.3,
            max_tokens=20,
        )
        title = resp.choices[0].message.content.strip().strip('"').strip("'")
        return title[:80] or fallback
    except Exception:
        return fallback


def handle_chat(req: ChatRequest, user_id: str) -> ChatResponse:
    conv_id = req.conversation_id
    is_new_conversation = not conv_id
    if is_new_conversation:
        conv = storage.create_conversation(user_id, req.message.strip()[:60] or "New conversation")
        conv_id = conv["id"]

    memory = _build_memory_block(conv_id)

  
    if req.use_web_search is True:
        chunks: list[RetrievedChunk] = []
        text_context = ""
        image_context, used_image = "", False
        web_context = _web_search_fallback(req.message)
        used_web = bool(web_context)
    else:
        retrieval_query = _contextualize_query(req.message, memory)

        chunks = retrieve(retrieval_query, document_ids=req.document_ids)

        def _format_chunk(c: RetrievedChunk) -> str:

            if c.section_heading and c.section_heading.lower() not in c.text.lower():
                return f"[{c.section_heading}]\n{c.text}"
            return c.text

        text_context = "\n\n".join(_format_chunk(c) for c in chunks if c.content_type == "text")

      
        
        looks_visual = query_mentions_visual(req.message)
        if looks_visual:
            figure_pool = retrieve_figures(retrieval_query, req.document_ids, limit=MAX_IMAGES_ANALYSED)
            image_context, used_image = _analyse_figures(figure_pool, req.message)
        else:
            image_context, used_image = "", False

        if req.use_web_search is False:
            web_context = ""
            used_web = False
        elif req.document_ids:

            web_context = ""
            used_web = False
        else:
            web_context = ""
            used_web = False
         
            doc_answered = bool(text_context.strip()) or bool(image_context.strip())
            if not doc_answered or _context_is_weak(chunks, text_context):
                web_context = _web_search_fallback(retrieval_query)
                used_web = bool(web_context)

    announce_web_fallback = req.use_web_search is None and used_web

    answer = _generate_answer(
        req.message, memory, text_context, image_context, web_context, used_web, announce_web_fallback
    )

    if is_new_conversation:
      
        try:
            storage.update_conversation_title(conv_id, _generate_title(req.message))
        except Exception:
            pass

   
    context_parts = [p for p in (text_context, image_context, web_context) if p]

    storage.add_message(conv_id, "user", req.message)
    storage.add_message(conv_id, "assistant", answer, contexts=context_parts)

    return ChatResponse(
        conversation_id=conv_id,
        answer=answer,
        used_web_search=used_web,
        used_image_analysis=used_image,
    )


# routes
@router.post("", response_model=ChatResponse)
def chat_endpoint(req: ChatRequest, user_id: str = Depends(get_current_user)):
    return handle_chat(req, user_id)


@router.get("/conversations", response_model=list[ConversationSummary])
def list_conversations_endpoint(user_id: str = Depends(get_current_user)):
    convs = storage.list_conversations(user_id)
    return [ConversationSummary(id=c["id"], title=c["title"], created_at=c["created_at"]) for c in convs]


@router.get("/conversations/{conversation_id}/messages")
def get_conversation_messages(conversation_id: str, user_id: str = Depends(get_current_user)):
    conv = storage.get_conversation(conversation_id)
    if not conv or conv["user_id"] != user_id:
        return []
    return storage.get_messages(conversation_id, limit=100)