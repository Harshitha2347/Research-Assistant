
from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional


_executor = ThreadPoolExecutor(max_workers=6, thread_name_prefix="bg-job")

_jobs: dict[str, dict[str, Any]] = {}
_lock = threading.Lock()

_JOB_TTL_SECONDS = 60 * 60


def _prune_locked() -> None:
    cutoff = time.time() - _JOB_TTL_SECONDS
    stale = [jid for jid, job in _jobs.items() if job.get("updated_at", 0) < cutoff]
    for jid in stale:
        _jobs.pop(jid, None)


def create_job(kind: str, meta: Optional[dict] = None) -> str:
    """Registers a new job in the 'running' state and returns its id."""
    job_id = str(uuid.uuid4())
    now = time.time()
    with _lock:
        _prune_locked()
        _jobs[job_id] = {
            "id": job_id,
            "kind": kind,
            "status": "running",
            "result": None,
            "error": None,
            "meta": meta or {},
            "cancel_requested": False,
            "created_at": now,
            "updated_at": now,
        }
    return job_id


def get_job(job_id: str) -> Optional[dict]:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def request_cancel(job_id: str) -> bool:
   
    with _lock:
        job = _jobs.get(job_id)
        if not job or job["status"] != "running":
            return False
        job["cancel_requested"] = True
        job["updated_at"] = time.time()
        return True


def is_cancelled(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        return bool(job and job.get("cancel_requested"))


def _finish(job_id: str, *, status: str, result: Any = None, error: Optional[str] = None) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if job is None:
            return
        job["status"] = status
        job["result"] = result
        job["error"] = error
        job["updated_at"] = time.time()


def run_in_background(job_id: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:

    def _runner() -> None:
        try:
            result = fn(*args, **kwargs)
            with _lock:
                job = _jobs.get(job_id)
                cancelled = bool(job and job.get("cancel_requested"))
            _finish(job_id, status="cancelled" if cancelled else "done", result=result)
        except Exception as e:  # noqa: BLE001 — surfaced via job status, not raised
            traceback.print_exc()
            _finish(job_id, status="error", error=str(e) or e.__class__.__name__)

    _executor.submit(_runner)


def submit_background(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:

    def _runner() -> None:
        try:
            fn(*args, **kwargs)
        except Exception:
            traceback.print_exc()

    _executor.submit(_runner)
