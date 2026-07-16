
from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException

from . import jobs, storage
from .auth import get_current_user
from .config import settings
from .models import EvaluationRequest, EvaluationResult
from .retrieval import retrieve

router = APIRouter(prefix="/evaluation", tags=["evaluation"])

METRIC_KEYS = ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


def _build_dataset(
    conversation_id: str,
    pair_indices: list[int] | None = None,
):

    from datasets import Dataset

    messages = storage.get_messages(conversation_id, limit=100)

    questions = []
    answers = []
    contexts = []
    ground_truths = []
    included_indices: list[int] = []

    pair_number = 0

    for i in range(len(messages) - 1):
        if (
            messages[i]["role"] == "user"
            and messages[i + 1]["role"] == "assistant"
        ):
            if pair_indices is not None and pair_number not in pair_indices:
                pair_number += 1
                continue

            question = messages[i]["content"]
            assistant_msg = messages[i + 1]
            answer = assistant_msg["content"]

            stored_contexts = assistant_msg.get("contexts") or []
            if stored_contexts:
                retrieved_contexts = list(stored_contexts)
            else:
            
                retrieved = retrieve(question)
                retrieved_contexts = [c.text for c in retrieved if c.content_type == "text"]

            if not retrieved_contexts:
                retrieved_contexts = [answer]

            questions.append(question)
            answers.append(answer)
            contexts.append(retrieved_contexts)
            ground_truths.append(answer)
            included_indices.append(pair_number)

            pair_number += 1

    dataset = Dataset.from_dict(
        {
            "question": questions,
            "answer": answers,
            "contexts": contexts,
            "ground_truth": ground_truths,
        }
    )
    return dataset, included_indices


def run_ragas(
    conversation_id: str,
    pair_indices: list[int] | None = None,
    job_id: str | None = None,
):

    from ragas import evaluate
    from ragas.run_config import RunConfig
    from ragas.metrics import (
        faithfulness,
        answer_relevancy,
        context_precision,
        context_recall,
    )
    from ragas.llms import LangchainLLMWrapper
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from langchain_groq import ChatGroq
    from .gemini_embedding import GeminiLangchainEmbeddings

    answer_relevancy.strictness = 1

    dataset, included_indices = _build_dataset(conversation_id, pair_indices)

    if len(dataset) == 0:
        raise HTTPException(
            status_code=400,
            detail="No completed conversations found.",
        )


    llm = LangchainLLMWrapper(
        ChatGroq(
            model=settings.groq_model,
            api_key=settings.groq_api_key,
            temperature=0,
        )
    )

    embeddings = LangchainEmbeddingsWrapper(
        GeminiLangchainEmbeddings(
            api_key=settings.gemini_api_key,
            model_name=settings.embedding_model,
            output_dimensionality=settings.embedding_output_dim,
        )
    )

  
    per_pair_scores: list[dict] = []
    for i in range(len(dataset)):
        if job_id and jobs.is_cancelled(job_id):
            break

        row_dataset = dataset.select([i])
        result = evaluate(
            dataset=row_dataset,
            metrics=[
                faithfulness,
                answer_relevancy,
                context_precision,
                context_recall,
            ],
            llm=llm,
            embeddings=embeddings,
            run_config=RunConfig(max_workers=2, timeout=120),
        )
        df = result.to_pandas()
        row_scores = {key: float(df[key].iloc[0]) for key in METRIC_KEYS}
        for key, value in row_scores.items():
            if math.isnan(value):
               
    
                print(
                    f"[evaluation] {key} came back NaN (judge-LLM call failed to "
                    f"parse/compute) for conversation={conversation_id} pair={included_indices[len(per_pair_scores)]}"
                )
        per_pair_scores.append(row_scores)

    completed_indices = included_indices[: len(per_pair_scores)]

    if not per_pair_scores:
        return None, completed_indices

    def _mean_ignoring_nan(values: list[float]) -> float:
       
        valid = [v for v in values if not math.isnan(v)]
        return sum(valid) / len(valid) if valid else float("nan")

    scores = {
        key: _mean_ignoring_nan([p[key] for p in per_pair_scores])
        for key in METRIC_KEYS
    }
    return scores, completed_indices


@router.post("/run")
def run_evaluation(
    req: EvaluationRequest,
    user_id: str = Depends(get_current_user),
):
  
    conv = storage.get_conversation(req.conversation_id)

    if not conv or conv["user_id"] != user_id:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found",
        )

    normalized_pairs = sorted(set(req.pair_indices)) if req.pair_indices else None

    if normalized_pairs:
       
        existing = storage.find_existing_evaluation(req.conversation_id, normalized_pairs)
        if existing:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This exact set of {len(normalized_pairs)} Q&A pair(s) was already "
                    "evaluated for this conversation — see it in History below, or select "
                    "a different set of pairs."
                ),
            )

    job_id = jobs.create_job(
        "evaluation",
        meta={"conversation_id": req.conversation_id, "pair_indices": normalized_pairs},
    )

    def _task():
        scores, completed_indices = run_ragas(req.conversation_id, req.pair_indices, job_id)
        if not scores:
            # Cancelled before any pair finished — nothing worth saving.
            return {"cancelled": True}
        return storage.save_evaluation(req.conversation_id, scores, completed_indices)

    jobs.run_in_background(job_id, _task)
    return {"job_id": job_id}


@router.post("/jobs/{job_id}/cancel")
def cancel_evaluation_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
):

    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    ok = jobs.request_cancel(job_id)
    return {"cancelled": ok}


@router.get("/jobs/{job_id}")
def get_evaluation_job(
    job_id: str,
    user_id: str = Depends(get_current_user),
):
    job = jobs.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/history", response_model=list[EvaluationResult])
def evaluation_history(
    user_id: str = Depends(get_current_user),
):
    return [
        EvaluationResult(**e)
        for e in storage.list_evaluations(user_id)
    ]


@router.get("/pairs/{conversation_id}")
def get_conversation_pairs(
    conversation_id: str,
    user_id: str = Depends(get_current_user),
):
    conv = storage.get_conversation(conversation_id)

    if not conv or conv["user_id"] != user_id:
        raise HTTPException(404, "Conversation not found")

    messages = storage.get_messages(conversation_id, limit=100)

    pairs = []

    idx = 0

    for i in range(len(messages) - 1):
        if (
            messages[i]["role"] == "user"
            and messages[i + 1]["role"] == "assistant"
        ):
            pairs.append(
                {
                    "index": idx,
                    "question": messages[i]["content"],
                    "answer": messages[i + 1]["content"][:150],
                }
            )

            idx += 1

    return pairs
