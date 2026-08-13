"""Background job bridge for the PySide6 shell.

Layer: UI infrastructure.

This controller keeps the Qt shell responsive while reusing the existing
conversion subprocess contract and application services. It does not define
conversion semantics; it only transports events between worker contexts and the
main UI thread.
"""

from __future__ import annotations

from contextlib import suppress
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
from ..proxy_mesh_service import ProxyMeshJobResult, ProxyMeshSettings
from .preview_jobs import PreviewProcessJob


@dataclass(frozen=True)
class _WindErrorPayload:
    primary: dict[str, str]
    retry: dict[str, str] | None = None


@dataclass(frozen=True)
class _ProxyPreviewWork:
    settings: ProxyMeshSettings
    collision_only: bool = False
    include_source_scene: bool = False

    @property
    def action(self) -> str:
        if self.collision_only:
            return "collision"
        return "preview_with_source" if self.include_source_scene else "preview"


class QtBackgroundJobsController:
    """Manage conversion and wind background work for the PySide6 shell."""

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
        self._wind_refresh_process_job = PreviewProcessJob(
            name="wind_refresh",
            start_process=lambda request, _settings: self._deps.start_wind_preview_process(request),
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._wind_preview_trace_payload,
            trace=self._trace_worker,
        )
        self._wind_json_thread: threading.Thread | None = None
        self._wind_preview_retry_count = 0
        self._wind_preview_job = PreviewProcessJob(
            name="wind_preview",
            start_process=self._deps.start_wind_preview_process,
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._wind_preview_trace_payload,
            trace=self._trace_worker,
        )
        self._proxy_mesh_process = None
        self._proxy_mesh_queue = None
        self._proxy_mesh_cancel_event = None
        self._proxy_mesh_request = None
        self._proxy_mesh_settings = None
        self._proxy_mesh_retry_count = 0
        self._proxy_mesh_error_traceback: str | None = None
        self._proxy_mesh_result_received = False
        self._proxy_mesh_thread: threading.Thread | None = None
        self._proxy_preview_retry_count = 0
        self._proxy_preview_job = PreviewProcessJob(
            name="proxy_preview",
            start_process=lambda request, work: self._deps.start_proxy_mesh_process(
                request,
                work.settings,
                action=work.action,
            ),
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._proxy_preview_trace_payload,
            trace=self._trace_worker,
            pending_start_delay_seconds=0.25,
        )
        self._fracture_export_process = None
        self._fracture_export_queue = None
        self._fracture_export_cancel_event = None
        self._fracture_export_request = None
        self._fracture_export_settings = None
        self._fracture_export_error_traceback: str | None = None
        self._fracture_export_result_received = False
        self._fracture_preview_job = PreviewProcessJob(
            name="fracture_preview",
            start_process=self._deps.start_fracture_preview_process,
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._fracture_preview_trace_payload,
            trace=self._trace_worker,
            pending_start_delay_seconds=0.25,
        )
        self._fracture_preview_retry_count = 0
        self._part_preview_job = PreviewProcessJob(
            name="part_preview",
            start_process=self._deps.start_part_preview_process,
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._part_preview_trace_payload,
            trace=self._trace_worker,
            pending_start_delay_seconds=0.2,
        )
        self._source_discovery_job = PreviewProcessJob(
            name="source_discovery",
            start_process=lambda request, _settings: self._deps.start_source_discovery_process(request),
            drain_queue=self._deps.drain_process_queue,
            close_queue=self._deps.close_process_queue,
            trace_payload=self._source_discovery_trace_payload,
            trace=self._trace_worker,
            pending_start_delay_seconds=0.2,
        )

    @property
    def conversion_running(self) -> bool:
        return bool(
            (self._conversion_process is not None and self._conversion_process.is_alive())
            or (self._conversion_thread is not None and self._conversion_thread.is_alive())
        )

    @property
    def wind_refresh_running(self) -> bool:
        return bool(
            (self._wind_refresh_thread is not None and self._wind_refresh_thread.is_alive())
            or self._wind_refresh_process_job.has_process
        )

    @property
    def wind_json_running(self) -> bool:
        return self._wind_json_thread is not None and self._wind_json_thread.is_alive()

    @property
    def wind_preview_running(self) -> bool:
        return self._wind_preview_job.has_process

    @property
    def proxy_mesh_running(self) -> bool:
        return bool(
            (self._proxy_mesh_process is not None and self._proxy_mesh_process.is_alive())
            or (self._proxy_mesh_thread is not None and self._proxy_mesh_thread.is_alive())
        )

    @property
    def proxy_preview_running(self) -> bool:
        return self._proxy_preview_job.has_process

    @property
    def fracture_export_running(self) -> bool:
        return bool(self._fracture_export_process is not None and self._fracture_export_process.is_alive())

    @property
    def fracture_preview_running(self) -> bool:
        return self._fracture_preview_job.has_process

    @property
    def part_preview_running(self) -> bool:
        return self._part_preview_job.has_process

    @property
    def source_discovery_running(self) -> bool:
        return self._source_discovery_job.has_process

    def _begin_status_activity(self, title: str, message: str) -> None:
        handler = getattr(self._window, "_begin_status_activity", None)
        if handler is not None:
            handler(title, message)
        else:
            self._window._set_status(message)

    def _begin_conversion_status(self, message: str) -> None:
        handler = getattr(self._window, "_begin_conversion_status", None)
        if handler is not None:
            handler(message)
        else:
            self._window._set_status(message)

    def _finish_status_activity(self, outcome: str, message: str) -> None:
        handler = getattr(self._window, "_finish_status_activity", None)
        if handler is not None:
            handler(outcome, message)
        else:
            self._window._set_status(message)

    def _set_status_telemetry(self, telemetry: ConversionTelemetry) -> None:
        handler = getattr(self._window, "_set_conversion_telemetry", None)
        if handler is not None:
            handler(telemetry)
        else:
            self._window._set_status(format_telemetry_status(telemetry))

    def _conversion_log_context(self, request: ConversionRequest) -> str:
        handler = getattr(self._window, "_conversion_status_log_context", None)
        return str(handler(request)) if handler is not None else ""

    def start_conversion(self, *, request: ConversionRequest, run_async: bool) -> None:
        if self.conversion_running:
            self._window._report_error("Conversion running", "A conversion is already running.")
            return
        self._conversion_request = request
        self._conversion_result_received = False
        self._conversion_error_traceback = None
        self._last_conversion_telemetry = None
        self._window._set_conversion_running(True)
        self._begin_conversion_status("Preparing conversion job...")
        context = self._conversion_log_context(request)
        context_suffix = f"\n\n{context}" if context else ""
        self._window._set_log(
            "Starting conversion.\n"
            "The PySide6 shell keeps the UI responsive while backend services normalize XML, import FBX, and write USDA."
            f"{context_suffix}"
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
            self._trace_worker("worker.spawn", "conversion", self._worker_queue_payload(message_queue))
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

    def start_wind_refresh(self, request, *, run_async: bool = False) -> None:
        if self.wind_refresh_running:
            self._window._set_status("Wind group inspection already running...")
            return
        self._window._set_wind_refresh_running(True)
        self._begin_status_activity("Inspecting Wind", "Inspecting wind groups...")
        self._window._append_log(
            "Inspecting wind groups.\n"
            "The PySide6 shell keeps the UI responsive while generator levels are analyzed."
        )
        if run_async:
            try:
                self._wind_refresh_process_job.start_latest(request, True)
            except Exception as exc:
                self._wind_refresh_process_job.close()
                self._window._set_wind_refresh_running(False)
                self._handle_wind_refresh_error(
                    _WindErrorPayload(
                        primary={
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(),
                        }
                    )
                )
                return
            self._ensure_polling()
            return
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
        self._begin_status_activity("Generating Wind JSON", "Generating Dynamic Wind JSON...")
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

    def start_wind_preview(self, request) -> None:
        if self.wind_preview_running:
            self._window._set_status("Wind Preview generation already running...")
            return
        self._begin_status_activity("Wind Preview", "Preparing Wind Preview...")
        if hasattr(self._window, "_handle_wind_preview_loading"):
            self._window._handle_wind_preview_loading("Preparing wind preview...")
        self._wind_preview_retry_count = 0
        try:
            self._wind_preview_job.start_latest(request, None)
        except Exception as exc:
            self._wind_preview_job.close()
            self._handle_wind_preview_error(str(exc))
            return
        self._window._update_action_state()
        self._ensure_polling()

    def start_proxy_mesh_export(self, request, settings) -> None:
        if self.proxy_mesh_running:
            self._window._set_status("Proxy Mesh generation already running...")
            return
        self._proxy_mesh_error_traceback = None
        self._proxy_mesh_result_received = False
        self._proxy_mesh_request = request
        self._proxy_mesh_settings = settings
        self._proxy_mesh_retry_count = 0
        self._begin_status_activity("Generating Proxy Mesh", "Generating Proxy Mesh...")
        if not self._start_proxy_mesh_process(request, settings):
            return
        self._window._update_action_state()
        self._ensure_polling()

    def start_generated_proxy_mesh_export(self, request, proxy) -> None:
        if self.proxy_mesh_running:
            self._window._set_status("Proxy Mesh generation already running...")
            return
        self._proxy_mesh_error_traceback = None
        self._proxy_mesh_result_received = False
        self._proxy_mesh_request = request
        self._proxy_mesh_settings = proxy.settings
        self._proxy_mesh_retry_count = 0
        self._begin_status_activity("Writing Proxy Mesh", "Writing Proxy Mesh...")
        self._proxy_mesh_thread = threading.Thread(
            target=self._run_generated_proxy_mesh_export_worker,
            kwargs={"request": request, "proxy": proxy},
            daemon=True,
        )
        self._proxy_mesh_thread.start()
        self._window._update_action_state()
        self._ensure_polling()

    def start_proxy_mesh_preview(
        self,
        request,
        settings,
        *,
        collision_only: bool = False,
        include_source_scene: bool = False,
    ) -> None:
        if self.proxy_mesh_running:
            self._window._set_status("Proxy Mesh export is already running...")
            return
        if not self.proxy_preview_running:
            self._proxy_preview_retry_count = 0
        message = "Updating Proxy collision..." if collision_only else "Generating Proxy Preview..."
        self._begin_status_activity("Proxy Preview", message)
        if hasattr(self._window, "_handle_proxy_preview_loading"):
            self._window._handle_proxy_preview_loading(message)
        try:
            start_result = self._proxy_preview_job.start_latest(
                request,
                _ProxyPreviewWork(
                    settings=settings,
                    collision_only=collision_only,
                    include_source_scene=include_source_scene,
                ),
            )
        except Exception as exc:
            self._proxy_preview_job.close()
            self._handle_proxy_preview_error(str(exc))
            return
        if start_result.queued:
            self._window._set_status("Proxy Preview update queued...")
        self._window._update_action_state()
        self._ensure_polling()

    def cancel_proxy_mesh_preview(self) -> None:
        self._proxy_preview_job.cancel_running(clear_pending=True)
        self._window._update_action_state()

    def start_fracture_export(self, request, settings) -> None:
        if self.fracture_export_running:
            self._window._set_status("Fracture export already running...")
            return
        self._fracture_export_error_traceback = None
        self._fracture_export_result_received = False
        self._fracture_export_request = request
        self._fracture_export_settings = settings
        self._begin_status_activity("Fracture Export", "Writing Fracture USDA pieces...")
        try:
            process, message_queue, cancel_event = self._deps.start_fracture_export_process(request, settings)
        except Exception as exc:
            self.close_fracture_export_process()
            self._window._report_error("Fracture export failed", str(exc), status="Fracture export failed.")
            return
        self._fracture_export_process = process
        self._fracture_export_queue = message_queue
        self._fracture_export_cancel_event = cancel_event
        self._trace_worker("worker.spawn", "fracture_export", self._worker_queue_payload(message_queue))
        self._window._update_action_state()
        self._ensure_polling()

    def start_fracture_preview(self, request, settings) -> None:
        if not self.fracture_preview_running:
            self._fracture_preview_retry_count = 0
        self._begin_status_activity("Fracture Preview", "Generating Fracture Preview...")
        try:
            start_result = self._fracture_preview_job.start_latest(request, settings)
        except Exception as exc:
            self.close_fracture_preview_process()
            self._window._report_error("Fracture Preview failed", str(exc), status="Fracture Preview failed.")
            return
        if start_result.queued:
            self._window._set_status("Fracture Preview update queued...")
        self._window._update_action_state()
        self._ensure_polling()

    def start_part_preview(self, request, settings) -> None:
        self._begin_status_activity("Part Preview", "Generating Part Preview...")
        if hasattr(self._window, "_handle_part_preview_loading"):
            self._window._handle_part_preview_loading("Generating preview...")
        try:
            self._part_preview_job.start_latest(request, settings)
        except Exception as exc:
            self._part_preview_job.close()
            self._handle_part_preview_error(str(exc))
            return
        self._ensure_polling()

    def start_source_discovery(self, request) -> None:
        self._begin_status_activity("Inspecting XML", "Inspecting large XML in an isolated worker...")
        try:
            self._source_discovery_job.start_latest(request, True)
        except Exception as exc:
            self._source_discovery_job.close()
            self._window._handle_source_discovery_error(str(exc))
            return
        self._ensure_polling()

    def cancel_source_discovery(self) -> None:
        if self._source_discovery_job.has_process or self._source_discovery_job.has_pending:
            self._source_discovery_job.cancel_running(clear_pending=True)

    def cancel_fracture_preview(self) -> None:
        self._fracture_preview_job.cancel_running(clear_pending=True)
        self._window._update_action_state()

    def _start_proxy_mesh_process(self, request, settings) -> bool:
        try:
            process, message_queue, cancel_event = self._deps.start_proxy_mesh_process(
                request,
                settings,
                action="export",
            )
        except Exception as exc:
            self.close_proxy_mesh_process()
            self._window._report_error("Proxy Mesh generation failed", str(exc), status="Proxy Mesh generation failed.")
            return False
        self._proxy_mesh_process = process
        self._proxy_mesh_queue = message_queue
        self._proxy_mesh_cancel_event = cancel_event
        self._trace_worker("worker.spawn", "proxy_mesh", self._worker_queue_payload(message_queue))
        return True

    def _run_proxy_mesh_export_worker(self, *, request, settings) -> None:
        try:
            result = self._deps.export_proxy_usda_from_source_request(request, settings)
            self._event_queue.put(("proxy_mesh_result", ProxyMeshJobResult(export=result)))
        except Exception as exc:
            self._event_queue.put(("proxy_mesh_error_traceback", traceback.format_exc()))
            self._event_queue.put(("proxy_mesh_result", ProxyMeshJobResult(error_message=str(exc))))

    def _run_generated_proxy_mesh_export_worker(self, *, request, proxy) -> None:
        try:
            result = self._deps.export_generated_proxy_usda_from_source_request(request, proxy)
            self._event_queue.put(("proxy_mesh_result", ProxyMeshJobResult(export=result)))
        except Exception as exc:
            self._event_queue.put(("proxy_mesh_error_traceback", traceback.format_exc()))
            self._event_queue.put(("proxy_mesh_result", ProxyMeshJobResult(error_message=str(exc))))

    def shutdown(self) -> None:
        self._poll_timer.stop()
        if self._conversion_cancel_event is not None:
            self._conversion_cancel_event.set()
        if self._conversion_process is not None and self._conversion_process.is_alive():
            with suppress(Exception):
                self._conversion_process.join(timeout=0.2)
            if self._conversion_process.is_alive():
                with suppress(Exception):
                    self._conversion_process.terminate()
                    self._conversion_process.join(timeout=0.2)
        if self._proxy_mesh_process is not None and self._proxy_mesh_process.is_alive():
            if self._proxy_mesh_cancel_event is not None:
                with suppress(Exception):
                    self._proxy_mesh_cancel_event.set()
            with suppress(Exception):
                self._proxy_mesh_process.join(timeout=0.2)
            if self._proxy_mesh_process.is_alive():
                with suppress(Exception):
                    self._proxy_mesh_process.terminate()
                    self._proxy_mesh_process.join(timeout=0.2)
        if self._fracture_export_process is not None and self._fracture_export_process.is_alive():
            if self._fracture_export_cancel_event is not None:
                with suppress(Exception):
                    self._fracture_export_cancel_event.set()
            with suppress(Exception):
                self._fracture_export_process.join(timeout=0.2)
            if self._fracture_export_process.is_alive():
                with suppress(Exception):
                    self._fracture_export_process.terminate()
                    self._fracture_export_process.join(timeout=0.2)
        if self._fracture_preview_job.has_process:
            self._fracture_preview_job.cancel_running(clear_pending=True)
        if self._part_preview_job.has_process:
            self._part_preview_job.cancel_running(clear_pending=True)
        if self._wind_preview_job.has_process:
            self._wind_preview_job.cancel_running(clear_pending=True)
        if self._wind_refresh_process_job.has_process:
            self._wind_refresh_process_job.cancel_running(clear_pending=True)
        if self._source_discovery_job.has_process:
            self._source_discovery_job.cancel_running(clear_pending=True)
        self.close_conversion_process()
        self.close_proxy_mesh_process()
        self.close_proxy_preview_process()
        self.close_fracture_export_process()
        self.close_fracture_preview_process()
        self.close_part_preview_process()
        self.close_wind_preview_process()
        self.close_wind_refresh_process()
        self.close_source_discovery_process()

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
                    payload.get("message") or "Wind JSON worker returned an error payload without a message.",
                    details=self._deps.format_wind_error(payload),
                    status="Wind JSON generation failed.",
                )
            elif event_name == "proxy_mesh_error_traceback":
                self._proxy_mesh_error_traceback = str(payload)
            elif event_name == "proxy_mesh_result":
                self._proxy_mesh_result_received = True
                self._handle_proxy_mesh_job_result(payload)
        if self._drain_conversion_process_queue():
            keep_polling = True

        if self._drain_wind_refresh_process_queue():
            keep_polling = True

        if self._wind_refresh_process_job.running:
            keep_polling = True
        elif self._wind_refresh_process_job.has_process and not self._wind_refresh_process_job.result_received:
            if self._drain_wind_refresh_process_queue():
                keep_polling = True
            if self._wind_refresh_process_job.has_process and not self._wind_refresh_process_job.result_received:
                self._handle_wind_refresh_process_crash()
                if self._wind_refresh_process_job.has_process:
                    keep_polling = True

        if self._conversion_process is not None and self._conversion_process.is_alive():
            keep_polling = True
        elif self._conversion_process is not None and not self._conversion_result_received:
            if self._drain_conversion_process_queue():
                keep_polling = True
            if self._conversion_process is not None and not self._conversion_result_received:
                self._handle_async_process_crash()
        elif self._conversion_thread is not None and self._conversion_thread.is_alive():
            keep_polling = True

        if self._proxy_mesh_queue is not None:
            for event_name, payload in self._deps.drain_process_queue(self._proxy_mesh_queue):
                keep_polling = True
                if event_name == "error_traceback":
                    self._proxy_mesh_error_traceback = str(payload)
                elif event_name == "result":
                    self._proxy_mesh_result_received = True
                    self._handle_proxy_mesh_job_result(payload)

        if self._proxy_mesh_process is not None and self._proxy_mesh_process.is_alive():
            keep_polling = True
        elif self._proxy_mesh_process is not None and not self._proxy_mesh_result_received:
            self._handle_proxy_mesh_process_crash()
        elif self._proxy_mesh_thread is not None and self._proxy_mesh_thread.is_alive():
            keep_polling = True

        if self._drain_wind_preview_queue():
            keep_polling = True

        if self._wind_preview_job.running:
            keep_polling = True
        elif self._wind_preview_job.has_process and not self._wind_preview_job.result_received:
            if self._drain_wind_preview_queue():
                keep_polling = True
            if self._wind_preview_job.has_process and not self._wind_preview_job.result_received:
                self._handle_wind_preview_process_crash()
                if self._wind_preview_job.has_process:
                    keep_polling = True

        if self._drain_proxy_preview_queue():
            keep_polling = True

        if self._proxy_preview_job.running:
            keep_polling = True
        elif self._proxy_preview_job.has_process and not self._proxy_preview_job.result_received:
            if self._drain_proxy_preview_queue():
                keep_polling = True
            if self._proxy_preview_job.has_process and not self._proxy_preview_job.result_received:
                self._handle_proxy_preview_process_crash()
                if self._proxy_preview_job.has_process:
                    keep_polling = True
        elif self._proxy_preview_job.has_pending:
            if self._proxy_preview_job.has_ready_pending:
                self._proxy_preview_job.start_pending_if_any()
            keep_polling = True

        if self._fracture_export_queue is not None:
            for event_name, payload in self._deps.drain_process_queue(self._fracture_export_queue):
                keep_polling = True
                if event_name == "error_traceback":
                    self._fracture_export_error_traceback = str(payload)
                elif event_name == "error":
                    self._fracture_export_result_received = True
                    self._handle_fracture_export_error(str(payload))
                elif event_name == "result":
                    self._fracture_export_result_received = True
                    self._handle_fracture_export_result(payload)

        if self._fracture_export_process is not None and self._fracture_export_process.is_alive():
            keep_polling = True
        elif self._fracture_export_process is not None and not self._fracture_export_result_received:
            self._handle_fracture_export_process_crash()

        if self._drain_fracture_preview_queue():
            keep_polling = True

        if self._fracture_preview_job.running:
            keep_polling = True
        elif self._fracture_preview_job.has_process and not self._fracture_preview_job.result_received:
            if self._drain_fracture_preview_queue():
                keep_polling = True
            if self._fracture_preview_job.has_process and not self._fracture_preview_job.result_received:
                self._handle_fracture_preview_process_crash()
                if self._fracture_preview_job.has_process:
                    keep_polling = True
        elif self._fracture_preview_job.has_pending:
            if self._fracture_preview_job.has_ready_pending:
                self._fracture_preview_job.start_pending_if_any()
            keep_polling = True

        if self._drain_part_preview_queue():
            keep_polling = True

        if self._part_preview_job.running:
            keep_polling = True
        elif self._part_preview_job.has_process and not self._part_preview_job.result_received:
            if self._drain_part_preview_queue():
                keep_polling = True
            if self._part_preview_job.has_process and not self._part_preview_job.result_received:
                self._handle_part_preview_process_crash()
                if self._part_preview_job.has_process:
                    keep_polling = True
        elif self._part_preview_job.has_pending:
            if self._part_preview_job.has_ready_pending:
                self._part_preview_job.start_pending_if_any()
            keep_polling = True

        if self._drain_source_discovery_queue():
            keep_polling = True

        if self._source_discovery_job.running:
            keep_polling = True
        elif self._source_discovery_job.has_process and not self._source_discovery_job.result_received:
            if self._drain_source_discovery_queue():
                keep_polling = True
            if self._source_discovery_job.has_process and not self._source_discovery_job.result_received:
                self._handle_source_discovery_process_crash()
                if self._source_discovery_job.has_process:
                    keep_polling = True
        elif self._source_discovery_job.has_pending:
            if self._source_discovery_job.has_ready_pending:
                self._source_discovery_job.start_pending_if_any()
            keep_polling = True

        if (
            self.wind_refresh_running
            or self.wind_json_running
            or self.wind_preview_running
            or self.proxy_mesh_running
            or self.proxy_preview_running
            or self.fracture_export_running
            or self.fracture_preview_running
            or self.part_preview_running
            or self.source_discovery_running
        ):
            keep_polling = True

        if keep_polling:
            return
        self._poll_timer.stop()

    def _drain_wind_preview_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._wind_preview_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            if event_name == "error":
                message = str(payload)
                if self._wind_preview_job.error_traceback:
                    message = f"{message}\n\n{self._wind_preview_job.error_traceback}"
                self._handle_wind_preview_error(message)
            elif event_name == "result":
                self._handle_wind_preview_result(payload)
        return received_event

    def _drain_wind_refresh_process_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._wind_refresh_process_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            if event_name == "error":
                message = str(payload)
                formatted_traceback = self._wind_refresh_process_job.error_traceback or ""
                if not self._wind_refresh_process_job.finish_current():
                    self._window._set_wind_refresh_running(False)
                    self._handle_wind_refresh_error(
                        _WindErrorPayload(
                            primary={
                                "type": "RuntimeError",
                                "message": message,
                                "traceback": formatted_traceback,
                            }
                        )
                    )
            elif event_name == "result":
                if not self._wind_refresh_process_job.finish_current():
                    self._window._set_wind_refresh_running(False)
                    self._window._handle_wind_data_loaded(payload, used_retry=False)
        return received_event

    def _handle_wind_refresh_process_crash(self) -> None:
        crash = self._wind_refresh_process_job.crash()
        message = f"Wind inspection worker crashed unexpectedly (exit code {crash.exit_code})."
        formatted_traceback = crash.error_traceback or ""
        if not self._wind_refresh_process_job.finish_current():
            self._window._set_wind_refresh_running(False)
            self._handle_wind_refresh_error(
                _WindErrorPayload(
                    primary={
                        "type": "RuntimeError",
                        "message": message,
                        "traceback": formatted_traceback,
                    }
                )
            )

    def _drain_fracture_preview_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._fracture_preview_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            elif event_name == "error":
                error_message = str(payload)
                if "Fracture job context:" not in error_message:
                    error_message = (
                        f"{error_message}\n"
                        f"{self._format_fracture_job_context(self._fracture_preview_job.request, self._fracture_preview_job.settings)}\n"
                        f"{self._format_runtime_crash_context()}"
                    )
                if self._fracture_preview_job.error_traceback and self._fracture_preview_job.error_traceback not in error_message:
                    error_message = f"{error_message}\n\n{self._fracture_preview_job.error_traceback}"
                self._handle_fracture_preview_error(error_message)
            elif event_name == "result":
                self._handle_fracture_preview_result(payload)
        return received_event

    def _drain_proxy_preview_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._proxy_preview_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            if event_name == "error":
                self._handle_proxy_preview_error(str(payload))
            elif event_name == "result":
                self._handle_proxy_preview_job_result(payload)
        return received_event

    def _drain_conversion_process_queue(self) -> bool:
        if self._conversion_queue is None:
            return False
        received_event = False
        for event_name, payload in self._deps.drain_process_queue(self._conversion_queue):
            received_event = True
            if event_name == "telemetry":
                self._handle_conversion_telemetry(payload)
            elif event_name == "error_traceback":
                self._conversion_error_traceback = str(payload)
            elif event_name == "result":
                self._conversion_result_received = True
                self._handle_conversion_job_result(payload)
        return received_event

    def _drain_part_preview_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._part_preview_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            if event_name == "error":
                message = str(payload)
                if self._part_preview_job.error_traceback:
                    message = f"{message}\n\n{self._part_preview_job.error_traceback}"
                self._handle_part_preview_error(message)
            elif event_name == "result":
                self._handle_part_preview_result(payload)
        return received_event

    def _drain_source_discovery_queue(self) -> bool:
        received_event = False
        for event_name, payload in self._source_discovery_job.drain():
            received_event = True
            if event_name == "error_traceback":
                continue
            if event_name == "error":
                message = str(payload)
                if self._source_discovery_job.error_traceback:
                    message = f"{message}\n\n{self._source_discovery_job.error_traceback}"
                if not self._source_discovery_job.finish_current():
                    self._window._handle_source_discovery_error(message)
            elif event_name == "result":
                if not self._source_discovery_job.finish_current():
                    self._window._handle_source_discovery_result(payload)
        return received_event

    def _handle_source_discovery_process_crash(self) -> None:
        crash = self._source_discovery_job.crash()
        message = f"Source discovery worker crashed unexpectedly (exit code {crash.exit_code})."
        if crash.error_traceback:
            message = f"{message}\n\n{crash.error_traceback}"
        if not self._source_discovery_job.finish_current():
            self._window._handle_source_discovery_error(message)

    def _handle_wind_refresh_error(self, payload: _WindErrorPayload) -> None:
        self._window._clear_pending_generate_after_refresh()
        if hasattr(self._window, "_clear_pending_wind_preview_after_refresh"):
            self._window._clear_pending_wind_preview_after_refresh()
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
        self._set_status_telemetry(telemetry)

    def _handle_async_process_crash(self) -> None:
        exit_code = self._conversion_process.exitcode if self._conversion_process is not None else None
        self._trace_worker("worker.crash", "conversion", {"exit_code": exit_code})
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
        self._trace_worker(
            "worker.result",
            "conversion",
            {"error": bool(job_result.error_message), "cancelled": bool(job_result.cancelled)},
        )
        self.close_conversion_process()

        if job_result.error_message:
            status = "Conversion cancelled." if job_result.cancelled else "Conversion failed."
            log_message = job_result.error_message
            if error_traceback:
                log_message = f"{log_message}\n\n{error_traceback}"
            if job_result.cancelled:
                self._finish_status_activity("cancelled", status)
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
            self._finish_status_activity("cancelled", "Conversion cancelled.")
            self._window._set_log("Conversion cancelled before a result was produced.")
            return

        resolved_request = request or ConversionRequest(
            input_paths=(result.input_path,),
            output_path=result.output_path,
        )
        self._window._set_log(format_conversion_results((result,), resolved_request))
        if result.usda_document is None:
            self._finish_status_activity("error", "Conversion finished with errors.")
            self._window._append_log("Conversion finished without a USDA document. See diagnostics above.")
            return

        self._finish_status_activity("success", f"Wrote USDA to {result.output_path}")
        self._window._show_info("Conversion complete", f"Wrote USDA to {result.output_path}")

    def _handle_proxy_mesh_process_crash(self) -> None:
        exit_code = self._proxy_mesh_process.exitcode if self._proxy_mesh_process is not None else None
        self._trace_worker("worker.crash", "proxy_mesh", {"exit_code": exit_code})
        if self._proxy_mesh_retry_count < 1 and self._proxy_mesh_request is not None and self._proxy_mesh_settings is not None:
            request = self._proxy_mesh_request
            settings = self._proxy_mesh_settings
            self._proxy_mesh_retry_count += 1
            self._close_proxy_mesh_process_handles()
            self._window._set_status(f"Proxy Mesh worker crashed once (exit code {exit_code}). Retrying...")
            self._start_proxy_mesh_process(request, settings)
            return
        crash_message = f"Proxy Mesh worker process crashed unexpectedly (exit code {exit_code})"
        crash_message = f"{crash_message}\n{self._format_worker_file_context(self._proxy_mesh_queue)}"
        if self._proxy_mesh_error_traceback:
            crash_message = f"{crash_message}\n\n{self._proxy_mesh_error_traceback}"
        self._handle_proxy_mesh_job_result(
            ProxyMeshJobResult(
                cancelled=bool(self._proxy_mesh_cancel_event and self._proxy_mesh_cancel_event.is_set()),
                error_message=crash_message,
            )
        )

    def _handle_proxy_mesh_job_result(self, job_result) -> None:
        error_traceback = self._proxy_mesh_error_traceback
        self._trace_worker("worker.result", "proxy_mesh", {"error": bool(job_result.error_message)})
        self.close_proxy_mesh_process()
        self._window._update_action_state()
        if job_result.error_message:
            log_message = job_result.error_message
            if error_traceback:
                log_message = f"{log_message}\n\n{error_traceback}"
            self._window._report_error(
                "Proxy Mesh generation failed",
                job_result.error_message,
                details=log_message,
                status="Proxy Mesh generation failed.",
            )
            return
        if job_result.export is None:
            self._window._report_error(
                "Proxy Mesh generation failed",
                "Proxy Mesh worker finished without an export result.",
                status="Proxy Mesh generation failed.",
            )
            return
        self._window._handle_proxy_mesh_export_result(job_result.export)

    def _handle_wind_preview_process_crash(self) -> None:
        crash = self._wind_preview_job.crash()
        if self._wind_preview_job.has_pending:
            self._wind_preview_job.finish_current()
            return
        if self._wind_preview_retry_count < 1 and crash.request is not None:
            self._wind_preview_retry_count += 1
            self._wind_preview_job.close_handles()
            self._window._set_status(f"Wind Preview worker crashed once (exit code {crash.exit_code}). Retrying...")
            if hasattr(self._window, "_handle_wind_preview_loading"):
                self._window._handle_wind_preview_loading("Retrying after worker crash...")
            try:
                self._wind_preview_job.start_latest(crash.request, crash.settings)
            except Exception as exc:
                self._wind_preview_job.close()
                self._handle_wind_preview_error(str(exc))
            return
        message = f"Wind Preview worker process crashed unexpectedly (exit code {crash.exit_code})"
        message = f"{message}\n{self._format_worker_file_context(crash.queue)}"
        message = f"{message}\n{self._format_runtime_crash_context()}"
        if crash.error_traceback:
            message = f"{message}\n\n{crash.error_traceback}"
        self._handle_wind_preview_error(message)

    def _handle_wind_preview_result(self, result) -> None:
        self._trace_worker("worker.result", "wind_preview", {"result": result is not None})
        if result is None:
            self._handle_wind_preview_error("Wind Preview worker finished without a preview result.")
            return
        if self._wind_preview_job.finish_current():
            return
        self._wind_preview_retry_count = 0
        self._window._update_action_state()
        self._window._handle_wind_preview_result(result)

    def _handle_wind_preview_error(self, message: str) -> None:
        self._trace_worker("worker.error", "wind_preview", {"message": message})
        if self._wind_preview_job.finish_current():
            return
        self._wind_preview_retry_count = 0
        self._window._update_action_state()
        if hasattr(self._window, "_handle_wind_preview_error_message"):
            self._window._handle_wind_preview_error_message(message)
        self._window._report_error(
            "Wind Preview failed",
            message,
            status="Wind Preview failed.",
        )

    def _handle_proxy_preview_process_crash(self) -> None:
        crash = self._proxy_preview_job.crash()
        if self._proxy_preview_job.has_pending:
            self._proxy_preview_job.finish_current()
            return
        if self._proxy_preview_retry_count < 1 and crash.request is not None and crash.settings is not None:
            self._proxy_preview_retry_count += 1
            self._proxy_preview_job.close_handles()
            self._window._set_status(f"Proxy Preview worker crashed once (exit code {crash.exit_code}). Retrying...")
            if hasattr(self._window, "_handle_proxy_preview_loading"):
                self._window._handle_proxy_preview_loading("Retrying after worker crash...")
            try:
                self._proxy_preview_job.start_latest(crash.request, crash.settings)
            except Exception as exc:
                self._proxy_preview_job.close()
                self._handle_proxy_preview_error(str(exc))
            return
        message = f"Proxy Preview worker process crashed unexpectedly (exit code {crash.exit_code})"
        message = f"{message}\n{self._format_worker_file_context(crash.queue)}"
        message = f"{message}\n{self._format_runtime_crash_context()}"
        if crash.error_traceback:
            message = f"{message}\n\n{crash.error_traceback}"
        self._handle_proxy_preview_error(message)

    def _handle_proxy_preview_job_result(self, job_result) -> None:
        error_traceback = self._proxy_preview_job.error_traceback
        request = self._proxy_preview_job.request
        work = self._proxy_preview_job.settings
        self._trace_worker("worker.result", "proxy_preview", {"error": bool(job_result.error_message)})
        if job_result.error_message:
            message = str(job_result.error_message)
            if (
                self._proxy_preview_retry_count < 1
                and request is not None
                and work is not None
                and _is_retryable_proxy_preview_error(message)
            ):
                self._proxy_preview_retry_count += 1
                self._proxy_preview_job.close_handles()
                self._window._set_status("Proxy Preview worker returned a transient error. Retrying...")
                if hasattr(self._window, "_handle_proxy_preview_loading"):
                    self._window._handle_proxy_preview_loading("Retrying...")
                try:
                    self._proxy_preview_job.start_latest(request, work)
                except Exception as exc:
                    self._proxy_preview_job.close()
                    self._handle_proxy_preview_error(str(exc))
                return
            if error_traceback:
                message = f"{message}\n\n{error_traceback}"
            self._handle_proxy_preview_error(message)
            return
        collision_meshes = getattr(job_result, "collision_meshes", None)
        if collision_meshes is not None:
            if self._proxy_preview_job.finish_current():
                return
            self._proxy_preview_retry_count = 0
            self._window._update_action_state()
            self._window._handle_proxy_collision_preview_result(work.settings, collision_meshes)
            return
        proxy = getattr(job_result, "proxy", None)
        if proxy is None:
            self._handle_proxy_preview_error("Proxy Preview worker finished without a preview result.")
            return
        if self._proxy_preview_job.finish_current():
            return
        self._proxy_preview_retry_count = 0
        self._window._update_action_state()
        self._window._handle_proxy_preview_result(proxy, getattr(job_result, "source_scene", None))

    def _handle_proxy_preview_error(self, message: str) -> None:
        self._trace_worker("worker.error", "proxy_preview", {"message": message})
        if self._proxy_preview_job.finish_current():
            return
        self._proxy_preview_retry_count = 0
        self._window._update_action_state()
        if hasattr(self._window, "_handle_proxy_preview_error_message"):
            self._window._handle_proxy_preview_error_message(message)

    def _handle_part_preview_process_crash(self) -> None:
        crash = self._part_preview_job.crash()
        message = f"Part Preview worker process crashed unexpectedly (exit code {crash.exit_code})"
        message = f"{message}\n{self._format_worker_file_context(crash.queue)}"
        message = f"{message}\n{self._format_runtime_crash_context()}"
        if crash.error_traceback:
            message = f"{message}\n\n{crash.error_traceback}"
        self._handle_part_preview_error(message)

    def _handle_part_preview_result(self, result) -> None:
        self._trace_worker("worker.result", "part_preview", {"result": result is not None})
        if result is None:
            self._handle_part_preview_error("Part Preview worker finished without a preview result.")
            return
        if self._part_preview_job.finish_current():
            return
        self._window._update_action_state()
        if hasattr(self._window, "_handle_part_preview_result"):
            self._window._handle_part_preview_result(result)

    def _handle_part_preview_error(self, message: str) -> None:
        self._trace_worker("worker.error", "part_preview", {"message": message})
        if self._part_preview_job.finish_current():
            return
        self._window._update_action_state()
        if hasattr(self._window, "_handle_part_preview_error_message"):
            self._window._handle_part_preview_error_message(message)

    def _handle_fracture_export_process_crash(self) -> None:
        exit_code = self._fracture_export_process.exitcode if self._fracture_export_process is not None else None
        self._trace_worker("worker.crash", "fracture_export", {"exit_code": exit_code})
        crash_message = f"Fracture export worker process crashed unexpectedly (exit code {exit_code})"
        crash_message = f"{crash_message}\n{self._format_fracture_job_context(self._fracture_export_request, self._fracture_export_settings)}"
        crash_message = f"{crash_message}\n{self._format_worker_file_context(self._fracture_export_queue)}"
        crash_message = f"{crash_message}\n{self._format_runtime_crash_context()}"
        if self._fracture_export_error_traceback:
            crash_message = f"{crash_message}\n\n{self._fracture_export_error_traceback}"
        self._handle_fracture_export_error(crash_message)

    def _handle_fracture_export_result(self, result) -> None:
        self._trace_worker("worker.result", "fracture_export", {"result": result is not None})
        self.close_fracture_export_process()
        self._window._update_action_state()
        if result is None:
            self._window._report_error(
                "Fracture export failed",
                "Fracture export worker finished without a result.",
                status="Fracture export failed.",
            )
            return
        self._window._handle_fracture_export_result(result)

    def _handle_fracture_preview_process_crash(self) -> None:
        crash = self._fracture_preview_job.crash()
        if self._fracture_preview_job.has_pending:
            self._fracture_preview_job.finish_current()
            return
        if self._fracture_preview_retry_count < 1 and crash.request is not None and crash.settings is not None:
            self._fracture_preview_retry_count += 1
            self._fracture_preview_job.close_handles()
            self._window._set_status(f"Fracture Preview worker crashed once (exit code {crash.exit_code}). Retrying...")
            if hasattr(self._window, "_fracture_preview_dialog") and self._window._fracture_preview_dialog is not None:
                self._window._fracture_preview_dialog.set_loading("Retrying after worker crash...")
            try:
                self._fracture_preview_job.start_latest(crash.request, crash.settings)
            except Exception as exc:
                self._fracture_preview_job.close()
                self._handle_fracture_preview_error(str(exc))
            return
        crash_message = f"Fracture preview worker process crashed unexpectedly (exit code {crash.exit_code})"
        crash_message = f"{crash_message}\n{self._format_fracture_job_context(crash.request, crash.settings)}"
        crash_message = f"{crash_message}\n{self._format_worker_file_context(crash.queue)}"
        crash_message = f"{crash_message}\n{self._format_runtime_crash_context()}"
        if crash.error_traceback:
            crash_message = f"{crash_message}\n\n{crash.error_traceback}"
        self._handle_fracture_preview_error(crash_message)

    def _format_fracture_job_context(self, request, settings) -> str:
        lines = ["Fracture job context:"]
        if request is None:
            lines.append("  request=<none>")
        else:
            if hasattr(request, "input_path"):
                input_line = f"  input_path={request.input_path}"
            else:
                input_paths = "; ".join(str(path) for path in request.input_paths)
                input_line = f"  input_paths={input_paths}"
            lines.extend(
                (
                    input_line,
                    f"  output_path={request.output_path}",
                    f"  output_directory={getattr(request, 'output_directory', '')}",
                    f"  cpu_profile={request.cpu_profile.value}",
                )
            )
        if settings is None:
            lines.append("  settings=<none>")
        elif hasattr(settings, "fracture"):
            fracture = settings.fracture
            lines.extend(
                (
                    f"  target_branch_count={fracture.target_piece_count}",
                    f"  force_stump_piece={fracture.force_stump_piece}",
                    f"  separate_stems={fracture.separate_stems}",
                    f"  branch_height_bias={fracture.branch_height_bias}",
                    f"  generate_caps={fracture.generate_caps}",
                    f"  preview_polycount={settings.final_polycount}",
                    f"  remove_small_branches={settings.branch_prune_aggression}",
                    f"  preview_base_priority={settings.base_mesh_priority}",
                    f"  preview_prototype_faces={settings.max_prototype_faces}",
                )
            )
        else:
            lines.extend(
                (
                    f"  target_branch_count={settings.target_piece_count}",
                    f"  force_stump_piece={settings.force_stump_piece}",
                    f"  separate_stems={settings.separate_stems}",
                    f"  branch_height_bias={settings.branch_height_bias}",
                    f"  generate_caps={settings.generate_caps}",
                )
            )
        return "\n".join(lines)

    def _format_worker_file_context(self, queue) -> str:
        lines = ["Worker file context:"]
        if queue is None:
            lines.append("  queue=<none>")
            return "\n".join(lines)
        for label in ("request_path", "result_path", "error_path", "stderr_path"):
            path = getattr(queue, label, None)
            if path is None:
                lines.append(f"  {label}=<none>")
                continue
            try:
                exists = path.exists()
                size = path.stat().st_size if exists else None
            except OSError:
                exists = False
                size = None
            lines.append(f"  {label}={path} exists={exists} size={size}")
        stderr_tail = self._worker_stderr_tail(queue)
        if stderr_tail:
            lines.append("Worker stderr tail:")
            lines.append(stderr_tail)
        return "\n".join(lines)

    def _handle_fracture_preview_result(self, result) -> None:
        self._trace_worker(
            "worker.result",
            "fracture_preview",
            {
                "preview_job_id": self._fracture_preview_job.active_job_id,
                "result": result is not None,
                "piece_count": getattr(getattr(result, "plan", None), "actual_piece_count", None),
            },
        )
        if self._fracture_preview_job.finish_current():
            return
        self._fracture_preview_retry_count = 0
        self._window._update_action_state()
        if result is None:
            self._window._report_error(
                "Fracture Preview failed",
                "Fracture preview worker finished without a result.",
                status="Fracture Preview failed.",
            )
            return
        self._window._handle_fracture_preview_result(result)

    def _handle_fracture_preview_error(self, message: str) -> None:
        error_traceback = self._fracture_preview_job.error_traceback
        if hasattr(self._window, "_trace"):
            self._window._trace(
                "worker.error",
                worker="fracture_preview",
                data={"message": message},
                debug_data={"traceback": error_traceback or ""},
            )
        else:
            self._trace_worker("worker.error", "fracture_preview", {"message": message})
        if self._fracture_preview_job.finish_current():
            return
        self._fracture_preview_retry_count = 0
        self._window._update_action_state()
        if hasattr(self._window, "_handle_fracture_preview_error_message"):
            self._window._handle_fracture_preview_error_message(message)
        log_message = message
        if error_traceback:
            log_message = f"{log_message}\n\n{error_traceback}"
        self._window._report_error(
            "Fracture Preview failed",
            message,
            details=log_message,
            status="Fracture Preview failed.",
        )

    def _handle_fracture_export_error(self, message: str) -> None:
        error_traceback = self._fracture_export_error_traceback
        self._trace_worker("worker.error", "fracture_export", {"message": message})
        self.close_fracture_export_process()
        self._window._update_action_state()
        log_message = message
        if error_traceback:
            log_message = f"{log_message}\n\n{error_traceback}"
        self._window._report_error(
            "Fracture export failed",
            message,
            details=log_message,
            status="Fracture export failed.",
        )

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

    def close_proxy_mesh_process(self) -> None:
        self._close_proxy_mesh_process_handles()
        self._proxy_mesh_request = None
        self._proxy_mesh_settings = None
        self._proxy_mesh_retry_count = 0

    def _close_proxy_mesh_process_handles(self) -> None:
        self._deps.close_process_queue(self._proxy_mesh_queue)
        self._proxy_mesh_process = None
        self._proxy_mesh_queue = None
        self._proxy_mesh_cancel_event = None
        self._proxy_mesh_error_traceback = None
        self._proxy_mesh_result_received = False
        self._proxy_mesh_thread = None

    def close_proxy_preview_process(self) -> None:
        self._proxy_preview_job.close()
        self._proxy_preview_retry_count = 0

    def close_fracture_export_process(self) -> None:
        self._deps.close_process_queue(self._fracture_export_queue)
        self._fracture_export_process = None
        self._fracture_export_queue = None
        self._fracture_export_cancel_event = None
        self._fracture_export_request = None
        self._fracture_export_settings = None
        self._fracture_export_error_traceback = None
        self._fracture_export_result_received = False

    def close_fracture_preview_process(self) -> None:
        self._fracture_preview_job.close()
        self._fracture_preview_retry_count = 0

    def close_part_preview_process(self) -> None:
        self._part_preview_job.close()

    def close_wind_preview_process(self) -> None:
        self._wind_preview_job.close()

    def close_wind_refresh_process(self) -> None:
        self._wind_refresh_process_job.close()

    def close_source_discovery_process(self) -> None:
        self._source_discovery_job.close()

    def _trace_worker(self, kind: str, worker: str, data: dict[str, object] | None = None) -> None:
        if hasattr(self._window, "_trace"):
            self._window._trace(kind, worker=worker, data=data or {})

    def _worker_queue_payload(self, queue) -> dict[str, object]:
        payload: dict[str, object] = {}
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
        stderr_tail = self._worker_stderr_tail(queue)
        if stderr_tail:
            payload["stderr_tail"] = stderr_tail
        return payload

    def _worker_stderr_tail(self, queue) -> str:
        path = getattr(queue, "stderr_path", None)
        if path is None:
            return ""
        try:
            if not path.exists() or path.stat().st_size <= 0:
                return ""
            data = path.read_bytes()[-4000:]
        except OSError:
            return ""
        return data.decode("utf-8", errors="replace").strip()

    def _wind_preview_trace_payload(self, request, settings, job_id: int) -> dict[str, object]:
        payload: dict[str, object] = {"preview_job_id": job_id}
        if request is not None:
            payload["input_path"] = getattr(request, "input_path", "")
        return payload

    def _source_discovery_trace_payload(self, request, settings, job_id: int) -> dict[str, object]:
        return {
            "preview_job_id": job_id,
            "input_path": str(getattr(request, "input_path", "")),
        }

    def _fracture_preview_trace_payload(self, request, settings, job_id: int) -> dict[str, object]:
        payload: dict[str, object] = {
            "preview_job_id": job_id,
        }
        if request is not None:
            payload.update(
                {
                    "input_path": getattr(request, "input_path", ""),
                    "output_path": getattr(request, "output_path", ""),
                    "output_directory": getattr(request, "output_directory", ""),
                    "cpu_profile": getattr(getattr(request, "cpu_profile", None), "value", ""),
                }
            )
        if settings is not None and hasattr(settings, "fracture"):
            fracture = settings.fracture
            collision = getattr(settings, "collision", None)
            payload.update(
                {
                    "target_branch_count": fracture.target_piece_count,
                    "force_stump_piece": fracture.force_stump_piece,
                    "separate_stems": fracture.separate_stems,
                    "branch_height_bias": fracture.branch_height_bias,
                    "generate_caps": fracture.generate_caps,
                    "pinned_cut_joint_tokens": fracture.pinned_cut_joint_tokens,
                    "preview_polycount": settings.final_polycount,
                    "remove_small_branches": settings.branch_prune_aggression,
                    "preview_base_priority": settings.base_mesh_priority,
                    "preview_prototype_faces": settings.max_prototype_faces,
                }
            )
            if collision is not None:
                payload.update(
                    {
                        "collision_enabled": getattr(collision, "enabled", False),
                        "collision_mode": getattr(getattr(collision, "mode", None), "value", ""),
                        "collision_include_parts": getattr(collision, "include_instance_parts", False),
                    }
                )
        return payload

    def _proxy_preview_trace_payload(self, request, settings, job_id: int) -> dict[str, object]:
        payload: dict[str, object] = {"preview_job_id": job_id}
        if request is not None:
            payload.update(
                {
                    "input_path": getattr(request, "input_path", ""),
                    "output_path": getattr(request, "output_path", ""),
                    "cpu_profile": getattr(getattr(request, "cpu_profile", None), "value", ""),
                }
            )
        work = settings
        proxy_settings = getattr(work, "settings", work)
        if proxy_settings is not None:
            payload.update(
                {
                    "collision_only": bool(getattr(work, "collision_only", False)),
                    "final_polycount": getattr(proxy_settings, "final_polycount", None),
                    "bounds_inflation": getattr(proxy_settings, "bounds_inflation", None),
                    "density_resolution": getattr(proxy_settings, "density_resolution", None),
                    "base_mesh_priority": getattr(proxy_settings, "base_mesh_priority", None),
                    "fuse_base_mesh_vertices": getattr(proxy_settings, "fuse_base_mesh_vertices", None),
                    "branch_prune_aggression": getattr(proxy_settings, "branch_prune_aggression", None),
                }
            )
        return payload

    def _part_preview_trace_payload(self, request, settings, job_id: int) -> dict[str, object]:
        payload: dict[str, object] = {"preview_job_id": job_id}
        if request is not None:
            payload.update(
                {
                    "input_path": getattr(request, "input_path", ""),
                    "source_key": getattr(request, "source_key", ""),
                    "source_name": getattr(request, "source_name", ""),
                    "cpu_profile": getattr(getattr(request, "cpu_profile", None), "value", ""),
                }
            )
            config = getattr(request, "prototype_source_config", None)
            if config is not None:
                payload.update(
                    {
                        "source_mode": getattr(getattr(config, "mode", None), "value", ""),
                        "material_mode": getattr(getattr(config, "fbx_material_mode", None), "value", ""),
                        "simplification_percent": getattr(config, "simplification_percent", None),
                    }
                )
        if settings is not None:
            payload["display_mode"] = getattr(getattr(settings, "display_mode", None), "value", "")
        return payload


def _is_retryable_proxy_preview_error(message: str) -> bool:
    deterministic_fragments = (
        "Unsupported proxy mesh method",
        "Proxy final polycount must be greater than zero",
        "Proxy bounds inflation must be greater than zero",
        "Proxy density resolution must be greater than zero",
        "Missing resolved prototype",
        "has no resolved polygon payload",
        "requires base geometry or at least one repeated part instance",
        "malformed orientation quaternion",
        "zero-length orientation quaternion",
        "zero scale component",
        "Proxy mesh generation supports exactly one input XML",
        "Proxy mesh generation requires a source XML path",
        "Proxy source resolution failed",
    )
    return not any(fragment in message for fragment in deterministic_fragments)
