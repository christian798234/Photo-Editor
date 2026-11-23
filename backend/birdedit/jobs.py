"""Background jobs with progress, per-item results and cancellation.

Two worker pools keep the UI responsive while bounding memory:
* ``import``: half-size RAW decodes for previews (1 worker by default)
* ``heavy``:  full-resolution work such as export (1 worker by default)

Cancellation is cooperative: jobs check ``cancelled`` between safe stages
(between files, between pipeline stages, between export tiles).
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable

from .config import FULL_RES_WORKERS, IMPORT_WORKERS

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    kind: str
    title: str
    total: int
    done: int = 0
    status: str = "queued"          # queued | running | done | cancelled | failed
    message: str = ""
    item_progress: float = 0.0
    results: list[dict] = field(default_factory=list)
    created: float = field(default_factory=time.time)
    finished: float | None = None
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def to_dict(self) -> dict:
        return {
            "id": self.id, "kind": self.kind, "title": self.title, "total": self.total,
            "done": self.done, "status": self.status, "message": self.message,
            "item_progress": round(self.item_progress, 3), "results": self.results,
            "created": self.created, "finished": self.finished,
        }


class JobManager:
    def __init__(self) -> None:
        self._pools = {
            "import": ThreadPoolExecutor(IMPORT_WORKERS, thread_name_prefix="import"),
            "heavy": ThreadPoolExecutor(FULL_RES_WORKERS, thread_name_prefix="heavy"),
        }
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def submit(self, kind: str, title: str, items: list, work: Callable[[Job, object], dict],
               pool: str = "import") -> Job:
        job = Job(id=uuid.uuid4().hex, kind=kind, title=title, total=len(items))
        with self._lock:
            self._jobs[job.id] = job
            self._prune()
        self._pools[pool].submit(self._run, job, items, work)
        return job

    def _run(self, job: Job, items: list, work) -> None:
        job.status = "running"
        try:
            for item in items:
                if job.cancelled:
                    break
                job.item_progress = 0.0
                try:
                    res = work(job, item)
                except InterruptedError:
                    res = {"item": str(item), "ok": False, "message": "Cancelled"}
                except Exception as e:  # one bad file must not stop a batch
                    log.exception("job item failed")
                    res = {"item": str(item), "ok": False,
                           "message": getattr(e, "user_message", None) or f"Failed: {e}"}
                job.results.append(res)
                job.done += 1
            job.status = "cancelled" if job.cancelled else "done"
        except Exception as e:
            log.exception("job failed")
            job.status = "failed"
            job.message = str(e)
        finally:
            job.finished = time.time()

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job or job.status in ("done", "cancelled", "failed"):
            return False
        job._cancel.set()
        job.message = "Cancelling..."
        return True

    def list(self) -> list[dict]:
        with self._lock:
            return [j.to_dict() for j in sorted(self._jobs.values(), key=lambda j: j.created)]

    def _prune(self, keep: int = 30) -> None:
        finished = [j for j in self._jobs.values() if j.finished]
        finished.sort(key=lambda j: j.finished or 0)
        for j in finished[:-keep] if len(finished) > keep else []:
            self._jobs.pop(j.id, None)

    def shutdown(self) -> None:
        for job in self._jobs.values():
            job._cancel.set()
        for pool in self._pools.values():
            pool.shutdown(wait=False, cancel_futures=True)
