from __future__ import annotations

import multiprocessing
import traceback
from queue import Empty

from .job_control import apply_process_profile
from .models import ConversionJobResult, ConversionRequest
from .pipeline import convert_request


def get_spawn_context() -> multiprocessing.context.BaseContext:
    return multiprocessing.get_context("spawn")


def start_conversion_process(
    request: ConversionRequest,
    *,
    runtime_paths,
):
    context = get_spawn_context()
    message_queue = context.Queue()
    cancel_event = context.Event()
    process = context.Process(
        target=_conversion_process_entry,
        kwargs={
            "request": request,
            "runtime_paths": runtime_paths,
            "message_queue": message_queue,
            "cancel_event": cancel_event,
        },
        daemon=False,
    )
    process.start()
    return process, message_queue, cancel_event


def drain_process_queue(message_queue) -> list[tuple[str, object]]:
    events: list[tuple[str, object]] = []
    while True:
        try:
            events.append(message_queue.get_nowait())
        except Empty:
            break
    return events


def close_process_queue(message_queue) -> None:
    if message_queue is None:
        return
    try:
        message_queue.close()
    except Exception:
        pass
    try:
        message_queue.join_thread()
    except Exception:
        pass


def _conversion_process_entry(
    *,
    request: ConversionRequest,
    runtime_paths,
    message_queue,
    cancel_event,
) -> None:
    try:
        apply_process_profile(request.cpu_profile)
        result = convert_request(
            request,
            telemetry_callback=lambda telemetry: message_queue.put(("telemetry", telemetry)),
            cancel_event=cancel_event,
            runtime_paths=runtime_paths,
        )[0]
        message_queue.put(("result", ConversionJobResult(result=result)))
    except Exception as exc:
        message_queue.put(("error_traceback", traceback.format_exc()))
        message_queue.put(
            (
                "result",
                ConversionJobResult(
                    cancelled=bool(cancel_event.is_set()),
                    error_message=str(exc),
                ),
            )
        )
