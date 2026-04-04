from __future__ import annotations

from xml_to_usda.conversion_process import start_conversion_process
from xml_to_usda.models import ConversionRequest


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
