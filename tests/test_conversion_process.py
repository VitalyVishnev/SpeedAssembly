from __future__ import annotations

from pathlib import Path
from queue import Empty
import threading

from xml_to_usda.conversion_process import (
    _conversion_process_entry,
    _proxy_mesh_process_entry,
    close_process_queue,
    drain_process_queue,
    start_conversion_process,
    start_proxy_mesh_process,
)
from xml_to_usda.models import ConversionJobResult, ConversionRequest
from xml_to_usda.pipeline import convert_request
from xml_to_usda.proxy_mesh_service import ProxyMeshJobResult, ProxyMeshSettings
from xml_to_usda.runtime_paths import resolve_runtime_paths


SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"


class _DummyProcess:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.daemon = kwargs.get("daemon")
        self.started = False

    def start(self) -> None:
        self.started = True


class _DummyContext:
    def __init__(self) -> None:
        self.queue = object()
        self.event = object()
        self.process: _DummyProcess | None = None

    def Queue(self):
        return self.queue

    def Event(self):
        return self.event

    def Process(self, **kwargs):
        self.process = _DummyProcess(**kwargs)
        return self.process


class _RecordingQueue:
    def __init__(self) -> None:
        self.items: list[tuple[str, object]] = []
        self.closed = False
        self.joined = False

    def put(self, item) -> None:
        self.items.append(item)

    def get_nowait(self):
        if not self.items:
            raise Empty
        return self.items.pop(0)

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.joined = True


class _BrokenCloseQueue(_RecordingQueue):
    def close(self) -> None:
        raise RuntimeError("close failed")

    def join_thread(self) -> None:
        raise RuntimeError("join failed")


def _test_runtime_paths(tmp_path: Path):
    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )


def test_start_conversion_process_uses_non_daemon_worker(monkeypatch) -> None:
    dummy_context = _DummyContext()
    monkeypatch.setattr("xml_to_usda.conversion_process.get_spawn_context", lambda: dummy_context)

    process, queue, cancel_event = start_conversion_process(
        ConversionRequest(input_paths=("input.xml",), output_path="output.usda"),
        runtime_paths=object(),
    )

    assert process is dummy_context.process
    assert queue is dummy_context.queue
    assert cancel_event is dummy_context.event
    assert dummy_context.process is not None
    assert dummy_context.process.started is True
    assert dummy_context.process.daemon is False


def test_start_proxy_mesh_process_uses_file_based_worker(monkeypatch) -> None:
    class _DummyPopen:
        def __init__(self, args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 1

        def wait(self, timeout=None):
            self.terminated = True
            return 0

        def terminate(self) -> None:
            self.terminated = True

    popen_calls: list[_DummyPopen] = []

    def fake_popen(args, **kwargs):
        process = _DummyPopen(args, **kwargs)
        popen_calls.append(process)
        return process

    monkeypatch.setattr("xml_to_usda.conversion_process.subprocess.Popen", fake_popen)

    process, queue, cancel_event = start_proxy_mesh_process(
        ConversionRequest(input_paths=("input.xml",), output_path="output.usda"),
        ProxyMeshSettings(),
        action="export",
    )

    assert popen_calls
    assert process.is_alive() is True
    assert "--request" in popen_calls[0].args
    assert popen_calls[0].kwargs["stdout"] is not None
    assert popen_calls[0].kwargs["stderr"] is not None
    cancel_event.set()
    assert process.is_alive() is False
    close_process_queue(queue)


def test_drain_process_queue_returns_all_pending_events() -> None:
    queue = _RecordingQueue()
    queue.put(("telemetry", {"phase": "xml_normalization"}))
    queue.put(("result", ConversionJobResult(error_message="done")))

    events = drain_process_queue(queue)

    assert events == [
        ("telemetry", {"phase": "xml_normalization"}),
        ("result", ConversionJobResult(error_message="done")),
    ]
    assert drain_process_queue(queue) == []


def test_close_process_queue_closes_and_joins_queue() -> None:
    queue = _RecordingQueue()

    close_process_queue(queue)

    assert queue.closed is True
    assert queue.joined is True


def test_close_process_queue_ignores_close_and_join_errors() -> None:
    close_process_queue(_BrokenCloseQueue())
    close_process_queue(None)


def test_conversion_process_entry_success_matches_direct_convert_request(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_paths = _test_runtime_paths(tmp_path)
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "worker_success.usda"),
    )
    expected_result = convert_request(
        request,
        runtime_paths=runtime_paths,
    )[0]
    queue = _RecordingQueue()

    monkeypatch.setattr("xml_to_usda.conversion_process.apply_process_profile", lambda _profile: None)

    _conversion_process_entry(
        request=request,
        runtime_paths=runtime_paths,
        message_queue=queue,
        cancel_event=threading.Event(),
    )
    events = drain_process_queue(queue)

    assert events
    assert any(event_name == "telemetry" for event_name, _payload in events)
    assert events[-1][0] == "result"
    job_result = events[-1][1]
    assert isinstance(job_result, ConversionJobResult)
    assert job_result.cancelled is False
    assert job_result.error_message is None
    assert job_result.result is not None
    assert job_result.result.input_path == expected_result.input_path
    assert job_result.result.output_path == expected_result.output_path
    assert job_result.result.diagnostics == expected_result.diagnostics
    assert job_result.result.usda_document is not None
    assert expected_result.usda_document is not None
    assert job_result.result.usda_document.text == expected_result.usda_document.text


def test_conversion_process_entry_reports_traceback_then_error_result_on_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_paths = _test_runtime_paths(tmp_path)
    request = ConversionRequest(
        input_paths=(str(tmp_path / "missing_input.xml"),),
        output_path=str(tmp_path / "worker_failure.usda"),
    )
    queue = _RecordingQueue()

    monkeypatch.setattr("xml_to_usda.conversion_process.apply_process_profile", lambda _profile: None)

    _conversion_process_entry(
        request=request,
        runtime_paths=runtime_paths,
        message_queue=queue,
        cancel_event=threading.Event(),
    )
    events = drain_process_queue(queue)

    assert events[-2][0] == "error_traceback"
    assert "missing_input.xml" in events[-2][1]
    assert events[-1][0] == "result"
    job_result = events[-1][1]
    assert isinstance(job_result, ConversionJobResult)
    assert job_result.result is None
    assert job_result.cancelled is False
    assert job_result.error_message is not None
    assert "missing_input.xml" in job_result.error_message


def test_conversion_process_entry_marks_cancelled_when_cancel_event_is_set(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_paths = _test_runtime_paths(tmp_path)
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "worker_cancelled.usda"),
    )
    queue = _RecordingQueue()
    cancel_event = threading.Event()
    cancel_event.set()

    monkeypatch.setattr("xml_to_usda.conversion_process.apply_process_profile", lambda _profile: None)

    _conversion_process_entry(
        request=request,
        runtime_paths=runtime_paths,
        message_queue=queue,
        cancel_event=cancel_event,
    )
    events = drain_process_queue(queue)

    assert events[-2][0] == "error_traceback"
    assert "Conversion cancelled by user." in events[-2][1]
    assert events[-1][0] == "result"
    job_result = events[-1][1]
    assert isinstance(job_result, ConversionJobResult)
    assert job_result.result is None
    assert job_result.cancelled is True
    assert job_result.error_message == "Conversion cancelled by user."


def test_proxy_mesh_process_entry_exports_proxy_usda(monkeypatch, tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "worker_proxy.usda"),
    )
    queue = _RecordingQueue()

    monkeypatch.setattr("xml_to_usda.conversion_process.apply_process_profile", lambda _profile: None)

    _proxy_mesh_process_entry(
        request=request,
        settings=ProxyMeshSettings(final_polycount=5000),
        action="export",
        message_queue=queue,
        cancel_event=threading.Event(),
    )
    events = drain_process_queue(queue)

    assert events[-1][0] == "result"
    job_result = events[-1][1]
    assert isinstance(job_result, ProxyMeshJobResult)
    assert job_result.error_message is None
    assert job_result.export is not None
    assert job_result.export.output_path == str(tmp_path / "worker_proxy_proxy.usda")
    assert Path(job_result.export.output_path).exists()


def test_proxy_mesh_process_entry_reports_error_result_on_failure(monkeypatch, tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=(str(tmp_path / "missing_input.xml"),),
        output_path=str(tmp_path / "worker_proxy.usda"),
    )
    queue = _RecordingQueue()

    monkeypatch.setattr("xml_to_usda.conversion_process.apply_process_profile", lambda _profile: None)

    _proxy_mesh_process_entry(
        request=request,
        settings=ProxyMeshSettings(final_polycount=5000),
        action="export",
        message_queue=queue,
        cancel_event=threading.Event(),
    )
    events = drain_process_queue(queue)

    assert events[-2][0] == "error_traceback"
    assert events[-1][0] == "result"
    job_result = events[-1][1]
    assert isinstance(job_result, ProxyMeshJobResult)
    assert job_result.export is None
    assert job_result.error_message is not None
