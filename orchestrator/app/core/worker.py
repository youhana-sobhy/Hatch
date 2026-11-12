"""Job queue for pipeline runs.

``thread`` mode runs pipelines on a bounded worker pool so API calls return immediately and
progress streams over WebSocket. ``inline`` mode runs the pipeline inside the caller, which
makes tests and the CLI deterministic. An onboarding never has two runs in flight.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor

from app.config import get_settings
from app.core import pipeline

log = logging.getLogger(__name__)


class Worker:
    def __init__(self) -> None:
        self._pool: ThreadPoolExecutor | None = None
        self._lock = threading.Lock()
        self._inflight: set[str] = set()

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(
                max_workers=get_settings().workers, thread_name_prefix="hatch-pipeline"
            )
        return self._pool

    def is_running(self, onboarding_id: str) -> bool:
        with self._lock:
            return onboarding_id in self._inflight

    def submit(self, onboarding_id: str, start: str = "pre_validate") -> bool:
        with self._lock:
            if onboarding_id in self._inflight:
                return False
            self._inflight.add(onboarding_id)

        def _job() -> str | None:
            try:
                return pipeline.run(onboarding_id, start)
            except Exception:
                log.exception("pipeline run for %s crashed", onboarding_id)
                return None
            finally:
                with self._lock:
                    self._inflight.discard(onboarding_id)

        if get_settings().executor == "inline":
            _job()
        else:
            future: Future = self._executor().submit(_job)
            future.add_done_callback(lambda f: f.exception())
        return True

    def shutdown(self) -> None:
        if self._pool is not None:
            self._pool.shutdown(wait=True, cancel_futures=False)
            self._pool = None


worker = Worker()
