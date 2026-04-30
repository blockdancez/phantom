"""In-process record of recent scheduler + trigger runs.

Keeps a bounded FIFO of execution metadata per job id so
``GET /api/stats/pipeline`` can report ``last_run / status / duration_ms /
last_error`` even when no persistence layer exists for job runs. Bounded size
prevents unbounded memory growth in long-running processes.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Literal

RunStatus = Literal["success", "failed", "running"]

_MAX_PER_JOB = 20


@dataclass(frozen=True)
class JobRun:
    job_id: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None


_runs: dict[str, deque[JobRun]] = {}
_lock = Lock()


def record_start(job_id: str) -> datetime:
    started = datetime.now(timezone.utc)
    run = JobRun(
        job_id=job_id,
        status="running",
        started_at=started,
        finished_at=None,
        duration_ms=None,
        error=None,
    )
    with _lock:
        _runs.setdefault(job_id, deque(maxlen=_MAX_PER_JOB)).append(run)
    return started


def record_finish(
    job_id: str,
    started_at: datetime,
    *,
    status: RunStatus = "success",
    error: str | None = None,
) -> None:
    finished = datetime.now(timezone.utc)
    duration_ms = int((finished - started_at).total_seconds() * 1000)
    run = JobRun(
        job_id=job_id,
        status=status,
        started_at=started_at,
        finished_at=finished,
        duration_ms=duration_ms,
        error=error,
    )
    with _lock:
        bucket = _runs.setdefault(job_id, deque(maxlen=_MAX_PER_JOB))
        if bucket and bucket[-1].status == "running" and bucket[-1].started_at == started_at:
            bucket[-1] = run
        else:
            bucket.append(run)


def last_run(job_id: str) -> JobRun | None:
    with _lock:
        bucket = _runs.get(job_id)
        if not bucket:
            return None
        return bucket[-1]


def all_last_runs() -> dict[str, JobRun]:
    with _lock:
        return {
            job_id: bucket[-1]
            for job_id, bucket in _runs.items()
            if bucket
        }


def reset() -> None:
    with _lock:
        _runs.clear()
