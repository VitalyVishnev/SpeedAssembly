"""Background job bridge for the PySide6 beta shell.

Layer: UI infrastructure.

This controller keeps the Qt shell responsive while reusing the existing
conversion subprocess contract and application services. It does not define
conversion semantics; it only transports events between worker contexts and the
main UI thread.
"""

from __future__ import annotations

from dataclasses import dataclass
from queue import Empty, Queue
import threading
import traceback

from PySide6.QtCore import QTimer

from ..gui_formatters import (
    format_conversion_results,
    format_telemetry_status,
)
from ..models import ConversionJobResult, ConversionRequest, ConversionTelemetry


@dataclass(frozen=True)
class _WindErrorPayload:
    primary: dict[str, str]
    retry: dict[str, str] | None = None


class QtBackgroundJobsController:
    """Manage conversion and wind background work for the beta shell."""

    def __init__(self, window, *, deps, runtime_paths) -> None:
        self._window = window
        self._deps = deps
        self._runtime_paths = runtime_paths
        self._event_queue: Queue[tuple[str, object]] = Queue()
        self._poll_timer = QTimer(window)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll)

        self._conversion_process = None
        self._conversion_queue = None
        self._conversion_cancel_event = None
        self._conversion_request: ConversionRequest | None = None
        self._conversion_result_received = False
        self._conversion_error_traceback: str | None = None
        self._last_conversion_telemetry: ConversionTelemetry | None = None
        self._conversion_thread: threading.Thread | None = None

        self._wind_refresh_thread: threading.Thread | None = None
        self._wind_json_thread: threading.Thread | None = None

    @property
    def conversion_running(self) -> bool:
        return bool(
            (self._conversion_process is not None and self._conversion_process.is_alive())
            or (self._conversion_thread is not None and self._conversion_thread.is_alive())
        )

    @property
    def wind_refresh_running(self) -> bool:
        return self._wind_refresh_thread is not None and self._wind_refresh_thread.is_alive()

    @property
    def wind_json_running(self) -> bool:
        return self._wind_json_thread is not None and self._wind_json_thread.is_alive()

    def start_conversion(self, *, request: ConversionRequest, run_async: bool) -> None:
        if self.conversion_running:
            self._window._report_error("Conversion running", "A conversion is already running.")
            return
        self._conversion_request = request
        self._conversion_result_received = False
        self._conversion_error_traceback = None
        self._last_conversion_telemetry = None
        self._window._set_conversion_running(True)
        self._window._set_status("Preparing conversion job...")
        self._window._set_log(
            "Starting conversion.\n"
            "The PySide6 shell keeps the UI responsive while backend services normalize XML, import FBX, and write USDA."
        )
        if run_async:
            try:
                process, message_queue, cancel_event = self._deps.start_conversion_process(
                    request,
                    runtime_paths=self._runtime_paths,
                )
            except Exception as exc:
                self._window._set_conversion_running(False)
                self.close_conversion_process()
                self._window._report_error("Conversion failed", str(exc), status="Conversion failed.")
                return
            self._conversion_process = process
            self._conversion_queue = message_queue
            self._conversion_cancel_event = cancel_event
            self._ensure_polling()
            return

        cancel_event = threading.Event()
        self._conversion_cancel_event = cancel_event
        self._conversion_thread = threading.Thread(
            target=self._run_sync_conversion_worker,
            kwargs={"request": request, "cancel_event": cancel_event},
            daemon=True,
        )
        self._conversion_thread.start()
        self._ensure_polling()

    def _run_sync_conversion_worker(self, *, request: ConversionRequest, cancel_event: threading.Event) -> None:
        try:
            result = self._deps.convert_request(
                request,
                telemetry_callback=lambda telemetry: self._event_queue.put(("conversion_telemetry", telemetry)),
                cancel_event=cancel_event,
                runtime_paths=self._runtime_paths,
            )[0]
            self._event_queue.put(("conversion_result", ConversionJobResult(result=result)))
        except Exception as exc:
            self._event_queue.put(("conversion_error_traceback", traceback.format_exc()))
            self._event_queue.put(
                (
                    "conversion_result",
                    ConversionJobResult(
                        cancelled=bool(cancel_event.is_set()),
                        error_message=str(exc),
                    ),
                )
            )

    def cancel_conversion(self) -> None:
        if not self.conversion_running:
            return
        if self._conversion_cancel_event is not None:
            self._conversion_cancel_event.set()
        self._window._set_status("Cancelling conversion...")

    def start_wind_refresh(self, request) -> None:
        if self.wind_refresh_running:
            self._window._set_status("Wind group inspection already running...")
            return
        self._window._set_wind_refresh_running(True)
        self._window._set_status("Inspecting wind groups...")
        self._window._append_log(
            "Inspecting wind groups.\n"
            "The PySide6 shell keeps the UI responsive while generator levels are analyzed."
        )
        self._wind_refresh_thread = threading.Thread(
            target=self._run_wind_refresh_worker,
            kwargs={"request": request},
            daemon=True,
        )
        self._wind_refresh_thread.start()
        self._ensure_polling()

    def _run_wind_refresh_worker(self, *, request) -> None:
        try:
            dynamic_wind = self._deps.inspect_wind_groups(request)
            self._event_queue.put(("wind_refresh_result", (dynamic_wind, False)))
            return
        except Exception as exc:
            primary = {
                "type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        if not self._deps.should_retry_wind_error(primary["type"], primary["message"]):
            self._event_queue.put(("wind_refresh_error", _WindErrorPayload(primary=primary)))
            return
        try:
            dynamic_wind = self._deps.inspect_wind_groups(request)
            self._event_queue.put(("wind_refresh_result", (dynamic_wind, True)))
        except Exception as retry_exc:
            retry = {
                "type": type(retry_exc).__name__,
                "message": str(retry_exc),
                "traceback": traceback.format_exc(),
            }
            self._event_queue.put(("wind_refresh_error", _WindErrorPayload(primary=primary, retry=retry)))

    def start_wind_json_generation(self, request) -> None:
        if self.wind_json_running:
            self._window._set_status("Wind JSON generation already running...")
            return
        self._window._set_wind_json_running(True)
        self._window._set_status("Generating Dynamic Wind JSON...")
        self._wind_json_thread = threading.Thread(
            target=self._run_wind_json_worker,
            kwargs={"request": request},
            daemon=True,
        )
        self._wind_json_thread.start()
        self._ensure_polling()

    def _run_wind_json_worker(self, *, request) -> None:
        try:
            result = self._deps.generate_wind_json_from_request(request)
            self._event_queue.put(("wind_json_result", result))
        except Exception as exc:
            self._event_queue.put(
                (
                    "wind_json_error",
                    {
                        "type": type(exc).__name__,
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    },
                )
            )

    def shutdown(self) -> None:
        self._poll_timer.stop()
        if self._conversion_cancel_event is not None:
            self._conversion_cancel_event.set()
        if self._conversion_process is not None and self._conversion_process.is_alive():
            try:
                self._conversion_process.join(timeout=0.2)
            except Exception:
                pass
            if self._conversion_process.is_alive():
                try:
                    self._conversion_process.terminate()
                    self._conversion_process.join(timeout=0.2)
                except Exception:
                    pass
        self.close_conversion_process()

    def _ensure_polling(self) -> None:
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _poll(self) -> None:
        keep_polling = False
        while True:
            try:
                event_name, payload = self._event_queue.get_nowait()
            except Empty:
                break
            keep_polling = True
            if event_name == "conversion_telemetry":
                self._handle_conversion_telemetry(payload)
            elif event_name == "conversion_error_traceback":
                self._conversion_error_traceback = str(payload)
            elif event_name == "conversion_result":
                self._conversion_result_received = True
                self._handle_conversion_job_result(payload)
            elif event_name == "wind_refresh_result":
                dynamic_wind, used_retry = payload
                self._wind_refresh_thread = None
                self._window._set_wind_refresh_running(False)
                self._window._handle_wind_data_loaded(dynamic_wind, used_retry=bool(used_retry))
            elif event_name == "wind_refresh_error":
                self._wind_refresh_thread = None
                self._window._set_wind_refresh_running(False)
                self._handle_wind_refresh_error(payload)
            elif event_name == "wind_json_result":
                self._wind_json_thread = None
                self._window._set_wind_json_running(False)
                self._window._handle_wind_json_result(payload)
            elif event_name == "wind_json_error":
                self._wind_json_thread = None
                self._window._set_wind_json_running(False)
                self._window._report_error(
                    "Wind JSON generation failed",
                    payload.get("message", "Unknown error."),
                    details=self._deps.format_wind_error(payload),
                    status="Wind JSON generation failed.",
                )

        if self._conversion_queue is not None:
            for event_name, payload in self._deps.drain_process_queue(self._conversion_queue):
                keep_polling = True
                if event_name == "telemetry":
                    self._handle_conversion_telemetry(payload)
                elif event_name == "error_traceback":
                    self._conversion_error_traceback = str(payload)
                elif event_name == "result":
                    self._conversion_result_received = True
                    self._handle_conversion_job_result(payload)

        if self._conversion_process is not None and self._conversion_process.is_alive():
            keep_polling = True
        elif self._conversion_process is not None and not self._conversion_result_received:
            self._handle_async_process_crash()
        elif self._conversion_thread is not None and self._conversion_thread.is_alive():
            keep_polling = True

        if self.wind_refresh_running or self.wind_json_running:
            keep_polling = True

        if keep_polling:
            return
        self._poll_timer.stop()

    def _handle_wind_refresh_error(self, payload: _WindErrorPayload) -> None:
        self._window._clear_pending_generate_after_refresh()
        details = self._deps.format_wind_error(payload.primary)
        if payload.retry is not None:
            details = (
                f"{details}\n\nRetry also failed:\n"
                f"{self._deps.format_wind_error(payload.retry)}"
            )
        self._window._report_error(
            "Wind group inspection failed",
            payload.primary["message"],
            details=details,
            status="Wind group inspection failed.",
        )

    def _handle_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        self._last_conversion_telemetry = telemetry
        self._window._set_status(format_telemetry_status(telemetry))

    def _handle_async_process_crash(self) -> None:
        exit_code = self._conversion_process.exitcode if self._conversion_process is not None else None
        crash_message = f"Conversion worker process crashed unexpectedly (exit code {exit_code})"
        if self._last_conversion_telemetry is not None:
            crash_message = (
                f"{crash_message}\n"
                f"Last telemetry: {format_telemetry_status(self._last_conversion_telemetry)}"
            )
        crash_message = f"{crash_message}\n{self._format_runtime_crash_context()}"
        if self._conversion_error_traceback:
            crash_message = f"{crash_message}\n\n{self._conversion_error_traceback}"
        self._handle_conversion_job_result(
            ConversionJobResult(
                cancelled=bool(self._conversion_cancel_event and self._conversion_cancel_event.is_set()),
                error_message=crash_message,
            )
        )

    def _format_runtime_crash_context(self) -> str:
        return (
            "Runtime context:\n"
            f"  frozen={bool(getattr(self._deps.sys, 'frozen', False))}\n"
            f"  executable={self._deps.sys.executable}\n"
            f"  argv0={self._deps.sys.argv[0] if self._deps.sys.argv else ''}\n"
            f"  jobs_root={self._runtime_paths.jobs_root}"
        )

    def _handle_conversion_job_result(self, job_result: ConversionJobResult) -> None:
        request = self._conversion_request
        self._window._set_conversion_running(False)
        error_traceback = self._conversion_error_traceback
        self.close_conversion_process()

        if job_result.error_message:
            status = "Conversion cancelled." if job_result.cancelled else "Conversion failed."
            log_message = job_result.error_message
            if error_traceback:
                log_message = f"{log_message}\n\n{error_traceback}"
            if job_result.cancelled:
                self._window._set_status(status)
                self._window._set_log(log_message)
            else:
                self._window._report_error(
                    "Conversion failed",
                    job_result.error_message,
                    details=log_message,
                    status=status,
                )
            return

        result = job_result.result
        if result is None:
            self._window._set_status("Conversion cancelled.")
            self._window._set_log("Conversion cancelled before a result was produced.")
            return

        resolved_request = request or ConversionRequest(
            input_paths=(result.input_path,),
            output_path=result.output_path,
        )
        self._window._set_log(format_conversion_results((result,), resolved_request))
        if result.usda_document is None:
            self._window._set_status("Conversion finished with errors.")
            self._window._append_log("Conversion finished without a USDA document. See diagnostics above.")
            return

        self._window._set_status(f"Wrote USDA to {result.output_path}")
        self._window._show_info("Conversion complete", f"Wrote USDA to {result.output_path}")

    def close_conversion_process(self) -> None:
        self._deps.close_process_queue(self._conversion_queue)
        self._conversion_process = None
        self._conversion_queue = None
        self._conversion_cancel_event = None
        self._conversion_request = None
        self._conversion_result_received = False
        self._conversion_error_traceback = None
        self._last_conversion_telemetry = None
        self._conversion_thread = None
