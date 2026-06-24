from __future__ import annotations

from pathlib import Path
from queue import Empty
import threading

from xml_to_usda.conversion_process import (
    _conversion_process_entry,
    _proxy_mesh_process_entry,
    close_process_queue,
    drain_process_queue,
    start_fracture_export_process,
    start_fracture_preview_process,
    start_conversion_process,
    start_proxy_mesh_process,
)
from xml_to_usda.conversion_worker_subprocess import (
    ConversionWorkerRequest,
    run_conversion_worker_request_file,
    write_conversion_worker_request,
)
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.fracture_export_service import FractureExportRequest
from xml_to_usda.fracture_preview_service import FracturePreviewSettings, FracturePreviewSourceRequest
from xml_to_usda.fracture_worker_subprocess import (
    read_fracture_worker_request,
)
from xml_to_usda.models import ConversionJobResult, ConversionRequest
from xml_to_usda.pipeline import convert_request
from xml_to_usda.proxy_mesh_service import ProxyMeshJobResult, ProxyMeshSettings, ProxyMeshSourceRequest
from xml_to_usda.runtime_paths import resolve_runtime_paths
from xml_to_usda.worker_file_protocol import read_worker_payload


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


def _read_worker_events(event_dir: Path) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    for path in sorted(event_dir.glob("*.event.json")):
        events.append(read_worker_payload(path))
    return events


def test_start_conversion_process_uses_file_based_worker(monkeypatch, tmp_path: Path) -> None:
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

    process, queue, cancel_event = start_conversion_process(
        ConversionRequest(input_paths=("input.xml",), output_path="output.usda"),
        runtime_paths=_test_runtime_paths(tmp_path),
    )

    assert popen_calls
    assert process.is_alive() is True
    assert "--request" in popen_calls[0].args
    assert popen_calls[0].kwargs["stdout"] is not None
    assert popen_calls[0].kwargs["stderr"] is not None
    cancel_event.set()
    assert process.is_alive() is False
    close_process_queue(queue)


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
        ProxyMeshSourceRequest(input_path="input.xml", output_path="output.usda"),
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


def test_start_fracture_export_process_uses_file_based_worker(monkeypatch) -> None:
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

    process, queue, cancel_event = start_fracture_export_process(
        FractureExportRequest(input_path="input.xml", output_path="output.usda"),
        FractureSettings(target_piece_count=4),
    )

    assert popen_calls
    assert process.is_alive() is True
    assert "--request" in popen_calls[0].args
    request_path = Path(popen_calls[0].args[popen_calls[0].args.index("--request") + 1])
    payload = read_fracture_worker_request(request_path)
    assert payload.request.output_path == "output.usda"
    assert isinstance(payload.request, FractureExportRequest)
    assert payload.action == "export"
    assert payload.settings.target_piece_count == 4
    assert popen_calls[0].kwargs["stdout"] is not None
    assert popen_calls[0].kwargs["stderr"] is not None
    cancel_event.set()
    assert process.is_alive() is False
    close_process_queue(queue)


def test_start_fracture_preview_process_uses_file_based_worker(monkeypatch) -> None:
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

    process, queue, cancel_event = start_fracture_preview_process(
        FracturePreviewSourceRequest(input_path="input.xml", output_path="output.usda"),
        FracturePreviewSettings(fracture=FractureSettings(target_piece_count=3)),
    )

    assert popen_calls
    assert process.is_alive() is True
    assert "--request" in popen_calls[0].args
    request_path = Path(popen_calls[0].args[popen_calls[0].args.index("--request") + 1])
    payload = read_fracture_worker_request(request_path)
    assert payload.request.output_path == "output.usda"
    assert isinstance(payload.request, FracturePreviewSourceRequest)
    assert payload.action == "preview"
    assert payload.settings.fracture.target_piece_count == 3
    stderr_path = queue.stderr_path
    assert stderr_path.name.endswith(".stderr.log")
    assert popen_calls[0].kwargs["stderr"] is not None
    cancel_event.set()
    assert process.is_alive() is False
    close_process_queue(queue)
    assert stderr_path.exists() is False


def test_fracture_worker_crash_context_can_include_stderr_tail(tmp_path: Path) -> None:
    from xml_to_usda.qt_ui.background_jobs import QtBackgroundJobsController

    stderr_path = tmp_path / "worker.stderr.log"
    stderr_path.write_text("first line\nnative crash detail\n", encoding="utf-8")
    queue = type(
        "_Queue",
        (),
        {
            "request_path": tmp_path / "request.pkl",
            "result_path": tmp_path / "result.pkl",
            "error_path": tmp_path / "error.json",
            "stderr_path": stderr_path,
        },
    )()
    controller = QtBackgroundJobsController.__new__(QtBackgroundJobsController)

    context = controller._format_worker_file_context(queue)
    payload = controller._worker_queue_payload(queue)

    assert "stderr_path=" in context
    assert "native crash detail" in context
    assert str(payload["stderr_tail"]).splitlines() == ["first line", "native crash detail"]


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


def test_conversion_worker_request_file_writes_telemetry_and_result(
    monkeypatch,
    tmp_path: Path,
) -> None:
    runtime_paths = _test_runtime_paths(tmp_path)
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(tmp_path / "worker_file_success.usda"),
    )
    request_path = tmp_path / "conversion.request.json"
    result_path = tmp_path / "conversion.result.json"
    error_path = tmp_path / "conversion.error.json"
    event_dir = tmp_path / "events"

    monkeypatch.setattr("xml_to_usda.conversion_worker_subprocess.apply_process_profile", lambda _profile: None)
    write_conversion_worker_request(
        request_path,
        ConversionWorkerRequest(
            request=request,
            runtime_paths=runtime_paths,
            result_path=str(result_path),
            error_path=str(error_path),
            event_dir=str(event_dir),
        ),
    )

    exit_code = run_conversion_worker_request_file(request_path)

    assert exit_code == 0
    assert error_path.exists() is False
    assert sorted(path.name for path in event_dir.glob("*.event.json"))
    events = _read_worker_events(event_dir)
    assert any(event_name == "telemetry" for event_name, _payload in events)
    job_result = read_worker_payload(result_path)
    assert isinstance(job_result, ConversionJobResult)
    assert job_result.error_message is None
    assert job_result.result is not None
    assert job_result.result.output_path == str(tmp_path / "worker_file_success.usda")


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
    request = ProxyMeshSourceRequest(
        input_path=str(SIMPLE_TREE_01),
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
    request = ProxyMeshSourceRequest(
        input_path=str(tmp_path / "missing_input.xml"),
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
