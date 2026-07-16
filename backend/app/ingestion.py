from __future__ import annotations

import time
import hashlib
import re
import uuid
from collections import defaultdict
from typing import Any

import fitz  # PyMuPDF
from llama_index.core.node_parser import SentenceWindowNodeParser
from llama_index.core.schema import Document as LIDocument
from qdrant_client.http import models as qm
from qdrant_client.http.models import PayloadSchemaType

from . import storage
from .config import get_embed_model, get_qdrant_client, settings

WINDOW_SIZE = 3  

_collection_ready = False

_MIN_SECTION_CHARS = 80  
_SECTION_MAX_CHARS = 1200
_SECTION_OVERLAP = 150


def ensure_collection(force: bool = False) -> None:
    global _collection_ready
    if _collection_ready and not force:
        return

    embed_model = get_embed_model()
    vector_size = len(embed_model.get_text_embedding("hello"))
    client = get_qdrant_client()

    existing = [c.name for c in client.get_collections().collections]

    if settings.qdrant_collection not in existing:
        client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=qm.VectorParams(
                size=vector_size,
                distance=qm.Distance.COSINE,
            ),
        )

    indexes = [
        ("document_id", PayloadSchemaType.KEYWORD),
        ("user_id", PayloadSchemaType.KEYWORD),
        ("content_type", PayloadSchemaType.KEYWORD),
        ("page_number", PayloadSchemaType.INTEGER),
    ]

    for field, schema in indexes:
        try:
            client.create_payload_index(
                collection_name=settings.qdrant_collection,
                field_name=field,
                field_schema=schema,
            )
        except Exception:
            pass

    _collection_ready = True


def _nearest_caption(caption_lines: list[str], img_index_on_page: int) -> str:
    if not caption_lines:
        return ""
    if img_index_on_page < len(caption_lines):
        return caption_lines[img_index_on_page]
    return caption_lines[-1]


def _extract_page_images(pdf) -> dict[int, list[dict]]:
    per_page: dict[int, list[dict]] = {}
    hash_pages: dict[str, set] = defaultdict(set)

    for page_num in range(len(pdf)):
        page = pdf[page_num]
        page_list = []
        for img_meta in page.get_images(full=True):
            xref = img_meta[0]
            try:
                base_image = pdf.extract_image(xref)
            except Exception:
                continue
            image_bytes = base_image["image"]
            img_w, img_h = base_image.get("width") or 0, base_image.get("height") or 0
            if img_w and img_h:
                if img_w < 60 and img_h < 60:
                    continue  
            elif len(image_bytes) < 1500:
                continue
            digest = hashlib.md5(image_bytes).hexdigest()
            hash_pages[digest].add(page_num)
            page_list.append(
                {
                    "bytes": image_bytes,
                    "ext": (base_image.get("ext") or "png").lower(),
                    "hash": digest,
                }
            )
        per_page[page_num] = page_list

    total_pages = len(pdf)
    logo_hashes = {
        h
        for h, pages in hash_pages.items()
        if len(pages) >= 3 or (len(pages) >= 2 and len(pages) >= 0.5 * total_pages)
    }

    return {
        pn: [img for img in imgs if img["hash"] not in logo_hashes]
        for pn, imgs in per_page.items()
    }


def _page_drawing_bbox(page) -> Any:
    drawings = page.get_drawings()
    if not drawings:
        return None
    x0 = y0 = x1 = y1 = None
    for d in drawings:
        r = d.get("rect")
        if not r:
            continue
        if x0 is None:
            x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
        else:
            x0, y0 = min(x0, r.x0), min(y0, r.y0)
            x1, y1 = max(x1, r.x1), max(y1, r.y1)
    if x0 is None:
        return None
    return fitz.Rect(x0, y0, x1, y1)


def _prepare_figure_point(
    user_id: str,
    doc_id: str,
    filename: str,
    page_num: int,
    image_bytes: bytes,
    image_ext: str,
    caption: str,
    current_heading: str,
    page_lines: list[str],
    label: str = "Figure",
) -> dict:
  
    image_id = str(uuid.uuid4())
    storage_path = storage.upload_image(user_id, doc_id, image_id, image_bytes, ext=image_ext)
    page_snippet = " ".join(page_lines[:10])[:400]
    figure_text = " — ".join(
        part
        for part in [
            caption,
            current_heading,
            f"{label} on page {page_num + 1} of {filename}",
            page_snippet,
        ]
        if part
    )
    return {
        "image_id": image_id,
        "figure_text": figure_text,
        "document_id": doc_id,
        "document_name": filename,
        "page_number": page_num + 1,
        "figure_caption": caption,
        "section_heading": current_heading,
        "storage_path": storage_path,
        "image_ext": image_ext,
        "user_id": user_id,
    }


def _save_figure_metadata(pending: list[dict], filename: str) -> None:

    if not pending:
        return
    try:
        storage.save_figures_bulk(pending)
    except Exception as e:
        print(
            f"[ingestion] failed saving figure metadata for {filename} "
            f"({len(pending)} figure(s)): {e}",
            flush=True,
        )


def _detect_section_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 90:
        return False
    words = stripped.split()
    if len(words) > 12:
        return False
    return stripped.isupper() or stripped.istitle()


def _fallback_chunks(text: str, max_chars: int = 900, overlap: int = 150) -> list[str]:
    text = text.strip()
    if not text:
        return []
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        start = end - overlap
    return chunks


def _structure_aware_sections(text_documents: list[LIDocument]) -> list[dict]:
    sections: list[dict] = []

    for doc in text_documents:
        meta = doc.metadata
        lines = [l.strip() for l in doc.text.split("\n") if l.strip()]
        current_heading = meta.get("section_heading", "") or ""
        buf: list[str] = []

        def flush(heading: str) -> None:
            body = " ".join(buf).strip()
            if len(body) < _MIN_SECTION_CHARS:
                return
            pieces = _fallback_chunks(
                body,
                max_chars=_SECTION_MAX_CHARS,
                overlap=_SECTION_OVERLAP,
            ) or [body]
            for piece in pieces:
                sections.append(
                    {
                        "text": piece,
                        "heading": heading,
                        "page_number": meta.get("page_number", 0),
                        "document_name": meta.get("document_name", ""),
                        "source": meta.get("source", "upload"),
                    }
                )

        for line in lines:
            if _detect_section_heading(line):
                flush(current_heading)
                buf = []
                current_heading = line
                continue
            buf.append(line)
        flush(current_heading)

    return sections


def extract_pdf(
    doc_id: str,
    user_id: str,
    filename: str,
    pdf_bytes: bytes,
) -> dict:
    """Extract text + images from a PDF and index into Qdrant.

    Returns summary counts: pages, chunks, figures.
    """

    started = time.perf_counter()

    print(
        f"[ingestion] START {filename} "
        f"({len(pdf_bytes) / 1024:.1f} KB)",
        flush=True,
    )
    # OPEN PDF

    print(
        f"[ingestion] Opening PDF {filename}",
        flush=True,
    )

    pdf = fitz.open(
        stream=pdf_bytes,
        filetype="pdf",
    )

    print(
        f"[ingestion] PDF opened: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )
    # EMBEDDING MODEL

    print(
        "[ingestion] Loading embedding model...",
        flush=True,
    )

    embed_model = get_embed_model()

    print(
        f"[ingestion] Embedding model ready: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    # QDRANT

    print(
        "[ingestion] Creating Qdrant client...",
        flush=True,
    )

    client = get_qdrant_client()

    print(
        f"[ingestion] Qdrant client ready: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    print(
        "[ingestion] Ensuring Qdrant collection...",
        flush=True,
    )

    ensure_collection()

    print(
        f"[ingestion] Qdrant collection ready: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    # INITIALISE EXTRACTION

    text_documents: list[LIDocument] = []
    figure_pending: list[dict] = []
    current_heading = ""
    num_figures = 0

    # IMAGE SCAN
    print(
        "[ingestion] Scanning PDF images...",
        flush=True,
    )

    page_images_by_page = _extract_page_images(pdf)

    print(
        f"[ingestion] Image scan complete for {filename}: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    # PAGE EXTRACTION
  
    print(
        f"[ingestion] Extracting {len(pdf)} PDF pages...",
        flush=True,
    )

    for page_num in range(len(pdf)):
        page = pdf[page_num]

        page_text = page.get_text("text")

        lines = [
            line
            for line in page_text.split("\n")
            if line.strip()
        ]

        for line in lines:
            if _detect_section_heading(line):
                current_heading = line.strip()
                break

        if page_text.strip():
            text_documents.append(
                LIDocument(
                    text=page_text,
                    metadata={
                        "document_id": doc_id,
                        "document_name": filename,
                        "page_number": page_num + 1,
                        "content_type": "text",
                        "section_heading": current_heading,
                        "source": "upload",
                    },
                )
            )
        # IMAGE METADATA


        caption_lines = [
            line.strip()
            for line in lines
            if re.match(
                r"^(figure|fig\.?)\s*\d+",
                line.strip(),
                re.IGNORECASE,
            )
        ]

        page_images = page_images_by_page.get(
            page_num,
            [],
        )

        raster_figures_this_page = 0

        for img_index_on_page, img in enumerate(
            page_images
        ):
            image_bytes = img["bytes"]
            image_ext = img["ext"]

            caption = _nearest_caption(
                caption_lines,
                img_index_on_page,
            )

            figure_pending.append(
                _prepare_figure_point(
                    user_id,
                    doc_id,
                    filename,
                    page_num,
                    image_bytes,
                    image_ext,
                    caption,
                    current_heading,
                    lines,
                    label="Figure",
                )
            )

            num_figures += 1
            raster_figures_this_page += 1

        # VECTOR DIAGRAM FALLBACK
        if raster_figures_this_page == 0:
            try:
                drawings = page.get_drawings()
                bbox = _page_drawing_bbox(page)

                if (
                    bbox is not None
                    and len(drawings) >= 4
                    and bbox.width > 40
                    and bbox.height > 40
                    and (bbox.width * bbox.height) > 6000
                ):
                    margin = 15

                    px0 = max(
                        page.rect.x0,
                        bbox.x0 - margin,
                    )

                    py0 = max(
                        page.rect.y0,
                        bbox.y0 - margin,
                    )

                    px1 = min(
                        page.rect.x1,
                        bbox.x1 + margin,
                    )

                    py1 = min(
                        page.rect.y1,
                        bbox.y1 + margin,
                    )

                    bbox = fitz.Rect(
                        px0,
                        py0,
                        px1,
                        py1,
                    )

                    pix = page.get_pixmap(
                        clip=bbox,
                        dpi=150,
                    )

                    image_bytes = pix.tobytes("png")

                    if len(image_bytes) >= 1500:
                        caption = (
                            caption_lines[0]
                            if caption_lines
                            else ""
                        )

                        figure_pending.append(
                            _prepare_figure_point(
                                user_id,
                                doc_id,
                                filename,
                                page_num,
                                image_bytes,
                                "png",
                                caption,
                                current_heading,
                                lines,
                                label="Figure (diagram)",
                            )
                        )

                        num_figures += 1

            except Exception as e:
                print(
                    f"[ingestion] vector-diagram "
                    f"capture failed on page "
                    f"{page_num + 1} of "
                    f"{filename}: {e}",
                    flush=True,
                )

    num_pages = len(pdf)

    pdf.close()

    print(
        f"[ingestion] Page extraction complete: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    if figure_pending:
        print(
            f"[ingestion] Saving metadata for {len(figure_pending)} "
            f"figure(s) in {filename}",
            flush=True,
        )

    _save_figure_metadata(figure_pending, filename)

    # SENTENCE WINDOW PARSING
    print(
        "[ingestion] Starting sentence-window parsing...",
        flush=True,
    )

    parser = SentenceWindowNodeParser.from_defaults(
        window_size=WINDOW_SIZE,
        window_metadata_key="window",
        original_text_metadata_key="original_text",
    )

    try:
        nodes = (
            parser.get_nodes_from_documents(
                text_documents
            )
            if text_documents
            else []
        )

    except Exception as e:
        print(
            f"[ingestion] sentence-window parsing "
            f"failed for {filename}: {e}",
            flush=True,
        )

        nodes = []

    print(
        f"[ingestion] Sentence parsing complete: "
        f"{len(nodes)} nodes — "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    # TEXT ITEMS
    text_points: list[qm.PointStruct] = []
    text_items: list[dict] = []

    if text_documents and not nodes:
        print(
            f"[ingestion] {filename}: sentence parser "
            f"produced 0 nodes from "
            f"{len(text_documents)} page(s) with text "
            f"— using fallback chunking",
            flush=True,
        )

        for doc in text_documents:
            for piece in _fallback_chunks(doc.text):
                text_items.append(
                    {
                        "text": piece,
                        "window": piece,
                        "document_name": (
                            doc.metadata.get(
                                "document_name",
                                filename,
                            )
                        ),
                        "page_number": (
                            doc.metadata.get(
                                "page_number",
                                0,
                            )
                        ),
                        "section_heading": (
                            doc.metadata.get(
                                "section_heading",
                                "",
                            )
                        ),
                        "source": "upload",
                        "chunking_strategy": (
                            "fixed_overlap"
                        ),
                    }
                )

    else:
        for node in nodes:
            sentence = node.get_content()
            meta = node.metadata

            text_items.append(
                {
                    "text": sentence,
                    "window": meta.get(
                        "window",
                        sentence,
                    ),
                    "document_name": meta.get(
                        "document_name",
                        filename,
                    ),
                    "page_number": meta.get(
                        "page_number",
                        0,
                    ),
                    "section_heading": meta.get(
                        "section_heading",
                        "",
                    ),
                    "source": meta.get(
                        "source",
                        "upload",
                    ),
                    "chunking_strategy": (
                        "sentence_window"
                    ),
                }
            )
    # BATCH TEXT EMBEDDING
    if text_items:
        print(
            f"[ingestion] Embedding "
            f"{len(text_items)} text chunks "
            f"for {filename}",
            flush=True,
        )

        texts = [
            (f"{item['section_heading']}. {item['text']}" if item["section_heading"] else item["text"])
            for item in text_items
        ]

        vectors = (
            embed_model.get_text_embedding_batch(
                texts,
                show_progress=False,
            )
        )

        print(
            f"[ingestion] Text embeddings complete: "
            f"{time.perf_counter() - started:.2f}s",
            flush=True,
        )

        for item, vector in zip(
            text_items,
            vectors,
        ):
            chunk_id = str(uuid.uuid4())

            text_points.append(
                qm.PointStruct(
                    id=chunk_id,
                    vector=vector,
                    payload={
                        "text": item["text"],
                        "window": item["window"],
                        "document_id": doc_id,
                        "document_name": item[
                            "document_name"
                        ],
                        "page_number": item[
                            "page_number"
                        ],
                        "chunk_id": chunk_id,
                        "content_type": "text",
                        "section_heading": item[
                            "section_heading"
                        ],
                        "source": item["source"],
                        "user_id": user_id,
                        "chunking_strategy": item[
                            "chunking_strategy"
                        ],
                    },
                )
            )

    # STRUCTURE-AWARE EMBEDDING

    structure_points: list[qm.PointStruct] = []

    if text_documents:
        try:
            sections = _structure_aware_sections(
                text_documents
            )

            if sections:
                print(
                    f"[ingestion] Embedding "
                    f"{len(sections)} structure chunks "
                    f"for {filename}",
                    flush=True,
                )

                section_texts = [
                    (f"{sec['heading']}. {sec['text']}" if sec["heading"] else sec["text"])
                    for sec in sections
                ]

                section_vectors = (
                    embed_model
                    .get_text_embedding_batch(
                        section_texts,
                        show_progress=False,
                    )
                )

                print(
                    f"[ingestion] Structure embeddings "
                    f"complete: "
                    f"{time.perf_counter() - started:.2f}s",
                    flush=True,
                )

                for sec, vector in zip(
                    sections,
                    section_vectors,
                ):
                    chunk_id = str(uuid.uuid4())

                    structure_points.append(
                        qm.PointStruct(
                            id=chunk_id,
                            vector=vector,
                            payload={
                                "text": sec["text"],
                                "window": sec["text"],
                                "document_id": doc_id,
                                "document_name": (
                                    sec["document_name"]
                                    or filename
                                ),
                                "page_number": sec[
                                    "page_number"
                                ],
                                "chunk_id": chunk_id,
                                "content_type": "text",
                                "section_heading": sec[
                                    "heading"
                                ],
                                "source": sec["source"],
                                "user_id": user_id,
                                "chunking_strategy": (
                                    "structure_aware"
                                ),
                            },
                        )
                    )

        except Exception as e:
            print(
                f"[ingestion] structure-aware "
                f"chunking failed for "
                f"{filename}: {e}",
                flush=True,
            )

            structure_points = []


    # QDRANT POINTS
    all_points = (
        text_points
        + structure_points
    )

    if not all_points and not figure_pending:
        print(
            f"[ingestion] WARNING: {filename} "
            f"produced 0 text chunks and 0 figures "
            f"from {num_pages} page(s) — "
            f"nothing will be retrievable.",
            flush=True,
        )

    print(
        f"[ingestion] Prepared {len(all_points)} "
        f"points for {filename}: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )
    # QDRANT UPSERT

    if all_points:
        BATCH = 128

        print(
            f"[ingestion] Starting Qdrant upsert "
            f"for {len(all_points)} points...",
            flush=True,
        )

        for i in range(
            0,
            len(all_points),
            BATCH,
        ):
            batch = all_points[
                i:i + BATCH
            ]

            try:
                client.upsert(
                    collection_name=(
                        settings.qdrant_collection
                    ),
                    points=batch,
                )

                print(
                    f"[ingestion] Qdrant batch "
                    f"{i // BATCH + 1} complete",
                    flush=True,
                )

            except Exception as e:
                print(
                    f"[ingestion] Qdrant upsert "
                    f"failed for {filename} "
                    f"(batch "
                    f"{i // BATCH + 1}): {e}",
                    flush=True,
                )

                raise

    # ---------------------------------------------------------
    # COMPLETE
    # ---------------------------------------------------------

    print(
        f"[ingestion] COMPLETE {filename}: "
        f"{time.perf_counter() - started:.2f}s",
        flush=True,
    )

    return {
        "num_pages": num_pages,
        "num_chunks": (
            len(text_points)
            + len(structure_points)
        ),
        "num_figures": num_figures,
    }


def delete_document_vectors(doc_id: str) -> None:
    client = get_qdrant_client()
    client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=qm.FilterSelector(
            filter=qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="document_id",
                        match=qm.MatchValue(value=doc_id),
                    )
                ]
            )
        ),
    )