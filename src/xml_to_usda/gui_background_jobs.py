from __future__ import annotations

import gc
import threading
import traceback
from queue import Empty
import tkinter as tk

from .gui_formatters import format_conversion_results, format_telemetry_status, format_wind_group_summary, format_wind_json_result
from .models import ConversionJobResult, ConversionRequest, ConversionTelemetry


class GuiBackgroundJobsBridge:
    def __init__(self, app) -> None:
        self.app = app

    def start_wind_group_refresh_async(self, request) -> None:
        if self.app._wind_thread is not None and self.app._wind_thread.is_alive():
            self.app.status_var.set("Wind group inspection already running...")
            return
        self.app._active_wind_request_id += 1
        request_id = self.app._active_wind_request_id
        self.app.refresh_wind_button.configure(state="disabled")
        self.app.status_var.set("Inspecting wind groups in background...")
        self.app._set_log(
            "Inspecting wind groups in background.\n"
            "Large XML files may take a while; the UI should stay responsive."
        )
        self.app._wind_thread = threading.Thread(
            target=self.run_wind_group_worker,
            kwargs={"request_id": request_id, "request": request},
            daemon=True,
        )
        self.app._wind_thread.start()
        self.schedule_wind_queue_poll()

    def run_wind_group_worker(self, *, request_id: int, request) -> None:
        try:
            dynamic_wind = self.app._deps.inspect_wind_groups(request)
            self.app._wind_queue.put(("result", (request_id, request, dynamic_wind, None)))
        except Exception as exc:
            self.app._wind_queue.put(
                (
                    "result",
                    (
                        request_id,
                        request,
                        None,
                        {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    ),
                )
            )

    def schedule_wind_queue_poll(self) -> None:
        if self.app._wind_queue_job is not None:
            return
        self.app._wind_queue_job = self.app.root.after(100, self.poll_wind_queue)

    def poll_wind_queue(self) -> None:
        self.app._wind_queue_job = None
        keep_polling = False
        while True:
            try:
                event_name, payload = self.app._wind_queue.get_nowait()
            except Empty:
                break
            if event_name != "result":
                continue
            request_id, request, dynamic_wind, error_payload = payload
            if request_id != self.app._active_wind_request_id:
                continue
            self.app.refresh_wind_button.configure(state="normal")
            if error_payload is not None:
                retry_handled, recovered_wind = self.retry_wind_group_refresh_if_needed(
                    request=request,
                    error_payload=error_payload,
                )
                if recovered_wind is None:
                    if retry_handled:
                        continue
                    self.app._report_error(
                        "Wind group inspection failed",
                        error_payload["message"],
                        details=self.app._deps.format_wind_error(error_payload),
                        status="Wind group inspection failed.",
                    )
                    continue
                dynamic_wind = recovered_wind
            else:
                self.app._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
                self.app.status_var.set(
                    f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels."
                )
                self.app._set_log(format_wind_group_summary(dynamic_wind))
                continue

            self.app._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
            self.app.status_var.set(
                f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels after fallback retry."
            )
            self.app._set_log(
                format_wind_group_summary(dynamic_wind)
                + "\n\nBackground wind worker failed once and the main-thread retry succeeded."
            )
            gc.collect()
        if self.app._wind_thread is not None and self.app._wind_thread.is_alive():
            keep_polling = True
        elif self.app.refresh_wind_button.cget("state") != "normal":
            self.app.refresh_wind_button.configure(state="normal")
        if keep_polling:
            self.schedule_wind_queue_poll()

    def retry_wind_group_refresh_if_needed(self, *, request, error_payload: dict[str, str]) -> tuple[bool, object | None]:
        if not self.app._deps.should_retry_wind_error(error_payload.get("type", ""), error_payload.get("message", "")):
            return False, None
        self.app.status_var.set("Retrying wind group inspection on the main thread...")
        try:
            return True, self.app._deps.inspect_wind_groups(request)
        except Exception as retry_exc:
            retry_payload = {
                "type": type(retry_exc).__name__,
                "message": str(retry_exc),
                "traceback": traceback.format_exc(),
            }
            self.app._set_log(
                self.app._deps.format_wind_error(error_payload)
                + "\n\nMain-thread retry also failed:\n"
                + self.app._deps.format_wind_error(retry_payload)
            )
            self.app._append_runtime_log_entry(
                "error",
                "Wind group inspection failed",
                self.app._deps.format_wind_error(error_payload)
                + "\n\nMain-thread retry also failed:\n"
                + self.app._deps.format_wind_error(retry_payload),
            )
            return True, None

    def start_conversion_async(self, request: ConversionRequest) -> None:
        if self.app._conversion_process is not None and self.app._conversion_process.is_alive():
            self.app._report_error("Conversion running", "A conversion is already running.")
            return
        self.app._set_conversion_running(True)
        self.app.status_var.set("Preparing background conversion job.")
        self.app._set_log(
            "Starting background conversion.\n"
            "The UI stays responsive while a dedicated worker process normalizes XML, imports FBX, and writes USDA."
        )
        self.app._conversion_context = request
        self.app._conversion_result_received = False
        self.app._conversion_error_traceback = None
        self.app._last_conversion_telemetry = None
        try:
            self.app._conversion_process, self.app._conversion_queue, self.app._conversion_cancel_event = self.app._deps.start_conversion_process(
                request,
                runtime_paths=self.app._runtime_paths(),
            )
        except Exception as exc:
            self.app._set_conversion_running(False)
            self.close_conversion_process()
            self.app._report_error("Conversion failed", str(exc), status="Conversion failed.")
            return
        self.schedule_conversion_queue_poll()

    def schedule_conversion_queue_poll(self) -> None:
        if self.app._conversion_queue_job is not None:
            return
        self.app._conversion_queue_job = self.app.root.after(100, self.poll_conversion_queue)

    def poll_conversion_queue(self) -> None:
        self.app._conversion_queue_job = None
        keep_polling = False
        if self.app._conversion_queue is not None:
            for event_name, payload in self.app._deps.drain_process_queue(self.app._conversion_queue):
                if event_name == "telemetry":
                    self.handle_conversion_telemetry(payload)
                    keep_polling = True
                    continue
                if event_name == "error_traceback":
                    self.app._conversion_error_traceback = str(payload)
                    continue
                if event_name == "result":
                    self.app._conversion_result_received = True
                    self.handle_conversion_job_result(payload, self.app._conversion_context)
                    keep_polling = False
                    continue
        if self.app._conversion_process is not None and self.app._conversion_process.is_alive():
            keep_polling = True
        elif self.app._conversion_process is not None and not self.app._conversion_result_received:
            exit_code = self.app._conversion_process.exitcode
            crash_message = f"Conversion worker process crashed unexpectedly (exit code {exit_code})"
            if self.app.status_var.get():
                crash_message = f"{crash_message} after {self.app.status_var.get().rstrip('.')}"
            if self.app._last_conversion_telemetry is not None:
                crash_message = (
                    f"{crash_message}\n"
                    f"Last telemetry: {format_telemetry_status(self.app._last_conversion_telemetry)}"
                )
            crash_message = f"{crash_message}\n{self.format_runtime_crash_context()}"
            if self.app._conversion_error_traceback:
                crash_message = f"{crash_message}\n\n{self.app._conversion_error_traceback}"
            self.handle_conversion_job_result(
                ConversionJobResult(
                    cancelled=bool(self.app._conversion_cancel_event and self.app._conversion_cancel_event.is_set()),
                    error_message=crash_message,
                ),
                self.app._conversion_context,
            )
            keep_polling = False
        if keep_polling:
            self.schedule_conversion_queue_poll()

    def handle_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        self.app._last_conversion_telemetry = telemetry
        self.app.status_var.set(format_telemetry_status(telemetry))

    def format_runtime_crash_context(self) -> str:
        return (
            "Runtime context:\n"
            f"  frozen={bool(getattr(self.app._deps.sys, 'frozen', False))}\n"
            f"  executable={self.app._deps.sys.executable}\n"
            f"  argv0={self.app._deps.sys.argv[0] if self.app._deps.sys.argv else ''}\n"
            f"  jobs_root={self.app._runtime_paths().jobs_root}"
        )

    def handle_conversion_job_result(self, job_result: ConversionJobResult, request: ConversionRequest | None) -> None:
        self.app._set_conversion_running(False)
        error_traceback = self.app._conversion_error_traceback
        self.close_conversion_process()
        self.app._save_settings()

        if job_result.error_message:
            status = "Conversion cancelled." if job_result.cancelled else "Conversion failed."
            log_message = job_result.error_message
            if error_traceback:
                log_message = f"{log_message}\n\n{error_traceback}"
            if job_result.cancelled:
                self.app.status_var.set(status)
                self.app._set_log(log_message)
            else:
                self.app._report_error("Conversion failed", job_result.error_message, details=log_message, status=status)
            return

        result = job_result.result
        if result is None:
            self.app.status_var.set("Conversion cancelled.")
            self.app._set_log("Conversion cancelled before a result was produced.")
            return

        resolved_request = request or ConversionRequest(
            input_paths=(result.input_path,),
            output_path=result.output_path,
        )
        self.app._set_log(format_conversion_results((result,), resolved_request))
        if result.usda_document is None:
            self.app.status_var.set("Conversion finished with errors.")
            self.app._append_runtime_log_entry("error", "Conversion failed", "See diagnostics in the log area.")
            gc.collect()
            return

        self.app.status_var.set(f"Wrote USDA to {result.output_path}")
        self.app._deps.messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")
        gc.collect()

    def close_conversion_process(self) -> None:
        if self.app._conversion_queue_job is not None:
            try:
                self.app.root.after_cancel(self.app._conversion_queue_job)
            except tk.TclError:
                pass
            self.app._conversion_queue_job = None
        if self.app._conversion_process is not None:
            try:
                if self.app._conversion_process.is_alive():
                    self.app._conversion_process.join(timeout=0.1)
            except Exception:
                pass
        self.app._deps.close_process_queue(self.app._conversion_queue)
        self.app._conversion_process = None
        self.app._conversion_queue = None
        self.app._conversion_cancel_event = None
        self.app._conversion_context = None
        self.app._conversion_result_received = False
        self.app._conversion_error_traceback = None
        self.app._last_conversion_telemetry = None
