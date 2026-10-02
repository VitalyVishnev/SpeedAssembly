from __future__ import annotations

from xml_to_usda.qt_ui.preview_jobs import PreviewProcessJob


class _CancelFlag:
    def __init__(self) -> None:
        self.was_set = False

    def set(self) -> None:
        self.was_set = True

    def is_set(self) -> bool:
        return self.was_set


class _Process:
    def __init__(self, *, alive: bool = True, exitcode: int | None = None) -> None:
        self._alive = alive
        self.exitcode = exitcode
        self.terminated = False

    def is_alive(self) -> bool:
        return self._alive and not self.terminated

    def join(self, timeout=None) -> None:
        return None

    def terminate(self) -> None:
        self.terminated = True


def _build_job(
    *,
    starts: list[dict[str, object]],
    queues: list[list[tuple[str, object]]] | None = None,
    pending_start_delay_seconds: float = 0.0,
    time_provider=None,
):
    processes: list[_Process] = []
    cancel_flags: list[_CancelFlag] = []
    traces: list[tuple[str, str, dict[str, object]]] = []
    queues = queues if queues is not None else []

    def start_process(request, settings):
        starts.append({"request": request, "settings": settings})
        process = _Process(alive=True)
        cancel_flag = _CancelFlag()
        processes.append(process)
        cancel_flags.append(cancel_flag)
        queue = queues.pop(0) if queues else []
        return process, queue, cancel_flag

    job = PreviewProcessJob(
        name="test_preview",
        start_process=start_process,
        drain_queue=lambda queue: list(queue),
        close_queue=lambda queue: queue.clear() if hasattr(queue, "clear") else None,
        trace_payload=lambda request, settings, job_id: {
            "preview_job_id": job_id,
            "request": request,
            "settings": settings,
        },
        trace=lambda kind, worker, data: traces.append((kind, worker, data)),
        pending_start_delay_seconds=pending_start_delay_seconds,
        **({"time_provider": time_provider} if time_provider is not None else {}),
    )
    return job, processes, cancel_flags, traces


def test_preview_process_job_latest_request_waits_without_killing_active_process() -> None:
    starts: list[dict[str, object]] = []
    job, processes, cancel_flags, traces = _build_job(starts=starts)

    first = job.start_latest("tree_a.xml", {"pieces": 5})
    second = job.start_latest("tree_b.xml", {"pieces": 9})

    assert first.started is True
    assert second.queued is True
    assert second.started is False
    assert starts == [{"request": "tree_a.xml", "settings": {"pieces": 5}}]
    assert cancel_flags[0].was_set is False
    assert processes[0].terminated is False
    assert job.request == "tree_a.xml"
    assert any(kind == "worker.pending" for kind, _worker, _data in traces)
    assert not any(kind == "worker.cancel_result" for kind, _worker, _data in traces)

    assert job.finish_current() is True
    assert starts == [
        {"request": "tree_a.xml", "settings": {"pieces": 5}},
        {"request": "tree_b.xml", "settings": {"pieces": 9}},
    ]
    assert job.request == "tree_b.xml"


def test_preview_process_job_coalesces_rapid_requests_before_pending_start() -> None:
    starts: list[dict[str, object]] = []
    job, _processes, _cancel_flags, _traces = _build_job(starts=starts)

    job.start_latest("tree.xml", {"stump": False, "caps": False})
    queued_stump = job.start_latest("tree.xml", {"stump": True, "caps": False})
    queued_caps = job.start_latest("tree.xml", {"stump": True, "caps": True})

    assert queued_stump == queued_caps
    assert queued_caps.started is False
    assert queued_caps.queued is True
    assert starts == [{"request": "tree.xml", "settings": {"stump": False, "caps": False}}]

    assert job.finish_current() is True
    assert starts == [
        {"request": "tree.xml", "settings": {"stump": False, "caps": False}},
        {"request": "tree.xml", "settings": {"stump": True, "caps": True}},
    ]


def test_preview_process_job_coalesces_a_fast_slider_burst_to_one_followup() -> None:
    starts: list[dict[str, object]] = []
    job, processes, cancel_flags, _traces = _build_job(starts=starts)

    job.start_latest("tree.xml", {"pieces": 1})
    for pieces in range(2, 102):
        job.start_latest("tree.xml", {"pieces": pieces})

    assert len(starts) == 1
    assert processes[0].terminated is False
    assert cancel_flags[0].was_set is False
    assert job.finish_current() is True
    assert starts == [
        {"request": "tree.xml", "settings": {"pieces": 1}},
        {"request": "tree.xml", "settings": {"pieces": 101}},
    ]


def test_preview_process_job_defers_pending_start_until_debounce_expires() -> None:
    now = 100.0
    starts: list[dict[str, object]] = []
    job, _processes, _cancel_flags, _traces = _build_job(
        starts=starts,
        pending_start_delay_seconds=0.25,
        time_provider=lambda: now,
    )

    job.start_latest("tree.xml", {"pieces": 5})
    job.start_latest("tree.xml", {"pieces": 14})

    assert job.finish_current() is True
    assert starts == [{"request": "tree.xml", "settings": {"pieces": 5}}]

    now = 100.24
    assert job.start_pending_if_any() is False
    assert starts == [{"request": "tree.xml", "settings": {"pieces": 5}}]

    now = 100.25
    assert job.start_pending_if_any() is True
    assert starts == [
        {"request": "tree.xml", "settings": {"pieces": 5}},
        {"request": "tree.xml", "settings": {"pieces": 14}},
    ]


def test_preview_process_job_queues_behind_finished_but_unread_process() -> None:
    starts: list[dict[str, object]] = []
    job, processes, _cancel_flags, _traces = _build_job(starts=starts)

    job.start_latest("tree.xml", {"pieces": 5})
    processes[0]._alive = False

    queued = job.start_latest("tree.xml", {"pieces": 9})

    assert queued.queued is True
    assert starts == [{"request": "tree.xml", "settings": {"pieces": 5}}]
    assert job.finish_current() is True
    assert starts[-1] == {"request": "tree.xml", "settings": {"pieces": 9}}


def test_preview_process_job_drain_records_traceback_and_result_state() -> None:
    starts: list[dict[str, object]] = []
    job, _processes, _cancel_flags, _traces = _build_job(
        starts=starts,
        queues=[[("error_traceback", "Traceback: bad"), ("result", object())]],
    )

    job.start_latest("tree.xml", {"pieces": 5})
    events = job.drain()

    assert [event_name for event_name, _payload in events] == ["error_traceback", "result"]
    assert job.error_traceback == "Traceback: bad"
    assert job.result_received is True


def test_preview_process_job_crash_reports_current_context() -> None:
    starts: list[dict[str, object]] = []
    job, processes, cancel_flags, _traces = _build_job(starts=starts)
    job.start_latest("tree.xml", {"pieces": 5})
    processes[0]._alive = False
    processes[0].exitcode = 3221225477
    cancel_flags[0].set()

    crash = job.crash()

    assert crash.exit_code == 3221225477
    assert crash.request == "tree.xml"
    assert crash.settings == {"pieces": 5}
    assert crash.cancelled is True
