"""Shared process-backed preview job lifecycle.

Layer: UI infrastructure.

The preview dialogs should not own worker processes. This module keeps the
latest-request-wins process lifecycle in one small place; callers still own
mode-specific result and error handling.
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
import time
from typing import Callable


@dataclass(frozen=True)
class PreviewJobStart:
    """Result of asking a preview job to start."""

    started: bool
    queued: bool = False


@dataclass(frozen=True)
class PreviewJobCrash:
    """State needed by callers to format a loud process crash."""

    job_id: int
    exit_code: int | None
    request: object | None
    settings: object | None
    queue: object | None
    error_traceback: str | None
    cancelled: bool


class PreviewProcessJob:
    """Own one process-backed latest-request-wins preview job."""

    def __init__(
        self,
        *,
        name: str,
        start_process: Callable[[object, object], tuple[object, object, object]],
        drain_queue: Callable[[object], list[tuple[str, object]]],
        close_queue: Callable[[object], None],
        trace_payload: Callable[[object | None, object | None, int], dict[str, object]],
        trace: Callable[[str, str, dict[str, object]], None],
        pending_start_delay_seconds: float = 0.0,
        time_provider: Callable[[], float] = time.monotonic,
    ) -> None:
        self._name = name
        self._start_process = start_process
        self._drain_queue = drain_queue
        self._close_queue = close_queue
        self._trace_payload = trace_payload
        self._trace = trace
        self._pending_start_delay_seconds = max(0.0, float(pending_start_delay_seconds))
        self._time_provider = time_provider
        self._process = None
        self._queue = None
        self._cancel_event = None
        self._request = None
        self._settings = None
        self._pending_request = None
        self._pending_settings = None
        self._pending_ready_at = 0.0
        self._result_received = False
        self._error_traceback: str | None = None
        self._generation_id = 0
        self._active_job_id = 0

    @property
    def running(self) -> bool:
        return bool(self._process is not None and self._process.is_alive())

    @property
    def has_process(self) -> bool:
        return self._process is not None

    @property
    def result_received(self) -> bool:
        return self._result_received

    @property
    def has_pending(self) -> bool:
        return self._pending_request is not None and self._pending_settings is not None

    @property
    def has_ready_pending(self) -> bool:
        return self.has_pending and self._time_provider() >= self._pending_ready_at

    @property
    def active_job_id(self) -> int:
        return self._active_job_id

    @property
    def request(self):
        return self._request

    @property
    def settings(self):
        return self._settings

    @property
    def queue(self):
        return self._queue

    @property
    def error_traceback(self) -> str | None:
        return self._error_traceback

    def start_latest(self, request, settings) -> PreviewJobStart:
        if self.has_pending:
            self._pending_request = request
            self._pending_settings = settings
            self._defer_pending_start()
            self._trace("worker.pending", self._name, self._trace_payload(request, settings, self._active_job_id))
            return PreviewJobStart(started=False, queued=True)

        if self.running:
            self._pending_request = request
            self._pending_settings = settings
            self._defer_pending_start()
            self._trace("worker.pending", self._name, self._trace_payload(request, settings, self._active_job_id))
            self.cancel_running(clear_pending=False)
            return PreviewJobStart(started=False, queued=True)

        self._error_traceback = None
        self._result_received = False
        self._request = request
        self._settings = settings
        self._generation_id += 1
        self._active_job_id = self._generation_id
        self._trace("worker.start", self._name, self._trace_payload(request, settings, self._active_job_id))
        process, queue, cancel_event = self._start_process(request, settings)
        self._process = process
        self._queue = queue
        self._cancel_event = cancel_event
        self._trace(
            "worker.spawn",
            self._name,
            {
                **self._trace_payload(request, settings, self._active_job_id),
                **_queue_payload(queue),
                "mode": "process",
            },
        )
        return PreviewJobStart(started=True)

    def start_pending_if_any(self) -> bool:
        request = self._pending_request
        settings = self._pending_settings
        if request is None or settings is None:
            return False
        if not self.has_ready_pending:
            return False
        self._pending_request = None
        self._pending_settings = None
        self._pending_ready_at = 0.0
        return self.start_latest(request, settings).started

    def cancel_running(self, *, clear_pending: bool) -> None:
        if clear_pending:
            self._pending_request = None
            self._pending_settings = None
            self._pending_ready_at = 0.0
        previous_job_id = self._active_job_id
        process_alive_before = self.running
        had_cancel_event = self._cancel_event is not None
        self._trace(
            "worker.cancel_request",
            self._name,
            {
                "preview_job_id": previous_job_id,
                "process_alive_before": process_alive_before,
                "had_cancel_event": had_cancel_event,
                "queue": _queue_payload(self._queue),
            },
        )
        self._generation_id += 1
        self._active_job_id = self._generation_id
        cancel_event_set = False
        terminated = False
        if self._cancel_event is not None:
            with suppress(Exception):
                self._cancel_event.set()
                cancel_event_set = True
        if self._process is not None and self._process.is_alive():
            with suppress(Exception):
                self._process.join(timeout=0.1)
            if self._process.is_alive():
                with suppress(Exception):
                    self._process.terminate()
                    self._process.join(timeout=0.1)
                    terminated = True
        self._trace(
            "worker.cancel_result",
            self._name,
            {
                "preview_job_id": previous_job_id,
                "next_preview_job_id": self._active_job_id,
                "cancel_event_set": cancel_event_set,
                "terminated": terminated,
                "process_alive_after": self.running,
            },
        )
        self.close_handles()

    def drain(self) -> list[tuple[str, object]]:
        if self._queue is None:
            return []
        events = self._drain_queue(self._queue)
        for event_name, payload in events:
            self._trace(
                "worker.event",
                self._name,
                {
                    "preview_job_id": self._active_job_id,
                    "event_name": event_name,
                    "payload_type": type(payload).__name__,
                },
            )
            if event_name == "error_traceback":
                self._error_traceback = str(payload)
            elif event_name in {"error", "result"}:
                self._result_received = True
        return events

    def crash(self) -> PreviewJobCrash:
        process = self._process
        exit_code = process.exitcode if process is not None else None
        self._trace(
            "worker.crash",
            self._name,
            {
                "preview_job_id": self._active_job_id,
                "exit_code": exit_code,
                "queue": _queue_payload(self._queue),
            },
        )
        return PreviewJobCrash(
            job_id=self._active_job_id,
            exit_code=exit_code,
            request=self._request,
            settings=self._settings,
            queue=self._queue,
            error_traceback=self._error_traceback,
            cancelled=bool(self._cancel_event and self._cancel_event.is_set()),
        )

    def finish_current(self) -> bool:
        self.close_handles()
        if self.start_pending_if_any():
            return True
        self._request = None
        self._settings = None
        self._active_job_id = 0
        return False

    def close(self) -> None:
        self._pending_request = None
        self._pending_settings = None
        self._pending_ready_at = 0.0
        if self._cancel_event is not None:
            with suppress(Exception):
                self._cancel_event.set()
        if self._process is not None and self._process.is_alive():
            with suppress(Exception):
                self._process.join(timeout=0.1)
            if self._process.is_alive():
                with suppress(Exception):
                    self._process.terminate()
                    self._process.join(timeout=0.1)
        self.close_handles()
        self._request = None
        self._settings = None
        self._active_job_id = 0

    def close_handles(self) -> None:
        self._close_queue(self._queue)
        self._process = None
        self._queue = None
        self._cancel_event = None
        self._error_traceback = None
        self._result_received = False

    def _defer_pending_start(self) -> None:
        self._pending_ready_at = self._time_provider() + self._pending_start_delay_seconds


def _queue_payload(queue) -> dict[str, object]:
    payload: dict[str, object] = {}
    if queue is None:
        return payload
    for label in ("request_path", "result_path", "error_path", "stderr_path"):
        path = getattr(queue, label, None)
        if path is None:
            continue
        try:
            exists = path.exists()
            size = path.stat().st_size if exists else None
        except OSError:
            exists = False
            size = None
        payload[label] = str(path)
        payload[f"{label}_exists"] = exists
        payload[f"{label}_size"] = size
    return payload
