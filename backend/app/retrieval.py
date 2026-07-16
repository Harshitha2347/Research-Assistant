from __future__ import annotations

import re
from typing import Optional

from qdrant_client.http import models as qm
from rank_bm25 import BM25Okapi

from .config import get_embed_model, get_groq_client, get_qdrant_client, get_reranker, settings
from .models import RetrievedChunk

CANDIDATE_POOL = 25
FINAL_TOP_K = 6
RERANK_TRIGGER_POOL = FINAL_TOP_K + 2 
# If the original query's own top vector match doesn't clear this, the
# question likely covers more ground than one embedding represents well
# (see _decompose_query) — e.g. a question comparing two named things
# blends both into a single vector and dilutes the match to either one.
DECOMPOSE_TRIGGER_SCORE = 0.55


def _decompose_query(query: str) -> list[str]:
    """Asks the LLM to split a question into up to 3 short, focused search
    phrases — e.g. a question comparing two things becomes one phrase per
    thing. This replaces guessing at "multi-part-ness" from surface
    patterns like capitalization or an English stopword list: the LLM
    reads what the question actually means and produces whatever
    sub-queries make sense for it, regardless of language, capitalization,
    or how many things are being asked about. Only called when the
    original query's own retrieval already looks weak (see retrieve()),
    so this doesn't add a call on every request."""
    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Break the question below into up to 3 short, focused "
                        "search phrases that together would retrieve everything "
                        "needed to answer it (e.g. a question comparing two "
                        "things becomes one phrase per thing). If it's already "
                        "one focused topic, return just that one phrase, "
                        "reworded as a short search query. Return one phrase per "
                        "line, nothing else.\n\nQuestion: " + query
                    ),
                }
            ],
            temperature=0,
            max_tokens=60,
        )
        lines = [l.strip("-• ").strip() for l in resp.choices[0].message.content.split("\n") if l.strip()]
        return lines[:3]
    except Exception:
        return []



def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9]+", text.lower())


def needs_query_expansion(query: str) -> bool:
    words = query.strip().split()
    return len(words) <= 6 or "?" not in query


def expand_query(query: str) -> list[str]:
    """One cheap Groq call producing 2 paraphrases, only used when needed."""
    try:
        client = get_groq_client()
        resp = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Rewrite the following search query as 2 short alternative "
                        "phrasings that capture the same intent. Return exactly 2 "
                        "lines, no numbering, no extra text.\nQuery: " + query
                    ),
                }
            ],
            temperature=0.3,
            max_tokens=80,
        )
        lines = [l.strip("- ").strip() for l in resp.choices[0].message.content.split("\n") if l.strip()]
        return lines[:2]
    except Exception:
        return []


def _vector_search(query_vector: list[float], doc_filter: Optional[list[str]], limit: int):
    client = get_qdrant_client()
    must = [qm.FieldCondition(key="content_type", match=qm.MatchValue(value="text"))]
    if doc_filter:
        must.append(qm.FieldCondition(key="document_id", match=qm.MatchAny(any=doc_filter)))
    try:
        return client.search(
            collection_name=settings.qdrant_collection,
            query_vector=query_vector,
            query_filter=qm.Filter(must=must),
            limit=limit,
            with_payload=True,
        )
    except Exception as e:
       
        print(f"[retrieval] vector search failed, continuing without it: {e}")
        return []


def _fetch_corpus_for_bm25(doc_filter: Optional[list[str]], limit: int = 500):
   
    client = get_qdrant_client()
    must = [qm.FieldCondition(key="content_type", match=qm.MatchValue(value="text"))]
    if doc_filter:
        must.append(qm.FieldCondition(key="document_id", match=qm.MatchAny(any=doc_filter)))
    try:
        points, _ = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=qm.Filter(must=must),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        return points
    except Exception as e:
        
        print(f"[retrieval] BM25 corpus fetch failed, continuing with vector-only results: {e}")
        return []


RRF_K = 60


def _reciprocal_rank_fusion(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return scores


def _normalize_rrf_scores(fused: dict[str, float], num_rankings: int) -> dict[str, float]:
    
    if not fused or num_rankings <= 0:
        return {}
    max_possible = num_rankings * (1.0 / (RRF_K + 1))
    if max_possible <= 0:
        return fused
    return {pid: min(1.0, score / max_possible) for pid, score in fused.items()}


def _contextual_compress(window: str, query_vec: list[float], embed_model) -> str:

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", window) if s.strip()]
    if len(sentences) <= 3:
        return window
    import numpy as np

    # One batched call for all sentences in this window, instead of one
    # network round-trip per sentence — the latter is fine for an
    # in-process local model but far too slow once embeddings are a
    # hosted API call.
    sent_vecs = embed_model.get_text_embedding_batch(sentences)
    sims = [float(np.dot(query_vec, v) / ((np.linalg.norm(query_vec) * np.linalg.norm(v)) + 1e-8)) for v in sent_vecs]
    ranked = sorted(zip(sentences, sims), key=lambda x: x[1], reverse=True)
    keep = sorted(ranked[: min(5, len(ranked))], key=lambda x: sentences.index(x[0]))
    return " ".join(s for s, _ in keep)


_VISUAL_QUERY_PATTERN = re.compile(
    r"\b(figures?|fig\.?s?|images?|diagrams?|charts?|graphs?|plots?|pictures?|"
    r"photos?|screenshots?|illustrations?|visual\w*|tables?|schematics?|"
    r"snapshots?|shown|depicts?|trend\w*|curves?)\b",
    re.IGNORECASE,
)


def query_mentions_visual(query: str) -> bool:
    
    return bool(_VISUAL_QUERY_PATTERN.search(query))


def retrieve_figures(query: str, document_ids: Optional[list[str]], limit: int = 3) -> list[RetrievedChunk]:
    """Figures are stored as plain metadata rows, not Qdrant vectors (see
    storage.save_figures_bulk / ingestion._save_figure_metadata) — nothing
    gets embedded at upload time. This shortlists candidates with a cheap,
    local keyword-overlap score against each figure's caption/heading/page
    text, with no network or API call involved. Actually reading what's in
    the image (the expensive part) only happens afterwards, in
    chat._analyse_figures, and only for whichever figures make this
    shortlist — i.e. only when the user's question is actually about one."""
    from . import storage

    rows = storage.list_figures(document_ids)
    if not rows:
        return []

    query_tokens = set(_tokenize(query))

    def _keyword_score(row: dict) -> float:
        haystack = f"{row.get('figure_caption') or ''} {row.get('section_heading') or ''} {row.get('figure_text') or ''}"
        row_tokens = set(_tokenize(haystack))
        if not query_tokens or not row_tokens:
            return 0.0
        return len(query_tokens & row_tokens) / len(query_tokens)

    scored = sorted(rows, key=_keyword_score, reverse=True)[:limit]

    results: list[RetrievedChunk] = []
    for row in scored:
        results.append(
            RetrievedChunk(
                text=row.get("figure_text", ""),
                score=_keyword_score(row),
                document_name=row.get("document_name", ""),
                page_number=row.get("page_number", 0),
                chunk_id=row.get("id", ""),
                content_type="figure",
                image_id=row.get("id"),
                figure_caption=row.get("figure_caption"),
                section_heading=row.get("section_heading"),
                storage_path=row.get("storage_path"),
                image_ext=row.get("image_ext"),
            )
        )
    return results


MAX_PER_SECTION = 2  # cap near-duplicate windows from the same resume
# section/project so a broad query ("what projects did X do") isn't
# crowded out by several overlapping windows of one project alone.

# If the top-ranked candidates agree on a document at least this often,
# treat the query as being about that one document and don't let the
# diversity backfill below cross into another uploaded document.
DOMINANT_DOC_THRESHOLD = 0.6
DOMINANT_DOC_SAMPLE = 5


def _dominant_document_id(ranked_pids: list[str], payload_by_id: dict[str, dict]) -> Optional[str]:
    """Best guess at which single uploaded document the query is about,
    from a majority vote over the top few ranked candidates. Multiple
    documents (e.g. two people's resumes) can each contain a similarly
    -worded "projects" section, so once results are diversified across
    sections there's nothing stopping that backfill from reaching into a
    different document/person entirely. Returns None (no restriction) for
    genuinely cross-document queries, where top candidates split roughly
    evenly rather than clustering on one document."""
    sample = [
        payload_by_id.get(pid, {}).get("document_id")
        for pid in ranked_pids[:DOMINANT_DOC_SAMPLE]
    ]
    sample = [d for d in sample if d]
    if not sample:
        return None
    from collections import Counter

    doc_id, count = Counter(sample).most_common(1)[0]
    if count / len(sample) >= DOMINANT_DOC_THRESHOLD:
        return doc_id
    return None


def _diversify_by_section(
    ranked_pids: list[str],
    payload_by_id: dict[str, dict],
    k: int,
    max_per_section: int = MAX_PER_SECTION,
    allow_cross_document_narrowing: bool = True,
) -> list[str]:
    """Greedily keep the top-k ids in ranked order, but cap how many can
    share a section_heading. Sentence-window / structure-aware chunking
    produces several overlapping windows per section (e.g. per project in
    a resume) — for a broad query these can all rank near the top and
    crowd out every other section, so a "what projects did X do" answer
    ends up describing one project three times instead of listing several.

    When one document clearly dominates the top results, candidates are
    exhausted within that document first (still respecting the per-section
    cap) before ever backfilling from another document — otherwise the
    backfill that fixes repetition ends up pulling in another uploaded
    document's (e.g. a different person's) similarly-worded section
    instead. This narrowing only applies when `allow_cross_document_narrowing`
    is True, i.e. the caller didn't already explicitly scope retrieval to
    specific document(s) — if the user explicitly selected several
    documents, that selection IS the scope, and this must not narrow it
    down further to whichever one document happens to rank higher (e.g.
    "where did Jasin do his internships?" with both Jasin's and
    Harshitha's resumes selected must still be able to answer from
    Jasin's document even if Harshitha's ranks higher overall).
    """
    dominant_doc = (
        _dominant_document_id(ranked_pids, payload_by_id) if allow_cross_document_narrowing else None
    )
    if dominant_doc:
        same_doc = [pid for pid in ranked_pids if payload_by_id.get(pid, {}).get("document_id") == dominant_doc]
        other_doc = [pid for pid in ranked_pids if payload_by_id.get(pid, {}).get("document_id") != dominant_doc]
        ordered = same_doc + other_doc
    else:
        ordered = ranked_pids

    picked: list[str] = []
    per_section: dict[str, int] = {}
    leftover: list[str] = []
    for pid in ordered:
        section = payload_by_id.get(pid, {}).get("section_heading") or pid
        if per_section.get(section, 0) < max_per_section:
            picked.append(pid)
            per_section[section] = per_section.get(section, 0) + 1
        else:
            leftover.append(pid)
        if len(picked) >= k:
            return picked[:k]
    # Not enough distinct sections to fill k slots on their own — backfill
    # the remainder from whatever got capped, in original rank order.
    picked.extend(leftover[: max(0, k - len(picked))])
    return picked[:k]


def retrieve(query: str, document_ids: Optional[list[str]] = None) -> list[RetrievedChunk]:
   
    embed_model = get_embed_model()
    query_vec = embed_model.get_query_embedding(query)

    queries = [query]
    if needs_query_expansion(query):
        queries.extend(expand_query(query))

    # ---- vector search across original + expanded queries ----
    # Embed every non-original query in one batched call rather than
    # looping get_query_embedding() per query (each is now a network
    # round-trip to the Gemini API, not a free in-process lookup).
    extra_queries = queries[1:]
    extra_vecs = embed_model.get_query_embedding_batch(extra_queries) if extra_queries else []
    query_vecs_by_text = dict(zip(extra_queries, extra_vecs))
    query_vecs_by_text[query] = query_vec

    vector_hits_by_query = []
    for q in queries:
        vector_hits_by_query.append(_vector_search(query_vecs_by_text[q], document_ids, CANDIDATE_POOL))

    # If the original query's own top vector match is weak, it likely
    # covers more ground than one embedding represents well — e.g. a
    # question comparing two named things blends both into one vector and
    # dilutes the match to either. Ask the LLM to split it into whatever
    # focused sub-queries actually make sense (no assumption about
    # language, capitalization, or how many things are being asked about)
    # and search each of those too.
    original_hits = vector_hits_by_query[0]
    top_vector_score = original_hits[0].score if original_hits else 0.0
    if top_vector_score < DECOMPOSE_TRIGGER_SCORE:
        sub_queries = [
            sub_q for sub_q in _decompose_query(query)
            if sub_q and sub_q.lower() not in {q.lower() for q in queries}
        ]
        if sub_queries:
            sub_vecs = embed_model.get_query_embedding_batch(sub_queries)
            for sub_q, sub_vec in zip(sub_queries, sub_vecs):
                queries.append(sub_q)
                vector_hits_by_query.append(_vector_search(sub_vec, document_ids, CANDIDATE_POOL))

    payload_by_id: dict[str, dict] = {}
    vector_rankings: list[list[str]] = []
    for hits in vector_hits_by_query:
        ranking = []
        for h in hits:
            payload_by_id[str(h.id)] = h.payload
            ranking.append(str(h.id))
        vector_rankings.append(ranking)

    # ---- BM25 over bounded corpus slice ----
    corpus_points = _fetch_corpus_for_bm25(document_ids)
    bm25_ranking: list[str] = []
    if corpus_points:
        # Include each chunk's section heading alongside its body text —
        # this is where a person's name (e.g. "Harshitha R") typically
        # lives (see _detect_section_heading in ingestion.py), and a bare
        # sentence like "Worked as a Data Science Intern..." often doesn't
        # repeat the name itself. Without this, BM25 can't tell which
        # person's chunk is being asked about by name, and can rank a
        # different person's similarly-worded chunk just as highly.
        tokenized = [
            _tokenize(f"{p.payload.get('section_heading', '')} {p.payload.get('text', '')}")
            for p in corpus_points
        ]
        bm25 = BM25Okapi(tokenized)
        scores = bm25.get_scores(_tokenize(query))
        order = sorted(range(len(corpus_points)), key=lambda i: scores[i], reverse=True)[:CANDIDATE_POOL]
        for i in order:
            p = corpus_points[i]
            payload_by_id[str(p.id)] = p.payload
            bm25_ranking.append(str(p.id))

    all_rankings = vector_rankings + [bm25_ranking]
    fused = _reciprocal_rank_fusion(all_rankings)
    fused_sorted = sorted(fused.items(), key=lambda x: x[1], reverse=True)
    pool_ids = [pid for pid, _ in fused_sorted[:CANDIDATE_POOL]]

    if not pool_ids:
        vec_counts = [len(r) for r in vector_rankings]
        print(
            f"[retrieval] 0 results for query={query!r} document_ids={document_ids} — "
            f"vector hits per query={vec_counts}, bm25 hits={len(bm25_ranking)}, "
            f"corpus scanned={len(corpus_points)}. If this document was just "
            f"uploaded, check the [ingestion] logs for it — most likely cause is "
            f"0 chunks were ever indexed for the filtered document_id(s)."
        )

    # A document scope was explicitly selected (one or more specific
    # documents checked) — that selection already IS the scope, so
    # diversification must be free to draw from all of them and must not
    # further narrow down to whichever one ranks higher (see
    # _diversify_by_section). The dominant-document narrowing only makes
    # sense when there was no explicit scope at all (searching everything
    # uploaded), to stop an unrelated document's similarly-worded section
    # from sneaking into the answer.
    allow_cross_document_narrowing = not document_ids

    # ---- cross-encoder reranking (runs whenever there's a real pool) ----
    if len(pool_ids) >= RERANK_TRIGGER_POOL:
        try:
            reranker = get_reranker()
            pairs = [[query, payload_by_id[pid].get("text", "")] for pid in pool_ids]
            rerank_scores = reranker.compute_score(pairs, normalize=True)
            if isinstance(rerank_scores, float):
                rerank_scores = [rerank_scores]
            ranked = sorted(zip(pool_ids, rerank_scores), key=lambda x: x[1], reverse=True)
            score_by_id = {pid: s for pid, s in ranked}
            top_ids = _diversify_by_section(
                [pid for pid, _ in ranked], payload_by_id, FINAL_TOP_K,
                allow_cross_document_narrowing=allow_cross_document_narrowing,
            )
            top_scores = {pid: score_by_id[pid] for pid in top_ids}
        except Exception as e:
           
            print(f"[retrieval] cross-encoder reranking failed, falling back to RRF order: {e}")
            normalized = _normalize_rrf_scores(fused, len(all_rankings))
            top_ids = _diversify_by_section(
                pool_ids, payload_by_id, FINAL_TOP_K,
                allow_cross_document_narrowing=allow_cross_document_narrowing,
            )
            top_scores = {pid: normalized.get(pid, 0.0) for pid in top_ids}
    else:
       
        normalized = _normalize_rrf_scores(fused, len(all_rankings))
        top_ids = _diversify_by_section(
            pool_ids, payload_by_id, FINAL_TOP_K,
            allow_cross_document_narrowing=allow_cross_document_narrowing,
        )
        top_scores = {pid: normalized.get(pid, 0.0) for pid in top_ids}

    results: list[RetrievedChunk] = []
    for pid in top_ids:
        payload = payload_by_id[pid]
        content_type = payload.get("content_type", "text")
        text = payload.get("window") or payload.get("text", "")
        if content_type == "text":
            text = _contextual_compress(text, query_vec, embed_model)
        results.append(
            RetrievedChunk(
                text=text,
                score=float(top_scores.get(pid, 0.0)),
                document_name=payload.get("document_name", ""),
                page_number=payload.get("page_number", 0),
                chunk_id=payload.get("chunk_id", pid),
                content_type=content_type,
                image_id=payload.get("image_id"),
                figure_caption=payload.get("figure_caption"),
                section_heading=payload.get("section_heading"),
                storage_path=payload.get("storage_path"),
            )
        )
    return results