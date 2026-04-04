from __future__ import annotations

import gc
import json
import multiprocessing
import os
import sys
import threading
import traceback
import tkinter as tk
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

from .conversion_process import close_process_queue, drain_process_queue, start_conversion_process
from .fbx_adapter import inspect_fbx_material_slots
from .models import (
    BaseMaterialOverride,
    CleanupPolicy,
    ConversionRequest,
    ConversionJobResult,
    ConversionPhase,
    ConversionTelemetry,
    CpuProfile,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    FbxMaterialSlotOverride,
    FbxMaterialSlotSpec,
    MaterialPolicy,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .pipeline import (
    convert_file,
    discover_part_prototypes,
    discover_source_materials,
    generate_wind_json,
    inspect_wind_data,
    load_canonical_model,
)
from .runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces


class ConversionApp:
    SETTINGS_DIR = Path.home() / ".xml_to_usda"
    SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"
    RUNTIME_LOG_PATH = SETTINGS_DIR / "gui_runtime.log"
    RUNTIME_CACHE_ROOT = resolve_runtime_paths().cache_root
    MAX_WIND_INFLUENCE = 1.0
    MAX_SHIFT_TOP = 1.0
    ASYNC_WIND_REFRESH_THRESHOLD_BYTES = 5 * 1024 * 1024
    ASYNC_CONVERSION_THRESHOLD_BYTES = 5 * 1024 * 1024

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convert XML -> USDA")
        self.root.minsize(900, 620)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.cpu_profile_var = tk.StringVar(value=CpuProfile.BALANCED.value)
        self.preserve_temp_files_var = tk.BooleanVar(value=False)
        self.use_existing_part_meshes_var = tk.BooleanVar(value=False)
        self.material_policy_var = tk.StringVar(value=MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
        self.bark_material_var = tk.StringVar()
        self.leaves_material_var = tk.StringVar()
        self.single_material_var = tk.StringVar()
        self.gust_attenuation_var = tk.DoubleVar(value=0.0)
        self.is_ground_cover_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(
            value="Single-file mode. Convert and Dynamic Wind JSON generation are available."
        )
        self._sections: dict[str, dict[str, object]] = {}
        self._base_material_rows: list[dict[str, object]] = []
        self._part_mesh_rows: list[dict[str, object]] = []
        self._wind_group_rows: list[dict[str, object]] = []
        self._persisted_wind_group_settings: dict[str, dict[str, object]] = {}
        self._legacy_wind_group_settings: dict[str, dict[str, object]] = {}
        self._persisted_wind_group_settings_by_input_path: dict[str, dict[str, dict[str, object]]] = {}
        self._current_wind_settings_key: str | None = None
        self._persisted_base_material_settings_by_input_path: dict[str, list[dict[str, object]]] = {}
        self._current_base_material_settings_key: str | None = None
        self._persisted_part_mesh_settings_by_input_path: dict[str, list[dict[str, object]]] = {}
        self._current_part_mesh_settings_key: str | None = None
        self._fbx_material_slot_cache: dict[str, tuple[FbxMaterialSlotSpec, ...]] = {}
        self._pending_settings_save_job: str | None = None
        self._suspend_settings_save = False
        self._conversion_process = None
        self._conversion_cancel_event = None
        self._conversion_queue = None
        self._conversion_queue_job: str | None = None
        self._conversion_context: dict[str, object] | None = None
        self._conversion_result_received = False
        self._conversion_error_traceback: str | None = None
        self._last_conversion_telemetry: ConversionTelemetry | None = None
        self._wind_thread: threading.Thread | None = None
        self._wind_queue: Queue[tuple[str, object]] = Queue()
        self._wind_queue_job: str | None = None
        self._active_wind_request_id = 0
        self._load_settings()
        self._runtime_cleanup_summary = sweep_stale_job_workspaces(self._runtime_paths())

        self._build_layout()
        self._install_persistence_hooks()
        self.root.report_callback_exception = self._handle_tk_callback_exception
        self._show_startup_build_banner()
        self._show_startup_runtime_banner()
        self._apply_runtime_cleanup_summary()

    def _build_layout(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer = ttk.Frame(self.root)
        outer.grid(row=0, column=0, sticky="nsew")
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        self.scroll_canvas = tk.Canvas(outer, highlightthickness=0, borderwidth=0)
        self.scroll_canvas.grid(row=0, column=0, sticky="nsew")
        self.scrollbar = ttk.Scrollbar(outer, orient="vertical", command=self.scroll_canvas.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.scroll_canvas.configure(yscrollcommand=self.scrollbar.set)

        self.content_frame = ttk.Frame(self.scroll_canvas, padding=16)
        self.content_window = self.scroll_canvas.create_window((0, 0), window=self.content_frame, anchor="nw")
        self.content_frame.columnconfigure(1, weight=1)

        self.scroll_canvas.bind("<Configure>", self._handle_canvas_resize)
        self.content_frame.bind("<Configure>", self._handle_content_resize)
        self.root.bind_all("<MouseWheel>", self._handle_mousewheel, add="+")
        self.root.bind_all("<Button-4>", self._handle_mousewheel, add="+")
        self.root.bind_all("<Button-5>", self._handle_mousewheel, add="+")

        row = 0
        ttk.Label(self.content_frame, text="Source XML").grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.content_frame, textvariable=self.input_var).grid(
            row=row, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )
        ttk.Button(self.content_frame, text="Browse...", command=self.browse_input).grid(
            row=row, column=2, sticky="ew", pady=(0, 8)
        )

        row += 1
        ttk.Label(self.content_frame, text="Output USDA").grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.content_frame, textvariable=self.output_var).grid(
            row=row, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )
        ttk.Button(self.content_frame, text="Save As...", command=self.browse_output).grid(
            row=row, column=2, sticky="ew", pady=(0, 8)
        )

        row += 1
        ttk.Label(self.content_frame, text="CPU Profile").grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Combobox(
            self.content_frame,
            textvariable=self.cpu_profile_var,
            state="readonly",
            values=tuple(profile.value for profile in CpuProfile),
        ).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Label(
            self.content_frame,
            text="Balanced is the default recommended profile and keeps 2 logical CPUs free during heavy export.",
        ).grid(row=row, column=2, sticky="w", pady=(0, 8))

        row += 1
        ttk.Checkbutton(
            self.content_frame,
            text="Preserve temp files for debugging",
            variable=self.preserve_temp_files_var,
        ).grid(row=row, column=1, sticky="w", padx=(12, 12), pady=(0, 8))
        ttk.Label(
            self.content_frame,
            text="Off by default. When enabled, per-job temp manifests stay on disk for inspection.",
        ).grid(row=row, column=2, sticky="w", pady=(0, 8))

        row += 1
        materials_content = self._create_collapsible_section(self.content_frame, row, "Materials", "materials")
        self.materials_frame = materials_content
        materials_content.columnconfigure(0, weight=1)
        ttk.Label(
            materials_content,
            text=(
                "Base XML materials are discovered from the source file. "
                "Assign Unreal material paths per XML material slot."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.base_material_summary_var = tk.StringVar(value="Base XML material analysis has not run yet.")
        ttk.Label(materials_content, textvariable=self.base_material_summary_var).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.base_material_rows_container = ttk.Frame(materials_content)
        self.base_material_rows_container.grid(row=2, column=0, sticky="ew")
        self.base_material_rows_container.columnconfigure(0, weight=1)
        self._base_material_rows_placeholder = ttk.Label(
            self.base_material_rows_container,
            text="Select an XML file to load base XML materials.",
        )
        self._base_material_rows_placeholder.grid(row=0, column=0, sticky="w")

        row += 1
        part_mesh_content = self._create_collapsible_section(self.content_frame, row, "Part Mesh Reuse", "part_mesh")
        self.part_mesh_frame = part_mesh_content
        part_mesh_content.columnconfigure(0, weight=1)
        part_mesh_intro = ttk.Label(
            part_mesh_content,
            text=(
                "Rows are discovered from the XML leaf-reference mesh library. Choose XML mesh, existing Unreal asset, "
                "or a disk FBX file for each repeated prototype."
            ),
        )
        part_mesh_intro.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.part_mesh_summary_var = tk.StringVar(value="Repeated branch analysis has not run yet.")
        ttk.Label(part_mesh_content, textvariable=self.part_mesh_summary_var).grid(row=1, column=0, sticky="w", pady=(0, 8))

        self.part_mesh_rows_container = ttk.Frame(part_mesh_content)
        self.part_mesh_rows_container.grid(row=2, column=0, sticky="ew")
        self.part_mesh_rows_container.columnconfigure(0, weight=1)

        self._part_mesh_rows_placeholder = ttk.Label(self.part_mesh_rows_container, text="Select an XML file to load part meshes.")
        self._part_mesh_rows_placeholder.grid(row=0, column=0, sticky="w")

        row += 1
        wind_content = self._create_collapsible_section(self.content_frame, row, "Wind Profile", "wind")
        self.wind_frame = wind_content
        wind_content.columnconfigure(1, weight=1)
        wind_content.columnconfigure(3, weight=1)

        self.refresh_wind_button = ttk.Button(wind_content, text="Refresh Wind Groups", command=self.refresh_wind_groups)
        self.refresh_wind_button.grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Checkbutton(
            wind_content,
            text="Ground Cover",
            variable=self.is_ground_cover_var,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 8))

        ttk.Label(wind_content, text="Gust Attenuation").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.gust_value_var = tk.StringVar(value=f"{self.gust_attenuation_var.get():.2f}")
        tk.Scale(
            wind_content,
            from_=0.0,
            to=5.0,
            resolution=0.05,
            orient="horizontal",
            variable=self.gust_attenuation_var,
            command=lambda value: self._handle_gust_change(float(value)),
        ).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Label(wind_content, textvariable=self.gust_value_var, width=6).grid(
            row=1, column=3, sticky="e", pady=(0, 8)
        )

        ttk.Label(
            wind_content,
            text="Group sliders are built from explicit Generator levels. Group 0 is trunk unless Ground Cover is enabled.",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self.wind_groups_container = ttk.Frame(wind_content)
        self.wind_groups_container.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.wind_groups_container.columnconfigure(1, weight=1)
        self.wind_groups_container.columnconfigure(3, weight=1)

        row += 1
        footer = ttk.Frame(self.content_frame)
        footer.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        action_row = ttk.Frame(footer)
        action_row.grid(row=0, column=1, sticky="e")
        self.cancel_button = ttk.Button(action_row, text="Cancel", command=self.cancel_conversion, state="disabled")
        self.cancel_button.pack(side="right", padx=(0, 8))
        ttk.Button(action_row, text="Generate Wind JSON", command=self.run_generate_wind_json).pack(side="right")
        self.convert_button = ttk.Button(action_row, text="Convert", command=self.run_conversion)
        self.convert_button.pack(side="right", padx=(0, 8))

        row += 1
        log_content = self._create_collapsible_section(self.content_frame, row, "Log", "log")
        self.log_frame = log_content
        log_content.columnconfigure(0, weight=1)
        ttk.Button(log_content, text="Copy Log", command=self.copy_log).grid(row=0, column=0, sticky="e", pady=(0, 8))

        self.log_widget = tk.Text(log_content, wrap="word", height=18)
        self.log_widget.grid(row=1, column=0, sticky="nsew")
        self.log_widget.configure(state="disabled")
        self.log_widget.bind("<Control-c>", self._handle_copy_shortcut)
        self.log_widget.bind("<Control-C>", self._handle_copy_shortcut)

        self._refresh_scroll_region()

    def browse_input(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select SpeedTree XML",
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
        )
        if not selected:
            return
        current_input = self.input_var.get().strip()
        self.status_var.set("Source XML selected. Running XML analysis...")
        self.input_var.set(selected)
        if not self.output_var.get():
            self.output_var.set(str(Path(selected).with_suffix(".usda")))
        if current_input == selected:
            self._handle_source_path_change()

    def browse_output(self) -> None:
        initial = self.output_var.get() or "tree.usda"
        selected = filedialog.asksaveasfilename(
            title="Select USDA output",
            defaultextension=".usda",
            initialfile=Path(initial).name,
            filetypes=[("USDA files", "*.usda"), ("All files", "*.*")],
        )
        if selected:
            self.output_var.set(selected)

    def refresh_wind_groups(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file before loading wind groups.")
            return
        if self._should_refresh_wind_groups_async(input_path):
            self._start_wind_group_refresh_async(input_path)
            return
        try:
            dynamic_wind = inspect_wind_data(input_path, is_ground_cover=bool(self.is_ground_cover_var.get()))
        except Exception as exc:
            self._report_error("Wind group inspection failed", str(exc), status="Wind group inspection failed.")
            return

        self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
        self.status_var.set(
            f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels."
        )
        self._set_log(format_wind_group_summary(dynamic_wind))
        gc.collect()

    def _should_refresh_wind_groups_async(self, input_path: str) -> bool:
        try:
            return Path(input_path).stat().st_size >= self.ASYNC_WIND_REFRESH_THRESHOLD_BYTES
        except OSError:
            return False

    def _start_wind_group_refresh_async(self, input_path: str) -> None:
        if self._wind_thread is not None and self._wind_thread.is_alive():
            self.status_var.set("Wind group inspection already running...")
            return
        self._active_wind_request_id += 1
        request_id = self._active_wind_request_id
        self.refresh_wind_button.configure(state="disabled")
        self.status_var.set("Inspecting wind groups in background...")
        self._set_log(
            "Inspecting wind groups in background.\n"
            "Large XML files may take a while; the UI should stay responsive."
        )
        self._wind_thread = threading.Thread(
            target=self._run_wind_group_worker,
            kwargs={
                "request_id": request_id,
                "input_path": input_path,
                "is_ground_cover": bool(self.is_ground_cover_var.get()),
            },
            daemon=True,
        )
        self._wind_thread.start()
        self._schedule_wind_queue_poll()

    def _run_wind_group_worker(self, *, request_id: int, input_path: str, is_ground_cover: bool) -> None:
        try:
            dynamic_wind = inspect_wind_data(input_path, is_ground_cover=is_ground_cover)
            self._wind_queue.put(("result", (request_id, input_path, is_ground_cover, dynamic_wind, None)))
        except Exception as exc:
            self._wind_queue.put(
                (
                    "result",
                    (
                        request_id,
                        input_path,
                        is_ground_cover,
                        None,
                        {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "traceback": traceback.format_exc(),
                        },
                    ),
                )
            )

    def _schedule_wind_queue_poll(self) -> None:
        if self._wind_queue_job is not None:
            return
        self._wind_queue_job = self.root.after(100, self._poll_wind_queue)

    def _poll_wind_queue(self) -> None:
        self._wind_queue_job = None
        keep_polling = False
        while True:
            try:
                event_name, payload = self._wind_queue.get_nowait()
            except Empty:
                break
            if event_name != "result":
                continue
            request_id, input_path, is_ground_cover, dynamic_wind, error_payload = payload
            if request_id != self._active_wind_request_id:
                continue
            self.refresh_wind_button.configure(state="normal")
            if error_payload is not None:
                retry_handled, recovered_wind = self._retry_wind_group_refresh_if_needed(
                    input_path=input_path,
                    is_ground_cover=is_ground_cover,
                    error_payload=error_payload,
                )
                if recovered_wind is None:
                    if retry_handled:
                        continue
                    self._report_error(
                        "Wind group inspection failed",
                        error_payload["message"],
                        details=self._format_wind_refresh_error(error_payload),
                        status="Wind group inspection failed.",
                    )
                    continue
                dynamic_wind = recovered_wind
            else:
                self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
                self.status_var.set(
                    f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels."
                )
                self._set_log(format_wind_group_summary(dynamic_wind))
                continue

            self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
            self.status_var.set(
                f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels after fallback retry."
            )
            self._set_log(
                format_wind_group_summary(dynamic_wind)
                + "\n\nBackground wind worker failed once and the main-thread retry succeeded."
            )
            gc.collect()
        if self._wind_thread is not None and self._wind_thread.is_alive():
            keep_polling = True
        elif self.refresh_wind_button.cget("state") != "normal":
            self.refresh_wind_button.configure(state="normal")
        if keep_polling:
            self._schedule_wind_queue_poll()

    def _retry_wind_group_refresh_if_needed(
        self,
        *,
        input_path: str,
        is_ground_cover: bool,
        error_payload: dict[str, str],
    ) -> tuple[bool, object | None]:
        if not self._should_retry_failed_wind_refresh(error_payload):
            return False, None
        self.status_var.set("Retrying wind group inspection on the main thread...")
        try:
            return True, inspect_wind_data(input_path, is_ground_cover=is_ground_cover)
        except Exception as retry_exc:
            retry_payload = {
                "type": type(retry_exc).__name__,
                "message": str(retry_exc),
                "traceback": traceback.format_exc(),
            }
            self._set_log(
                self._format_wind_refresh_error(error_payload)
                + "\n\nMain-thread retry also failed:\n"
                + self._format_wind_refresh_error(retry_payload)
            )
            self._append_runtime_log_entry(
                "error",
                "Wind group inspection failed",
                self._format_wind_refresh_error(error_payload)
                + "\n\nMain-thread retry also failed:\n"
                + self._format_wind_refresh_error(retry_payload),
            )
            return True, None

    def _should_retry_failed_wind_refresh(self, error_payload: dict[str, str]) -> bool:
        error_type = error_payload.get("type", "")
        message = error_payload.get("message", "")
        return error_type == "SystemError" or "bad argument to internal function" in message or "setobject.c" in message

    def _format_wind_refresh_error(self, error_payload: dict[str, str]) -> str:
        error_type = error_payload.get("type", "Exception")
        message = error_payload.get("message", "")
        formatted_traceback = error_payload.get("traceback", "").strip()
        lines = [f"{error_type}: {message}"]
        if formatted_traceback:
            lines.extend(["", formatted_traceback])
        return "\n".join(lines).strip()

    def run_conversion(self) -> None:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        cpu_profile = self._current_cpu_profile()
        cleanup_policy = self._current_cleanup_policy()
        material_policy = self._current_material_policy()
        bark_material_path = self.bark_material_var.get().strip()
        leaves_material_path = self.leaves_material_var.get().strip()
        single_material_path = self.single_material_var.get().strip()
        effective_bark_material_path = bark_material_path or None
        effective_leaves_material_path = leaves_material_path or None
        effective_single_material_path = single_material_path or None
        if material_policy == MaterialPolicy.SINGLE_MATERIAL:
            effective_bark_material_path = None
            effective_leaves_material_path = None
        else:
            effective_single_material_path = None
        if not input_path:
            self._report_error("Missing input", "Select a source XML file.")
            return
        if not output_path:
            self._report_error("Missing output", "Select an output USDA path.")
            return
        try:
            base_material_overrides = self._collect_base_material_overrides()
            prototype_source_configs = self._collect_part_source_configs()
            use_existing_part_meshes, part_mesh_asset_paths = self._collect_part_mesh_overrides()
        except ValueError as exc:
            self._report_error("Invalid PartMesh mapping", str(exc))
            return
        use_explicit_material_contract = self._should_use_explicit_material_contract(
            base_material_overrides,
            prototype_source_configs,
        )

        validation_error = (
            self._validate_explicit_material_paths()
            if use_explicit_material_contract
            else self._validate_material_paths(
                material_policy,
                bark_material_path,
                leaves_material_path,
                single_material_path,
            )
        )
        if validation_error is not None:
            self._report_error("Invalid material path", validation_error)
            return

        has_fbx_sources = any(config.mode == PrototypeSourceMode.FBX_FILE for config in prototype_source_configs)
        run_conversion_async = has_fbx_sources or self._should_run_conversion_async(input_path)
        uses_new_source_contract = has_fbx_sources or (
            prototype_source_configs
            and (
                cpu_profile != CpuProfile.BALANCED
                or any(config.mode != PrototypeSourceMode.UNREAL_ASSET for config in prototype_source_configs)
            )
        )

        if run_conversion_async:
            self._start_conversion_async(
                input_path=input_path,
                output_path=output_path,
                cpu_profile=cpu_profile,
                cleanup_policy=cleanup_policy,
                material_policy=material_policy,
                bark_material_path=effective_bark_material_path,
                leaves_material_path=effective_leaves_material_path,
                single_material_path=effective_single_material_path,
                base_material_overrides=base_material_overrides,
                use_explicit_material_contract=use_explicit_material_contract,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
                prototype_source_configs=prototype_source_configs,
            )
            return

        try:
            convert_kwargs = {
                "material_policy": material_policy,
                "bark_material_path": effective_bark_material_path,
                "leaves_material_path": effective_leaves_material_path,
                "single_material_path": effective_single_material_path,
                "cleanup_policy": cleanup_policy,
            }
            if use_explicit_material_contract or uses_new_source_contract:
                convert_kwargs["cpu_profile"] = cpu_profile
                convert_kwargs["cleanup_policy"] = cleanup_policy
                convert_kwargs["prototype_source_configs"] = prototype_source_configs
                convert_kwargs["base_material_overrides"] = base_material_overrides
                convert_kwargs["use_explicit_material_contract"] = use_explicit_material_contract
            else:
                convert_kwargs["use_existing_part_meshes"] = use_existing_part_meshes
                convert_kwargs["part_mesh_asset_paths"] = part_mesh_asset_paths
                convert_kwargs["cleanup_policy"] = cleanup_policy
            convert_kwargs["runtime_paths"] = self._runtime_paths()
            result = convert_file(input_path, output_path, **convert_kwargs)
        except Exception as exc:
            self._report_error("Conversion failed", str(exc), status="Conversion failed.")
            gc.collect()
            return

        self._save_settings()
        self._set_log(
            format_conversion_results(
                (result,),
                cpu_profile=cpu_profile,
                cleanup_policy=cleanup_policy,
                material_policy=material_policy,
                bark_material_path=effective_bark_material_path,
                leaves_material_path=effective_leaves_material_path,
                single_material_path=effective_single_material_path,
                base_material_overrides=base_material_overrides,
                use_explicit_material_contract=use_explicit_material_contract,
                prototype_source_configs=prototype_source_configs,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
            )
        )
        if result.usda_document is None:
            self.status_var.set("Conversion finished with errors.")
            self._append_runtime_log_entry("error", "Conversion failed", "See diagnostics in the log area.")
            gc.collect()
            return

        self.status_var.set(f"Wrote USDA to {result.output_path}")
        messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")
        gc.collect()

    def _start_conversion_async(
        self,
        *,
        input_path: str,
        output_path: str,
        cpu_profile: CpuProfile,
        cleanup_policy: CleanupPolicy,
        material_policy: MaterialPolicy,
        bark_material_path: str | None,
        leaves_material_path: str | None,
        single_material_path: str | None,
        base_material_overrides: tuple[BaseMaterialOverride, ...],
        use_explicit_material_contract: bool,
        use_existing_part_meshes: bool,
        part_mesh_asset_paths: tuple[tuple[str, str], ...],
        prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    ) -> None:
        if self._conversion_process is not None and self._conversion_process.is_alive():
            self._report_error("Conversion running", "A conversion is already running.")
            return

        self._set_conversion_running(True)
        self.status_var.set("Preparing background conversion job.")
        self._set_log(
            "Starting background conversion.\n"
            "The UI stays responsive while a dedicated worker process normalizes XML, imports FBX, and writes USDA."
        )
        request = ConversionRequest(
            input_paths=(input_path,),
            output_path=output_path,
            material_policy=material_policy,
            bark_material_path=bark_material_path,
            leaves_material_path=leaves_material_path,
            single_material_path=single_material_path,
            base_material_overrides=base_material_overrides,
            cpu_profile=cpu_profile,
            cleanup_policy=cleanup_policy,
            use_explicit_material_contract=use_explicit_material_contract,
            prototype_source_configs=prototype_source_configs,
            use_existing_part_meshes=use_existing_part_meshes,
            part_mesh_asset_paths=part_mesh_asset_paths,
        )
        self._conversion_context = {
            "cpu_profile": cpu_profile,
            "cleanup_policy": cleanup_policy,
            "material_policy": material_policy,
            "bark_material_path": bark_material_path,
            "leaves_material_path": leaves_material_path,
            "single_material_path": single_material_path,
            "base_material_overrides": base_material_overrides,
            "use_explicit_material_contract": use_explicit_material_contract,
            "prototype_source_configs": prototype_source_configs,
            "use_existing_part_meshes": use_existing_part_meshes,
            "part_mesh_asset_paths": part_mesh_asset_paths,
        }
        self._conversion_result_received = False
        self._conversion_error_traceback = None
        self._last_conversion_telemetry = None
        try:
            self._conversion_process, self._conversion_queue, self._conversion_cancel_event = start_conversion_process(
                request,
                runtime_paths=self._runtime_paths(),
            )
        except Exception as exc:
            self._set_conversion_running(False)
            self._close_conversion_process()
            self._report_error("Conversion failed", str(exc), status="Conversion failed.")
            return
        self._schedule_conversion_queue_poll()

    def _schedule_conversion_queue_poll(self) -> None:
        if self._conversion_queue_job is not None:
            return
        self._conversion_queue_job = self.root.after(100, self._poll_conversion_queue)

    def _poll_conversion_queue(self) -> None:
        self._conversion_queue_job = None
        keep_polling = False
        if self._conversion_queue is not None:
            for event_name, payload in drain_process_queue(self._conversion_queue):
                if event_name == "telemetry":
                    self._handle_conversion_telemetry(payload)
                    keep_polling = True
                    continue
                if event_name == "error_traceback":
                    self._conversion_error_traceback = str(payload)
                    continue
                if event_name == "result":
                    self._conversion_result_received = True
                    self._handle_conversion_job_result(payload, self._conversion_context or {})
                    keep_polling = False
                    continue
        if self._conversion_process is not None and self._conversion_process.is_alive():
            keep_polling = True
        elif self._conversion_process is not None and not self._conversion_result_received:
            exit_code = self._conversion_process.exitcode
            crash_message = (
                "Conversion worker process crashed unexpectedly"
                f" (exit code {exit_code})"
            )
            if self.status_var.get():
                crash_message = f"{crash_message} after {self.status_var.get().rstrip('.')}"
            if self._last_conversion_telemetry is not None:
                crash_message = (
                    f"{crash_message}\n"
                    f"Last telemetry: {_format_telemetry_status(self._last_conversion_telemetry)}"
                )
            crash_message = f"{crash_message}\n{self._format_runtime_crash_context()}"
            if self._conversion_error_traceback:
                crash_message = f"{crash_message}\n\n{self._conversion_error_traceback}"
            self._handle_conversion_job_result(
                ConversionJobResult(cancelled=bool(self._conversion_cancel_event and self._conversion_cancel_event.is_set()), error_message=crash_message),
                self._conversion_context or {},
            )
            keep_polling = False
        if keep_polling:
            self._schedule_conversion_queue_poll()

    def _handle_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        self._last_conversion_telemetry = telemetry
        self.status_var.set(_format_telemetry_status(telemetry))

    def _format_runtime_crash_context(self) -> str:
        return (
            "Runtime context:\n"
            f"  frozen={bool(getattr(sys, 'frozen', False))}\n"
            f"  executable={sys.executable}\n"
            f"  argv0={sys.argv[0] if sys.argv else ''}\n"
            f"  jobs_root={self._runtime_paths().jobs_root}"
        )

    def _handle_conversion_job_result(self, job_result: ConversionJobResult, context: dict[str, object]) -> None:
        self._set_conversion_running(False)
        error_traceback = self._conversion_error_traceback
        self._close_conversion_process()
        self._save_settings()

        if job_result.error_message:
            status = "Conversion cancelled." if job_result.cancelled else "Conversion failed."
            log_message = job_result.error_message
            if error_traceback:
                log_message = f"{log_message}\n\n{error_traceback}"
            if job_result.cancelled:
                self.status_var.set(status)
                self._set_log(log_message)
            else:
                self._report_error("Conversion failed", job_result.error_message, details=log_message, status=status)
            return

        result = job_result.result
        if result is None:
            self.status_var.set("Conversion cancelled.")
            self._set_log("Conversion cancelled before a result was produced.")
            return

        self._set_log(
            format_conversion_results(
                (result,),
                cpu_profile=context["cpu_profile"],
                cleanup_policy=context["cleanup_policy"],
                material_policy=context["material_policy"],
                bark_material_path=context["bark_material_path"],
                leaves_material_path=context["leaves_material_path"],
                single_material_path=context["single_material_path"],
                base_material_overrides=context["base_material_overrides"],
                use_explicit_material_contract=context["use_explicit_material_contract"],
                prototype_source_configs=context["prototype_source_configs"],
                use_existing_part_meshes=context["use_existing_part_meshes"],
                part_mesh_asset_paths=context["part_mesh_asset_paths"],
            )
        )
        if result.usda_document is None:
            self.status_var.set("Conversion finished with errors.")
            self._append_runtime_log_entry("error", "Conversion failed", "See diagnostics in the log area.")
            gc.collect()
            return

        self.status_var.set(f"Wrote USDA to {result.output_path}")
        messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")
        gc.collect()

    def _set_conversion_running(self, active: bool) -> None:
        self.convert_button.configure(state="disabled" if active else "normal")
        self.cancel_button.configure(state="normal" if active else "disabled")

    def _should_run_conversion_async(self, input_path: str) -> bool:
        try:
            return Path(input_path).stat().st_size >= self.ASYNC_CONVERSION_THRESHOLD_BYTES
        except OSError:
            return False

    def cancel_conversion(self) -> None:
        if self._conversion_process is None or not self._conversion_process.is_alive():
            return
        if self._conversion_cancel_event is not None:
            self._conversion_cancel_event.set()
        self.status_var.set("Cancelling conversion...")

    def run_generate_wind_json(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file.")
            return
        if not self._wind_group_rows:
            self.refresh_wind_groups()
            if not self._wind_group_rows:
                return

        output_path = str(self._derive_wind_json_output_path())
        try:
            result = generate_wind_json(
                input_path,
                output_path,
                group_settings=self._collect_wind_group_settings(),
                gust_attenuation=float(self.gust_attenuation_var.get()),
                is_ground_cover=bool(self.is_ground_cover_var.get()),
            )
        except Exception as exc:
            self._report_error("Wind JSON generation failed", str(exc), status="Wind JSON generation failed.")
            return

        self._save_settings()
        self._set_log(format_wind_json_result(result))
        self.status_var.set(f"Wrote wind JSON to {result.output_path}")
        messagebox.showinfo("Wind JSON complete", f"Wrote wind JSON to {result.output_path}")
        gc.collect()

    def copy_log(self) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(self._get_copy_text())

    def _handle_copy_shortcut(self, _event=None):
        self.copy_log()
        return "break"

    def _get_copy_text(self) -> str:
        try:
            return self.log_widget.get("sel.first", "sel.last")
        except tk.TclError:
            return self.log_widget.get("1.0", "end-1c")

    def _set_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        self.log_widget.delete("1.0", tk.END)
        self.log_widget.insert("1.0", text)
        self.log_widget.configure(state="disabled")

    def _append_log(self, text: str) -> None:
        self.log_widget.configure(state="normal")
        existing_text = self.log_widget.get("1.0", "end-1c")
        if existing_text:
            self.log_widget.insert(tk.END, f"\n\n{text}")
        else:
            self.log_widget.insert("1.0", text)
        self.log_widget.configure(state="disabled")

    def _show_startup_build_banner(self) -> None:
        banner = self._render_startup_build_banner()
        if not banner:
            return
        self._set_log(banner)
        self._append_runtime_log_entry("info", "Build banner", banner)

    def _show_startup_runtime_banner(self) -> None:
        banner = self._render_startup_runtime_banner()
        if not banner:
            return
        self._append_log(banner)
        self._append_runtime_log_entry("info", "Runtime banner", banner)

    def _render_startup_build_banner(self) -> str:
        build_info = self._load_build_info()
        if not build_info:
            return ""

        built_at = str(build_info.get("built_at", "")).strip() or "<unknown>"
        build_mode = str(build_info.get("build_mode", "")).strip() or "unknown"
        python_exe = str(build_info.get("python_exe", "")).strip() or "<unknown>"
        exe_path = str(build_info.get("exe_path", "")).strip() or "<unknown>"

        lines = [
            "Build info:",
            f"  built_at: {built_at}",
            f"  mode: {build_mode}",
            f"  exe: {exe_path}",
            f"  python: {python_exe}",
        ]

        git_branch = str(build_info.get("git_branch", "")).strip()
        if git_branch:
            lines.append(f"  git_branch: {git_branch}")
        git_head = str(build_info.get("git_head", "")).strip()
        if git_head:
            lines.append(f"  git_head: {git_head}")
        git_dirty = build_info.get("git_dirty")
        if isinstance(git_dirty, bool):
            lines.append(f"  git_dirty: {git_dirty}")
        summary = str(build_info.get("change_summary", "")).strip()
        if summary:
            lines.append(f"  changes: {summary}")
        return "\n".join(lines)

    def _load_build_info(self) -> dict[str, object]:
        candidate_paths = []
        for raw_path in (sys.argv[0], sys.executable):
            if not raw_path:
                continue
            try:
                candidate_paths.append(Path(raw_path).resolve().with_name("build_info.json"))
            except OSError:
                continue

        candidate_paths.append(Path(__file__).resolve().parents[2] / "dist" / "build_info.json")

        seen: set[Path] = set()
        for candidate in candidate_paths:
            if candidate in seen:
                continue
            seen.add(candidate)
            if not candidate.exists():
                continue
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
        return {}

    def _render_startup_runtime_banner(self) -> str:
        runtime_paths = self._runtime_paths()
        try:
            start_method = multiprocessing.get_start_method(allow_none=True)
        except RuntimeError:
            start_method = None
        meipass = getattr(sys, "_MEIPASS", None)
        lines = [
            "Runtime info:",
            f"  frozen: {bool(getattr(sys, 'frozen', False))}",
            f"  executable: {sys.executable}",
            f"  argv0: {sys.argv[0] if sys.argv else ''}",
            f"  pid: {os.getpid()}",
            f"  cwd: {os.getcwd()}",
            f"  start_method: {start_method or '<default>'}",
            f"  settings_path: {self.SETTINGS_PATH}",
            f"  runtime_log: {self.RUNTIME_LOG_PATH}",
            f"  jobs_root: {runtime_paths.jobs_root}",
        ]
        if meipass:
            lines.append(f"  meipass: {meipass}")
        return "\n".join(lines)

    def _report_error(
        self,
        title: str,
        message: str,
        *,
        details: str | None = None,
        status: str | None = None,
    ) -> None:
        self.status_var.set(status or title)
        log_message = details or message
        self._set_log(log_message)
        self._append_runtime_log_entry("error", title, log_message)

    def _append_runtime_log_entry(self, level: str, title: str, message: str) -> None:
        try:
            self.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            entry = f"[{timestamp}] {level.upper()} {title}\n{message.rstrip()}\n\n"
            with self.RUNTIME_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(entry)
        except OSError:
            return

    def _validate_material_paths(
        self,
        material_policy: MaterialPolicy,
        bark_material_path: str,
        leaves_material_path: str,
        single_material_path: str,
    ) -> str | None:
        checks: list[tuple[str, str]] = []
        if material_policy == MaterialPolicy.SINGLE_MATERIAL:
            checks.append(("Single", single_material_path))
        else:
            checks.extend((("Bark", bark_material_path), ("Leaves", leaves_material_path)))
        for label, path in checks:
            if path and not _is_valid_unreal_asset_path(path):
                return f"{label} material path must start with /Game/."
        return None

    def _validate_explicit_material_paths(self) -> str | None:
        for row in self._base_material_rows:
            material_path = str(row["material_path_var"].get()).strip()
            if material_path and not _is_valid_unreal_asset_path(material_path):
                return (
                    f"Base XML material path for "
                    f"{row['source_name']} (ID {row['source_id']}) must start with /Game/."
                )
        for row in self._part_mesh_rows:
            mode = PrototypeSourceMode(str(row["source_mode_var"].get()))
            if mode == PrototypeSourceMode.UNREAL_ASSET:
                continue
            part_material_mode = FbxMaterialMode(str(row["fbx_material_mode_var"].get()))
            if part_material_mode == FbxMaterialMode.SINGLE_MATERIAL:
                single_path = str(row["single_material_var"].get()).strip()
                if single_path and not _is_valid_unreal_asset_path(single_path):
                    return f"Single material path for {row['source_name']} must start with /Game/."
                continue
            if part_material_mode == FbxMaterialMode.MATERIAL_SLOTS:
                overrides = self._collect_part_row_material_slot_overrides(row)
                for override in overrides:
                    if override.ue_asset_path and not _is_valid_unreal_asset_path(override.ue_asset_path):
                        return (
                            f"FBX material slot path for {row['source_name']} "
                            f"slot {override.slot_name} must start with /Game/."
                        )
                if mode == PrototypeSourceMode.FBX_FILE and not any(
                    override.ue_asset_path for override in overrides
                ):
                    return (
                        f"Material Slots mode for {row['source_name']} requires at least one Unreal "
                        "material path in the discovered FBX material slots."
                    )
                continue
            for label, value in (
                ("Black", str(row["black_material_var"].get()).strip()),
                ("White", str(row["white_material_var"].get()).strip()),
            ):
                if value and not _is_valid_unreal_asset_path(value):
                    return f"{label} material path for {row['source_name']} must start with /Game/."
        return None

    def _collect_base_material_overrides(self) -> tuple[BaseMaterialOverride, ...]:
        if not self._base_material_rows:
            return ()
        overrides = []
        for row in self._base_material_rows:
            overrides.append(
                BaseMaterialOverride(
                    source_id=int(row["source_id"]),
                    source_name=str(row["source_name"]),
                    ue_asset_path=str(row["material_path_var"].get()).strip() or None,
                )
            )
        return tuple(overrides)

    def _should_use_explicit_material_contract(
        self,
        base_material_overrides: tuple[BaseMaterialOverride, ...],
        prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    ) -> bool:
        if any(override.ue_asset_path for override in base_material_overrides):
            return True
        for config in prototype_source_configs:
            if config.mode == PrototypeSourceMode.UNREAL_ASSET:
                continue
            if config.fbx_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT:
                return True
            if config.single_material_path or config.black_material_path or config.white_material_path:
                return True
            if config.mode == PrototypeSourceMode.FBX_FILE:
                return True
        return False

    def _collect_part_mesh_overrides(self) -> tuple[bool, tuple[tuple[str, str], ...]]:
        configs = self._collect_part_source_configs()
        mappings = tuple(
            (config.source_name or config.source_key, config.asset_path or "")
            for config in configs
            if config.mode == PrototypeSourceMode.UNREAL_ASSET and config.asset_path
        )
        return bool(mappings), mappings

    def _collect_part_source_configs(self) -> tuple[PrototypeSourceConfig, ...]:
        if not self._part_mesh_rows:
            return ()

        configs: list[PrototypeSourceConfig] = []
        for row in self._part_mesh_rows:
            mode = PrototypeSourceMode(str(row["source_mode_var"].get()))
            source_name = str(row["source_name"])
            source_key = str(row["source_key"])
            part_material_mode = FbxMaterialMode(str(row["fbx_material_mode_var"].get()))
            single_material_path = str(row["single_material_var"].get()).strip() or None
            black_material_path = str(row["black_material_var"].get()).strip() or None
            white_material_path = str(row["white_material_var"].get()).strip() or None
            material_slot_overrides = self._collect_part_row_material_slot_overrides(row)
            if mode == PrototypeSourceMode.XML_MESH:
                if (
                    part_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT
                    or single_material_path
                    or black_material_path
                    or white_material_path
                ):
                    configs.append(
                        PrototypeSourceConfig(
                            source_key=source_key,
                            source_name=source_name,
                            mode=mode,
                            fbx_material_mode=part_material_mode,
                            single_material_path=single_material_path,
                            black_material_path=black_material_path,
                            white_material_path=white_material_path,
                        )
                    )
                continue
            if mode == PrototypeSourceMode.UNREAL_ASSET:
                asset_path = str(row["asset_var"].get()).strip()
                if not asset_path:
                    continue
                if not _is_valid_unreal_asset_path(asset_path):
                    raise ValueError(f"PartMesh asset path for {source_name} must start with /Game/.")
                configs.append(
                    PrototypeSourceConfig(
                        source_key=source_key,
                        source_name=source_name,
                        mode=mode,
                        asset_path=asset_path,
                    )
                )
                continue

            fbx_path = str(row["fbx_var"].get()).strip()
            fbx_material_mode = FbxMaterialMode(str(row["fbx_material_mode_var"].get()))
            if not fbx_path:
                continue
            resolved = Path(fbx_path).expanduser().resolve()
            if not resolved.exists():
                raise ValueError(f"FBX file for {source_name} does not exist: {resolved}")
            configs.append(
                PrototypeSourceConfig(
                    source_key=source_key,
                    source_name=source_name,
                    mode=mode,
                    fbx_material_mode=part_material_mode,
                    fbx_path=str(resolved),
                    single_material_path=single_material_path,
                    black_material_path=black_material_path,
                    white_material_path=white_material_path,
                    fbx_material_slot_overrides=material_slot_overrides,
                )
            )
        return tuple(configs)

    def _handle_source_path_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        self._active_wind_request_id += 1
        input_path = self.input_var.get().strip()
        if not input_path:
            self._current_wind_settings_key = None
            self._clear_base_material_rows()
            self._clear_part_mesh_rows()
            self._clear_wind_group_controls()
            return
        path = Path(input_path)
        if not path.exists():
            return
        resolved_key = self._resolve_input_settings_key(input_path)
        self._current_wind_settings_key = resolved_key
        self._persisted_wind_group_settings = self._resolve_persisted_wind_settings_for_key(resolved_key)
        self._clear_wind_group_controls("Analyzing XML and loading wind groups...")
        try:
            self._refresh_base_material_rows(input_path)
            self._refresh_part_mesh_rows(input_path)
        except Exception as exc:
            self._report_error("XML analysis failed", str(exc), status="XML analysis failed.")
            return
        self.refresh_wind_groups()

    def _resolve_persisted_wind_settings_for_key(self, settings_key: str) -> dict[str, dict[str, object]]:
        if settings_key in self._persisted_wind_group_settings_by_input_path:
            return dict(self._persisted_wind_group_settings_by_input_path[settings_key])
        if not self._persisted_wind_group_settings_by_input_path:
            return dict(self._legacy_wind_group_settings)
        return {}

    def _clear_base_material_rows(self) -> None:
        self._current_base_material_settings_key = None
        self._base_material_rows.clear()
        self.base_material_summary_var.set("Base XML material analysis has not run yet.")
        for child in self.base_material_rows_container.winfo_children():
            child.destroy()
        self._base_material_rows_placeholder = ttk.Label(
            self.base_material_rows_container,
            text="Select an XML file to load base XML materials.",
        )
        self._base_material_rows_placeholder.grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def _refresh_base_material_rows(self, input_path: str) -> None:
        if self._suspend_settings_save:
            return
        self._suspend_settings_save = True
        try:
            materials = discover_source_materials(input_path)
            resolved_key = self._resolve_input_settings_key(input_path)
            self._current_base_material_settings_key = resolved_key
            persisted_rows = self._persisted_base_material_settings_by_input_path.get(resolved_key, [])
            self._rebuild_base_material_rows(materials, persisted_rows)
        finally:
            self._suspend_settings_save = False
        self._save_settings()

    def _rebuild_base_material_rows(
        self,
        materials: tuple[BaseMaterialOverride, ...],
        persisted_rows: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    ) -> None:
        for child in self.base_material_rows_container.winfo_children():
            child.destroy()
        self._base_material_rows.clear()

        if not materials:
            self.base_material_summary_var.set("No XML material slots were found in this file.")
            ttk.Label(self.base_material_rows_container, text="No XML material slots found in this XML.").grid(
                row=0, column=0, sticky="w"
            )
            self._refresh_scroll_region()
            return

        self.base_material_summary_var.set(f"Found {len(materials)} base XML material slot(s).")
        self.base_material_rows_container.columnconfigure(0, weight=1)
        header = ttk.Frame(self.base_material_rows_container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="XML Material").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Unreal Material Path").grid(row=0, column=2, sticky="w")

        persisted_by_id = {
            int(record.get("source_id")): record
            for record in persisted_rows
            if isinstance(record, dict) and str(record.get("source_id", "")).lstrip("-").isdigit()
        }

        for row_index, material in enumerate(materials, start=1):
            row_frame = ttk.Frame(self.base_material_rows_container)
            row_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 6))
            row_frame.columnconfigure(2, weight=1)
            ttk.Label(row_frame, text=material.source_name or f"Material_{material.source_id}").grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=str(material.source_id)).grid(row=0, column=1, sticky="w", padx=(12, 12))
            material_path_var = tk.StringVar(
                value=str(persisted_by_id.get(material.source_id, {}).get("ue_asset_path", ""))
            )
            entry = ttk.Entry(row_frame, textvariable=material_path_var)
            entry.grid(row=0, column=2, sticky="ew")
            material_path_var.trace_add("write", self._handle_persisted_field_change)
            self._base_material_rows.append(
                {
                    "source_id": material.source_id,
                    "source_name": material.source_name,
                    "material_path_var": material_path_var,
                    "entry": entry,
                }
            )
        self._refresh_scroll_region()

    def _clear_part_mesh_rows(self) -> None:
        self._current_part_mesh_settings_key = None
        self._part_mesh_rows.clear()
        self.part_mesh_summary_var.set("Repeated branch analysis has not run yet.")
        for child in self.part_mesh_rows_container.winfo_children():
            child.destroy()
        self._part_mesh_rows_placeholder = ttk.Label(
            self.part_mesh_rows_container,
            text="Select an XML file to load part meshes.",
        )
        self._part_mesh_rows_placeholder.grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def _clear_wind_group_controls(self, message: str = "Click Refresh Wind Groups to inspect wind settings.") -> None:
        for child in self.wind_groups_container.winfo_children():
            child.destroy()
        self._wind_group_rows.clear()
        if hasattr(self, "refresh_wind_button"):
            self.refresh_wind_button.configure(state="normal")
        ttk.Label(self.wind_groups_container, text=message).grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def _refresh_part_mesh_rows(self, input_path: str) -> None:
        if self._suspend_settings_save:
            return
        self._suspend_settings_save = True
        try:
            prototypes = discover_part_prototypes(input_path)
            resolved_key = self._resolve_input_settings_key(input_path)
            self._current_part_mesh_settings_key = resolved_key
            persisted_rows = self._persisted_part_mesh_settings_by_input_path.get(resolved_key, [])
            self._rebuild_part_mesh_rows(prototypes, persisted_rows)
        finally:
            self._suspend_settings_save = False
        self._save_settings()

    def _resolve_input_settings_key(self, input_path: str) -> str:
        return str(Path(input_path).expanduser().resolve())

    def _rebuild_part_mesh_rows(
        self,
        prototypes,
        persisted_rows: list[dict[str, object]] | tuple[dict[str, object], ...] = (),
    ) -> None:
        for child in self.part_mesh_rows_container.winfo_children():
            child.destroy()
        self._part_mesh_rows.clear()

        if not prototypes:
            self.part_mesh_summary_var.set("No repeated branch instances were found in this XML.")
            ttk.Label(self.part_mesh_rows_container, text="No repeated part meshes found in this XML.").grid(
                row=0, column=0, sticky="w"
            )
            self._refresh_scroll_region()
            return

        total_instances = sum(prototype.instance_count for prototype in prototypes)
        self.part_mesh_summary_var.set(
            f"Found {total_instances} repeated branch instances across {len(prototypes)} prototype(s)."
        )

        self.part_mesh_rows_container.columnconfigure(0, weight=1)
        header = ttk.Frame(self.part_mesh_rows_container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=2)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=0)
        header.columnconfigure(3, weight=1)
        header.columnconfigure(4, weight=4)
        header.columnconfigure(5, weight=4)
        header.columnconfigure(6, weight=2)
        header.columnconfigure(7, weight=3)
        header.columnconfigure(8, weight=3)
        header.columnconfigure(9, weight=3)
        header.columnconfigure(10, weight=0)
        ttk.Label(header, text="XML Mesh").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Mesh ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Instances").grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Source Mode").grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Unreal Object Path").grid(row=0, column=4, sticky="w", padx=(0, 12))
        ttk.Label(header, text="FBX File").grid(row=0, column=5, sticky="w")
        ttk.Label(header, text="Part Materials").grid(row=0, column=6, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Single Material").grid(row=0, column=7, sticky="w")
        ttk.Label(header, text="Black Material").grid(row=0, column=8, sticky="w", padx=(12, 0))
        ttk.Label(header, text="White Material").grid(row=0, column=9, sticky="w", padx=(12, 0))

        persisted_by_name = {
            str(record.get("source_name", "")): record
            for record in persisted_rows
            if isinstance(record, dict) and record.get("source_name")
        }
        persisted_by_key = {
            str(record.get("source_key", "")): record
            for record in persisted_rows
            if isinstance(record, dict) and record.get("source_key")
        }

        self._part_mesh_rows_placeholder = ttk.Label(self.part_mesh_rows_container, text="")
        row_index = 1
        for prototype in prototypes:
            row_frame = ttk.Frame(self.part_mesh_rows_container)
            row_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 6))
            row_frame.columnconfigure(0, weight=2)
            row_frame.columnconfigure(3, weight=1)
            row_frame.columnconfigure(4, weight=4)
            row_frame.columnconfigure(5, weight=4)
            row_frame.columnconfigure(6, weight=2)
            row_frame.columnconfigure(7, weight=3)
            row_frame.columnconfigure(8, weight=3)
            row_frame.columnconfigure(9, weight=3)

            mesh_id_text = f"Mesh_{prototype.source_mesh_id}" if prototype.source_mesh_id is not None else "<none>"
            display_name = prototype.source_name or prototype.source_key
            instance_count_text = str(prototype.instance_count)
            ttk.Label(row_frame, text=display_name).grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=mesh_id_text).grid(row=0, column=1, sticky="w", padx=(12, 12))
            ttk.Label(row_frame, text=instance_count_text).grid(row=0, column=2, sticky="w", padx=(0, 12))

            source_mode_var = tk.StringVar(value=PrototypeSourceMode.XML_MESH.value)
            use_unreal_var = tk.BooleanVar(value=False)
            asset_var = tk.StringVar(value="")
            fbx_var = tk.StringVar(value="")
            fbx_material_mode_var = tk.StringVar(value=FbxMaterialMode.VERTEX_COLOR_SPLIT.value)
            single_material_var = tk.StringVar(value="")
            black_material_var = tk.StringVar(value="")
            white_material_var = tk.StringVar(value="")
            source_mode_combo = ttk.Combobox(
                row_frame,
                textvariable=source_mode_var,
                state="readonly",
                values=tuple(mode.value for mode in PrototypeSourceMode),
                width=14,
            )
            asset_entry = ttk.Entry(row_frame, textvariable=asset_var)
            fbx_entry = ttk.Entry(row_frame, textvariable=fbx_var)
            fbx_material_mode_combo = ttk.Combobox(
                row_frame,
                textvariable=fbx_material_mode_var,
                state="readonly",
                values=(
                    FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                    FbxMaterialMode.SINGLE_MATERIAL.value,
                    FbxMaterialMode.MATERIAL_SLOTS.value,
                ),
                width=18,
            )
            single_material_entry = ttk.Entry(row_frame, textvariable=single_material_var)
            black_material_entry = ttk.Entry(row_frame, textvariable=black_material_var)
            white_material_entry = ttk.Entry(row_frame, textvariable=white_material_var)
            browse_button = ttk.Button(
                row_frame,
                text="Browse...",
                command=lambda var=fbx_var: self._browse_part_fbx(var),
            )
            source_mode_combo.grid(row=0, column=3, sticky="ew", padx=(0, 12))
            asset_entry.grid(row=0, column=4, sticky="ew")
            fbx_entry.grid(row=0, column=5, sticky="ew", padx=(12, 8))
            fbx_material_mode_combo.grid(row=0, column=6, sticky="ew", padx=(0, 12))
            single_material_entry.grid(row=0, column=7, sticky="ew")
            black_material_entry.grid(row=0, column=8, sticky="ew", padx=(12, 0))
            white_material_entry.grid(row=0, column=9, sticky="ew", padx=(12, 12))
            browse_button.grid(row=0, column=10, sticky="ew")
            material_slot_container = ttk.Frame(row_frame)
            material_slot_container.grid(row=1, column=4, columnspan=7, sticky="ew", pady=(4, 0))
            material_slot_container.columnconfigure(1, weight=1)
            material_slot_placeholder = ttk.Label(
                material_slot_container,
                text="FBX material slots appear here when Material Slots mode is enabled.",
            )
            material_slot_placeholder.grid(row=0, column=0, sticky="w")

            row_data = {
                "source_key": prototype.source_key,
                "source_name": display_name,
                "mesh_id": prototype.source_mesh_id,
                "instance_count": prototype.instance_count,
                "source_mode_var": source_mode_var,
                "use_unreal_var": use_unreal_var,
                "asset_var": asset_var,
                "fbx_var": fbx_var,
                "fbx_material_mode_var": fbx_material_mode_var,
                "single_material_var": single_material_var,
                "black_material_var": black_material_var,
                "white_material_var": white_material_var,
                "asset_entry": asset_entry,
                "fbx_entry": fbx_entry,
                "fbx_material_mode_combo": fbx_material_mode_combo,
                "single_material_entry": single_material_entry,
                "black_material_entry": black_material_entry,
                "white_material_entry": white_material_entry,
                "browse_button": browse_button,
                "source_mode_combo": source_mode_combo,
                "material_slot_container": material_slot_container,
                "material_slot_placeholder": material_slot_placeholder,
                "material_slot_rows": [],
                "restored_slot_override_records": (),
            }

            record = persisted_by_name.get(display_name) or persisted_by_key.get(str(prototype.source_key))
            if record is not None:
                restored_mode = str(record.get("source_mode", "")).strip() or (
                    PrototypeSourceMode.UNREAL_ASSET.value if bool(record.get("use_unreal_reference", False)) else PrototypeSourceMode.XML_MESH.value
                )
                if restored_mode not in {mode.value for mode in PrototypeSourceMode}:
                    restored_mode = PrototypeSourceMode.XML_MESH.value
                restored_fbx_material_mode = str(
                    record.get("fbx_material_mode", FbxMaterialMode.VERTEX_COLOR_SPLIT.value)
                ).strip()
                if restored_fbx_material_mode == FbxMaterialMode.AUTO.value:
                    restored_fbx_material_mode = FbxMaterialMode.VERTEX_COLOR_SPLIT.value
                if restored_fbx_material_mode not in {
                    FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                    FbxMaterialMode.SINGLE_MATERIAL.value,
                    FbxMaterialMode.MATERIAL_SLOTS.value,
                }:
                    restored_fbx_material_mode = FbxMaterialMode.VERTEX_COLOR_SPLIT.value
                source_mode_var.set(restored_mode)
                fbx_material_mode_var.set(restored_fbx_material_mode)
                use_unreal_var.set(restored_mode == PrototypeSourceMode.UNREAL_ASSET.value)
                asset_var.set(str(record.get("unreal_asset_path", "")))
                fbx_var.set(str(record.get("fbx_path", "")))
                single_material_var.set(str(record.get("single_material_path", "")))
                black_material_var.set(str(record.get("black_material_path", "")))
                white_material_var.set(str(record.get("white_material_path", "")))
                row_data["restored_slot_override_records"] = tuple(record.get("fbx_material_slot_overrides", ()))

            self._part_mesh_rows.append(row_data)
            self._handle_part_source_mode_change(row_data)
            asset_var.trace_add("write", self._handle_persisted_field_change)
            fbx_var.trace_add("write", self._handle_persisted_field_change)
            fbx_var.trace_add("write", lambda *_args, row=row_data: self._handle_part_source_mode_change(row))
            fbx_material_mode_var.trace_add("write", self._handle_persisted_field_change)
            single_material_var.trace_add("write", self._handle_persisted_field_change)
            black_material_var.trace_add("write", self._handle_persisted_field_change)
            white_material_var.trace_add("write", self._handle_persisted_field_change)
            source_mode_var.trace_add("write", self._handle_persisted_field_change)
            source_mode_var.trace_add(
                "write",
                lambda *_args, row=row_data, unreal_var=use_unreal_var: self._handle_source_mode_trace(row, unreal_var),
            )
            fbx_material_mode_var.trace_add(
                "write",
                lambda *_args, row=row_data: self._handle_part_source_mode_change(row),
            )
            use_unreal_var.trace_add("write", lambda *_args, mode_var=source_mode_var, unreal_var=use_unreal_var: self._handle_legacy_unreal_toggle(mode_var, unreal_var))
            row_index += 1

        self._refresh_scroll_region()

    def _browse_part_fbx(self, target_var: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Select part FBX",
            filetypes=[("FBX files", "*.fbx"), ("JSON test payloads", "*.json"), ("All files", "*.*")],
        )
        if selected:
            target_var.set(selected)

    def _handle_source_mode_trace(
        self,
        row: dict[str, object],
        use_unreal_var: tk.BooleanVar,
    ) -> None:
        self._handle_part_source_mode_change(row)
        use_unreal_var.set(str(row["source_mode_var"].get()) == PrototypeSourceMode.UNREAL_ASSET.value)

    def _handle_legacy_unreal_toggle(self, source_mode_var: tk.StringVar, use_unreal_var: tk.BooleanVar) -> None:
        if bool(use_unreal_var.get()):
            source_mode_var.set(PrototypeSourceMode.UNREAL_ASSET.value)
        elif source_mode_var.get() == PrototypeSourceMode.UNREAL_ASSET.value:
            source_mode_var.set(PrototypeSourceMode.XML_MESH.value)

    def _handle_part_source_mode_change(self, row: dict[str, object]) -> None:
        mode = PrototypeSourceMode(str(row["source_mode_var"].get()))
        asset_entry = row["asset_entry"]
        fbx_entry = row["fbx_entry"]
        fbx_material_mode_combo = row["fbx_material_mode_combo"]
        single_material_entry = row["single_material_entry"]
        black_material_entry = row["black_material_entry"]
        white_material_entry = row["white_material_entry"]
        browse_button = row["browse_button"]
        fbx_material_mode_var = row["fbx_material_mode_var"]

        asset_entry.configure(state="normal" if mode == PrototypeSourceMode.UNREAL_ASSET else "disabled")
        fbx_state = "normal" if mode == PrototypeSourceMode.FBX_FILE else "disabled"
        fbx_entry.configure(state=fbx_state)
        browse_button.configure(state=fbx_state)

        if mode == PrototypeSourceMode.FBX_FILE:
            allowed_material_modes = (
                FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                FbxMaterialMode.SINGLE_MATERIAL.value,
                FbxMaterialMode.MATERIAL_SLOTS.value,
            )
        else:
            allowed_material_modes = (
                FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                FbxMaterialMode.SINGLE_MATERIAL.value,
            )
        fbx_material_mode_combo.configure(
            state="readonly" if mode != PrototypeSourceMode.UNREAL_ASSET else "disabled",
            values=allowed_material_modes,
        )
        if str(fbx_material_mode_var.get()) not in allowed_material_modes:
            fbx_material_mode_var.set(FbxMaterialMode.VERTEX_COLOR_SPLIT.value)

        material_controls_enabled = mode != PrototypeSourceMode.UNREAL_ASSET
        material_mode = FbxMaterialMode(str(fbx_material_mode_var.get()))
        single_state = (
            "normal"
            if material_controls_enabled and material_mode == FbxMaterialMode.SINGLE_MATERIAL
            else "disabled"
        )
        split_state = (
            "normal"
            if material_controls_enabled and material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
            else "disabled"
        )
        single_material_entry.configure(state=single_state)
        black_material_entry.configure(state=split_state)
        white_material_entry.configure(state=split_state)
        self._refresh_part_row_material_slot_controls(row)

    def _refresh_part_row_material_slot_controls(self, row: dict[str, object]) -> None:
        container = row["material_slot_container"]
        placeholder = row["material_slot_placeholder"]
        for child in container.winfo_children():
            child.destroy()
        row["material_slot_rows"] = []
        placeholder = ttk.Label(
            container,
            text="FBX material slots appear here when Material Slots mode is enabled.",
        )
        row["material_slot_placeholder"] = placeholder
        mode = PrototypeSourceMode(str(row["source_mode_var"].get()))
        material_mode = FbxMaterialMode(str(row["fbx_material_mode_var"].get()))
        if mode != PrototypeSourceMode.FBX_FILE or material_mode != FbxMaterialMode.MATERIAL_SLOTS:
            container.grid_remove()
            return

        fbx_path = str(row["fbx_var"].get()).strip()
        container.grid()
        if not fbx_path:
            placeholder.configure(text="Choose an FBX file to inspect material slots.")
            placeholder.grid(row=0, column=0, sticky="w")
            return
        try:
            slot_specs = self._inspect_fbx_material_slots_cached(fbx_path)
        except Exception as exc:
            placeholder.configure(text=f"FBX material slot analysis failed: {exc}")
            placeholder.grid(row=0, column=0, sticky="w")
            return
        if not slot_specs:
            placeholder.configure(text="No face-used FBX material slots were found in this file.")
            placeholder.grid(row=0, column=0, sticky="w")
            return

        persisted_overrides = self._material_slot_override_lookup(
            row.get("restored_slot_override_records", ())
        )
        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="FBX Material Slots").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(container, text="Unreal Material Path").grid(row=0, column=1, sticky="w", pady=(0, 4))
        for slot_index, slot_spec in enumerate(slot_specs, start=1):
            path_var = tk.StringVar(value=persisted_overrides.get(slot_spec.name, ""))
            path_var.trace_add("write", self._handle_persisted_field_change)
            ttk.Label(
                container,
                text=f"{slot_spec.name} ({slot_spec.face_count} faces)",
            ).grid(row=slot_index, column=0, sticky="w", padx=(0, 12), pady=(0, 4))
            entry = ttk.Entry(container, textvariable=path_var)
            entry.grid(row=slot_index, column=1, sticky="ew", pady=(0, 4))
            row["material_slot_rows"].append(
                {
                    "slot_name": slot_spec.name,
                    "face_count": slot_spec.face_count,
                    "path_var": path_var,
                    "entry": entry,
                }
            )
        row["restored_slot_override_records"] = ()

    def _inspect_fbx_material_slots_cached(self, fbx_path: str) -> tuple[FbxMaterialSlotSpec, ...]:
        resolved = str(Path(fbx_path).expanduser().resolve())
        cached = self._fbx_material_slot_cache.get(resolved)
        if cached is not None:
            return cached
        slots = inspect_fbx_material_slots(
            resolved,
            cpu_profile=self._current_cpu_profile(),
        )
        self._fbx_material_slot_cache[resolved] = slots
        return slots

    def _material_slot_override_lookup(self, records) -> dict[str, str]:
        lookup: dict[str, str] = {}
        for record in records or ():
            if not isinstance(record, dict):
                continue
            slot_name = str(record.get("slot_name", "")).strip()
            ue_asset_path = str(record.get("ue_asset_path", "")).strip()
            if slot_name and ue_asset_path:
                lookup[slot_name] = ue_asset_path
        return lookup

    def _collect_part_row_material_slot_overrides(
        self,
        row: dict[str, object],
    ) -> tuple[FbxMaterialSlotOverride, ...]:
        overrides: list[FbxMaterialSlotOverride] = []
        for slot_row in row.get("material_slot_rows", ()):
            slot_name = str(slot_row["slot_name"]).strip()
            ue_asset_path = str(slot_row["path_var"].get()).strip() or None
            if not slot_name:
                continue
            overrides.append(FbxMaterialSlotOverride(slot_name=slot_name, ue_asset_path=ue_asset_path))
        return tuple(overrides)

    def _create_collapsible_section(self, parent: ttk.Frame, row: int, title: str, key: str) -> ttk.Frame:
        container = ttk.Frame(parent)
        container.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        container.columnconfigure(0, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        button_text = tk.StringVar(value=f"[-] {title}")
        button = ttk.Button(header, textvariable=button_text, command=lambda: self._toggle_section(key))
        button.grid(row=0, column=0, sticky="w")

        content = ttk.Frame(container, padding=(12, 8, 0, 0))
        content.grid(row=1, column=0, sticky="ew")

        self._sections[key] = {
            "container": container,
            "content": content,
            "button_text": button_text,
            "title": title,
            "expanded": tk.BooleanVar(value=True),
        }
        return content

    def _toggle_section(self, key: str) -> None:
        section = self._sections[key]
        content = section["content"]
        expanded_var = section["expanded"]
        button_text = section["button_text"]
        title = section["title"]
        expanded = not bool(expanded_var.get())
        expanded_var.set(expanded)
        if expanded:
            content.grid()
            button_text.set(f"[-] {title}")
        else:
            content.grid_remove()
            button_text.set(f"[+] {title}")
        self._refresh_scroll_region()

    def _handle_canvas_resize(self, event) -> None:
        self.scroll_canvas.itemconfigure(self.content_window, width=event.width)
        self._refresh_scroll_region()

    def _handle_content_resize(self, _event=None) -> None:
        self._refresh_scroll_region()

    def _refresh_scroll_region(self) -> None:
        self.scroll_canvas.configure(scrollregion=self.scroll_canvas.bbox("all"))

    def _handle_mousewheel(self, event) -> None:
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
            if event.delta == 0:
                return
        self.scroll_canvas.yview_scroll(delta, "units")

    def _install_persistence_hooks(self) -> None:
        self.input_var.trace_add("write", self._handle_source_path_change)
        self.cpu_profile_var.trace_add("write", self._handle_persisted_field_change)
        self.preserve_temp_files_var.trace_add("write", self._handle_persisted_field_change)
        self.material_policy_var.trace_add("write", self._handle_material_policy_change)
        self.bark_material_var.trace_add("write", self._handle_persisted_field_change)
        self.leaves_material_var.trace_add("write", self._handle_persisted_field_change)
        self.single_material_var.trace_add("write", self._handle_persisted_field_change)
        self.gust_attenuation_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_ground_cover_change)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close)

    def _handle_persisted_field_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        self._save_settings()

    def _handle_material_policy_change(self, *_args) -> None:
        self._apply_material_policy_visibility()
        self._handle_persisted_field_change()

    def _handle_ground_cover_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        if self.input_var.get().strip() and self._wind_group_rows:
            self.refresh_wind_groups()

    def _current_material_policy(self) -> MaterialPolicy:
        try:
            return MaterialPolicy.parse(self.material_policy_var.get())
        except ValueError:
            return MaterialPolicy.SOURCE_MATERIAL_ROLES

    def _current_cpu_profile(self) -> CpuProfile:
        try:
            return CpuProfile(self.cpu_profile_var.get())
        except ValueError:
            return CpuProfile.BALANCED

    def _current_cleanup_policy(self) -> CleanupPolicy:
        return (
            CleanupPolicy.PRESERVE_FOR_DEBUGGING
            if bool(self.preserve_temp_files_var.get())
            else CleanupPolicy.EPHEMERAL
        )

    def _runtime_paths(self):
        return resolve_runtime_paths(
            settings_dir=self.SETTINGS_DIR,
            settings_path=self.SETTINGS_PATH,
            cache_root=self.RUNTIME_CACHE_ROOT,
        )

    def _apply_runtime_cleanup_summary(self) -> None:
        if not self._runtime_cleanup_summary.has_activity:
            return
        summary_message = f"Runtime cleanup: {self._runtime_cleanup_summary.to_message()}"
        if self._runtime_cleanup_summary.failed_paths:
            failed_paths = "\n".join(
                f"  - {failed_path}" for failed_path in self._runtime_cleanup_summary.failed_paths
            )
            summary_message = f"{summary_message}\n{failed_paths}"
        self._append_log(summary_message)

    def _apply_material_policy_visibility(self) -> None:
        return

    def _handle_window_close(self) -> None:
        if self._conversion_queue_job is not None:
            try:
                self.root.after_cancel(self._conversion_queue_job)
            except tk.TclError:
                pass
            self._conversion_queue_job = None
        if self._wind_queue_job is not None:
            try:
                self.root.after_cancel(self._wind_queue_job)
            except tk.TclError:
                pass
            self._wind_queue_job = None
        if self._conversion_process is not None and self._conversion_process.is_alive():
            if self._conversion_cancel_event is not None:
                self._conversion_cancel_event.set()
            self._conversion_process.join(timeout=0.2)
            if self._conversion_process.is_alive():
                self._conversion_process.terminate()
                self._conversion_process.join(timeout=0.2)
            self._close_conversion_process()
        if self._pending_settings_save_job is not None:
            try:
                self.root.after_cancel(self._pending_settings_save_job)
            except tk.TclError:
                pass
            self._pending_settings_save_job = None
        self._save_settings()
        self.root.destroy()

    def _handle_tk_callback_exception(self, exc_type, exc_value, exc_traceback) -> None:
        formatted = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback)).strip()
        self._report_error(
            "UI callback failed",
            str(exc_value),
            details=formatted,
            status="UI callback failed.",
        )

    def _close_conversion_process(self) -> None:
        if self._conversion_queue_job is not None:
            try:
                self.root.after_cancel(self._conversion_queue_job)
            except tk.TclError:
                pass
            self._conversion_queue_job = None
        if self._conversion_process is not None:
            try:
                if self._conversion_process.is_alive():
                    self._conversion_process.join(timeout=0.1)
            except Exception:
                pass
        close_process_queue(self._conversion_queue)
        self._conversion_process = None
        self._conversion_queue = None
        self._conversion_cancel_event = None
        self._conversion_context = None
        self._conversion_result_received = False
        self._conversion_error_traceback = None
        self._last_conversion_telemetry = None

    def _load_settings(self) -> None:
        settings = self._read_settings()
        self.cpu_profile_var.set(str(settings.get("cpu_profile", CpuProfile.BALANCED.value)))
        self.preserve_temp_files_var.set(bool(settings.get("preserve_temp_files", False)))
        self.material_policy_var.set(
            MaterialPolicy.parse(settings.get("material_policy", MaterialPolicy.SOURCE_MATERIAL_ROLES.value)).value
        )
        self.bark_material_var.set(str(settings.get("bark_material_path", "")))
        self.leaves_material_var.set(str(settings.get("leaves_material_path", "")))
        self.single_material_var.set(str(settings.get("single_material_path", "")))
        self.gust_attenuation_var.set(float(settings.get("gust_attenuation", 0.0)))
        self.is_ground_cover_var.set(bool(settings.get("is_ground_cover", False)))
        self._legacy_wind_group_settings = dict(settings.get("wind_group_settings", {}))
        self._persisted_wind_group_settings = dict(self._legacy_wind_group_settings)
        self._persisted_wind_group_settings_by_input_path = dict(
            settings.get("wind_group_settings_by_input_path", {})
        )
        self._persisted_base_material_settings_by_input_path = dict(
            settings.get("base_material_settings_by_input_path", {})
        )
        self._persisted_part_mesh_settings_by_input_path = dict(
            settings.get("part_mesh_settings_by_input_path", {})
        )

    def _read_settings(self) -> dict:
        if not self.SETTINGS_PATH.exists():
            return {}
        try:
            payload = json.loads(self.SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        wind_group_settings = payload.get("wind_group_settings", {})
        if not isinstance(wind_group_settings, dict):
            wind_group_settings = {}
        wind_group_settings_by_input_path = payload.get("wind_group_settings_by_input_path", {})
        if not isinstance(wind_group_settings_by_input_path, dict):
            wind_group_settings_by_input_path = {}
        part_mesh_settings = payload.get("part_mesh_settings_by_input_path", {})
        if not isinstance(part_mesh_settings, dict):
            part_mesh_settings = {}
        base_material_settings = payload.get("base_material_settings_by_input_path", {})
        if not isinstance(base_material_settings, dict):
            base_material_settings = {}
        return {
            "cpu_profile": payload.get("cpu_profile", CpuProfile.BALANCED.value),
            "preserve_temp_files": payload.get("preserve_temp_files", False),
            "material_policy": MaterialPolicy.parse(
                payload.get("material_policy", MaterialPolicy.SOURCE_MATERIAL_ROLES.value)
            ).value,
            "bark_material_path": payload.get("bark_material_path", ""),
            "leaves_material_path": payload.get("leaves_material_path", ""),
            "single_material_path": payload.get("single_material_path", ""),
            "gust_attenuation": payload.get("gust_attenuation", 0.0),
            "is_ground_cover": payload.get("is_ground_cover", False),
            "wind_group_settings": {
                str(key): value
                for key, value in wind_group_settings.items()
                if isinstance(value, dict)
            },
            "wind_group_settings_by_input_path": {
                str(key): {
                    str(group_key): group_value
                    for group_key, group_value in group_settings.items()
                    if isinstance(group_value, dict)
                }
                for key, group_settings in wind_group_settings_by_input_path.items()
                if isinstance(group_settings, dict)
            },
            "base_material_settings_by_input_path": {
                str(key): value
                for key, value in base_material_settings.items()
                if isinstance(value, list)
            },
            "part_mesh_settings_by_input_path": {
                str(key): value
                for key, value in part_mesh_settings.items()
                if isinstance(value, list)
            },
        }

    def _save_settings(self) -> None:
        try:
            if self._pending_settings_save_job is not None:
                try:
                    self.root.after_cancel(self._pending_settings_save_job)
                except tk.TclError:
                    pass
                self._pending_settings_save_job = None
            self.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            base_material_settings_by_input_path = dict(self._persisted_base_material_settings_by_input_path)
            part_mesh_settings_by_input_path = dict(self._persisted_part_mesh_settings_by_input_path)
            wind_group_settings_by_input_path = dict(self._persisted_wind_group_settings_by_input_path)
            current_base_material_settings = self._serialize_base_material_settings()
            current_part_mesh_settings = self._serialize_part_mesh_settings()
            current_wind_group_settings = self._serialize_wind_group_settings()
            if self._current_base_material_settings_key is not None:
                if current_base_material_settings:
                    base_material_settings_by_input_path[self._current_base_material_settings_key] = current_base_material_settings
                else:
                    base_material_settings_by_input_path.pop(self._current_base_material_settings_key, None)
            if self._current_part_mesh_settings_key is not None:
                if current_part_mesh_settings:
                    part_mesh_settings_by_input_path[self._current_part_mesh_settings_key] = current_part_mesh_settings
                else:
                    part_mesh_settings_by_input_path.pop(self._current_part_mesh_settings_key, None)
            if self._current_wind_settings_key is not None:
                if current_wind_group_settings:
                    wind_group_settings_by_input_path[self._current_wind_settings_key] = current_wind_group_settings
                else:
                    wind_group_settings_by_input_path.pop(self._current_wind_settings_key, None)
            payload = {
                "material_policy": self._current_material_policy().value,
                "bark_material_path": self.bark_material_var.get().strip(),
                "leaves_material_path": self.leaves_material_var.get().strip(),
                "single_material_path": self.single_material_var.get().strip(),
                "gust_attenuation": round(float(self.gust_attenuation_var.get()), 4),
                "is_ground_cover": bool(self.is_ground_cover_var.get()),
                "wind_group_settings": current_wind_group_settings,
            }
            if self._current_cpu_profile() != CpuProfile.BALANCED:
                payload["cpu_profile"] = self._current_cpu_profile().value
            if bool(self.preserve_temp_files_var.get()):
                payload["preserve_temp_files"] = True
            if part_mesh_settings_by_input_path:
                payload["part_mesh_settings_by_input_path"] = part_mesh_settings_by_input_path
            if base_material_settings_by_input_path:
                payload["base_material_settings_by_input_path"] = base_material_settings_by_input_path
            if wind_group_settings_by_input_path:
                payload["wind_group_settings_by_input_path"] = wind_group_settings_by_input_path
            self.SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._persisted_base_material_settings_by_input_path = base_material_settings_by_input_path
            self._persisted_part_mesh_settings_by_input_path = part_mesh_settings_by_input_path
            self._persisted_wind_group_settings_by_input_path = wind_group_settings_by_input_path
        except OSError:
            return

    def _serialize_base_material_settings(self) -> list[dict[str, object]]:
        if not self._base_material_rows:
            return []
        serialized: list[dict[str, object]] = []
        for row in self._base_material_rows:
            ue_asset_path = str(row["material_path_var"].get()).strip()
            if not ue_asset_path:
                continue
            serialized.append(
                {
                    "source_id": int(row["source_id"]),
                    "source_name": str(row["source_name"]),
                    "ue_asset_path": ue_asset_path,
                }
            )
        return serialized

    def _serialize_part_mesh_settings(self) -> list[dict[str, object]]:
        if not self._part_mesh_rows:
            return []

        serialized: list[dict[str, object]] = []
        for row in self._part_mesh_rows:
            source_mode = PrototypeSourceMode(str(row["source_mode_var"].get()))
            use_unreal_reference = bool(row["use_unreal_var"].get())
            asset_path = str(row["asset_var"].get()).strip()
            fbx_path = str(row["fbx_var"].get()).strip()
            fbx_material_mode = FbxMaterialMode(str(row["fbx_material_mode_var"].get()))
            single_material_path = str(row["single_material_var"].get()).strip()
            black_material_path = str(row["black_material_var"].get()).strip()
            white_material_path = str(row["white_material_var"].get()).strip()
            material_slot_overrides = self._collect_part_row_material_slot_overrides(row)
            if (
                source_mode == PrototypeSourceMode.XML_MESH
                and not use_unreal_reference
                and not asset_path
                and not fbx_path
                and fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
                and not single_material_path
                and not black_material_path
                and not white_material_path
                and not material_slot_overrides
            ):
                continue
            record = {
                "source_name": str(row["source_name"]),
                "source_key": str(row["source_key"]),
            }
            if source_mode == PrototypeSourceMode.UNREAL_ASSET:
                record["use_unreal_reference"] = True
                record["unreal_asset_path"] = asset_path
            elif source_mode == PrototypeSourceMode.FBX_FILE:
                record["source_mode"] = PrototypeSourceMode.FBX_FILE.value
                record["fbx_path"] = fbx_path
                record["fbx_material_mode"] = fbx_material_mode.value
            else:
                record["source_mode"] = PrototypeSourceMode.XML_MESH.value
                record["fbx_material_mode"] = fbx_material_mode.value
            if single_material_path:
                record["single_material_path"] = single_material_path
            if black_material_path:
                record["black_material_path"] = black_material_path
            if white_material_path:
                record["white_material_path"] = white_material_path
            if material_slot_overrides:
                record["fbx_material_slot_overrides"] = [
                    {
                        "slot_name": override.slot_name,
                        "ue_asset_path": override.ue_asset_path or "",
                    }
                    for override in material_slot_overrides
                ]
            serialized.append(record)
        return serialized

    def _serialize_wind_group_settings(self) -> dict[str, dict[str, object]]:
        if not self._wind_group_rows:
            return dict(self._persisted_wind_group_settings)
        serialized: dict[str, dict[str, object]] = {}
        for row in self._wind_group_rows:
            group_index = int(row["group_index"])
            dual_influence_var = row["dual_influence_var"]
            influence_var = row["influence_var"]
            min_influence_var = row["min_influence_var"]
            max_influence_var = row["max_influence_var"]
            shift_var = row["shift_var"]
            serialized[str(group_index)] = {
                "use_dual_influence": bool(dual_influence_var.get()),
                "influence": round(float(influence_var.get()), 4),
                "min_influence": round(float(min_influence_var.get()), 4),
                "max_influence": round(float(max_influence_var.get()), 4),
                "shift_top": round(float(shift_var.get()), 4),
            }
        self._persisted_wind_group_settings = serialized
        return serialized

    def _derive_wind_json_output_path(self) -> Path:
        output_path = self.output_var.get().strip()
        if output_path:
            resolved_output = Path(output_path)
            return resolved_output.with_name(f"{resolved_output.stem}_DynamicWind.json")
        return Path(self.input_var.get().strip()).with_name(f"{Path(self.input_var.get().strip()).stem}_DynamicWind.json")

    def _rebuild_wind_group_controls(self, groups: tuple[DynamicWindSimulationGroup, ...]) -> None:
        for child in self.wind_groups_container.winfo_children():
            child.destroy()
        self._wind_group_rows.clear()

        if not groups:
            ttk.Label(self.wind_groups_container, text="No skeleton joints found.").grid(row=0, column=0, sticky="w")
            return

        for row_index, group in enumerate(groups):
            group_frame = ttk.Frame(self.wind_groups_container, padding=(0, 6, 0, 10))
            group_frame.grid(row=row_index, column=0, sticky="ew")
            group_frame.columnconfigure(0, weight=1)
            group_frame.columnconfigure(1, weight=1)

            header = ttk.Frame(group_frame)
            header.grid(row=0, column=0, columnspan=2, sticky="ew")
            header.columnconfigure(0, weight=1)

            title = f"Group {group.group_index} ({'Trunk' if group.is_trunk_group else f'Generator level {group.branch_order}'})"
            ttk.Label(header, text=title).grid(row=0, column=0, sticky="w")

            persisted_dual_influence = self._persisted_group_bool(
                group.group_index, "use_dual_influence", group.use_dual_influence
            )
            dual_influence_var = tk.BooleanVar(value=persisted_dual_influence)
            dual_check = ttk.Checkbutton(header, text="Dual Influence", variable=dual_influence_var)
            dual_check.grid(row=0, column=1, sticky="e")

            single_frame = ttk.Frame(group_frame)
            single_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            single_frame.columnconfigure(1, weight=1)
            influence_default = self._persisted_group_value(group.group_index, "influence", group.influence)
            influence_var = tk.DoubleVar(value=influence_default)
            influence_value_var = tk.StringVar(value=f"{influence_var.get():.2f}")
            influence_scale = tk.Scale(
                single_frame,
                from_=0.0,
                to=self.MAX_WIND_INFLUENCE,
                resolution=0.05,
                orient="horizontal",
                variable=influence_var,
                command=lambda value, value_var=influence_value_var: self._handle_scale_change(value, value_var),
            )
            ttk.Label(single_frame, text="Influence").grid(row=0, column=0, sticky="w")
            influence_scale.grid(row=0, column=1, sticky="ew", padx=(12, 12))
            ttk.Label(single_frame, textvariable=influence_value_var, width=6).grid(row=0, column=2, sticky="e")

            dual_frame = ttk.Frame(group_frame)
            dual_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            dual_frame.columnconfigure(1, weight=1)
            min_influence_default = self._persisted_group_value(group.group_index, "min_influence", group.min_influence)
            max_influence_default = self._persisted_group_value(
                group.group_index, "max_influence", group.max_influence if group.max_influence else influence_default
            )
            min_influence_var = tk.DoubleVar(value=min_influence_default)
            min_influence_value_var = tk.StringVar(value=f"{min_influence_var.get():.2f}")
            min_influence_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.MAX_WIND_INFLUENCE,
                resolution=0.01,
                orient="horizontal",
                variable=min_influence_var,
                command=lambda value, value_var=min_influence_value_var: self._handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Min Influence").grid(row=0, column=0, sticky="w")
            min_influence_scale.grid(row=0, column=1, sticky="ew", padx=(12, 12))
            ttk.Label(dual_frame, textvariable=min_influence_value_var, width=6).grid(row=0, column=2, sticky="e")

            max_influence_var = tk.DoubleVar(value=max_influence_default)
            max_influence_value_var = tk.StringVar(value=f"{max_influence_var.get():.2f}")
            max_influence_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.MAX_WIND_INFLUENCE,
                resolution=0.01,
                orient="horizontal",
                variable=max_influence_var,
                command=lambda value, value_var=max_influence_value_var: self._handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Max Influence").grid(row=1, column=0, sticky="w")
            max_influence_scale.grid(row=1, column=1, sticky="ew", padx=(12, 12), pady=(6, 0))
            ttk.Label(dual_frame, textvariable=max_influence_value_var, width=6).grid(
                row=1, column=2, sticky="e", pady=(6, 0)
            )

            shift_var = tk.DoubleVar(value=self._persisted_group_value(group.group_index, "shift_top", group.shift_top))
            shift_value_var = tk.StringVar(value=f"{shift_var.get():.2f}")
            shift_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.MAX_SHIFT_TOP,
                resolution=0.01,
                orient="horizontal",
                variable=shift_var,
                command=lambda value, value_var=shift_value_var: self._handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Shift Top").grid(row=2, column=0, sticky="w")
            shift_scale.grid(row=2, column=1, sticky="ew", padx=(12, 12), pady=(6, 0))
            ttk.Label(dual_frame, textvariable=shift_value_var, width=6).grid(
                row=2, column=2, sticky="e", pady=(6, 0)
            )

            row_data = {
                "group_index": group.group_index,
                "branch_order": group.branch_order,
                "is_trunk_group": group.is_trunk_group,
                "influence_var": influence_var,
                "shift_var": shift_var,
                "dual_influence_var": dual_influence_var,
                "min_influence_var": min_influence_var,
                "max_influence_var": max_influence_var,
                "single_frame": single_frame,
                "dual_frame": dual_frame,
            }
            self._wind_group_rows.append(row_data)
            dual_influence_var.trace_add("write", lambda *_args, row=row_data: self._handle_wind_group_mode_change(row))
            self._apply_wind_group_mode(row_data)

        self._save_settings()

    def _persisted_group_value(self, group_index: int, field_name: str, default: float) -> float:
        persisted = self._persisted_wind_group_settings.get(str(group_index), {})
        value = persisted.get(field_name, default)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return default
        maximum = self.MAX_SHIFT_TOP if field_name == "shift_top" else self.MAX_WIND_INFLUENCE
        return max(0.0, min(numeric_value, maximum))

    def _persisted_group_bool(self, group_index: int, field_name: str, default: bool) -> bool:
        persisted = self._persisted_wind_group_settings.get(str(group_index), {})
        value = persisted.get(field_name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return bool(value)

    def _handle_wind_group_mode_change(self, row: dict[str, object]) -> None:
        self._apply_wind_group_mode(row)
        self._schedule_settings_save()

    def _apply_wind_group_mode(self, row: dict[str, object]) -> None:
        dual_influence = bool(row["dual_influence_var"].get())
        self._set_frame_visible(row["single_frame"], not dual_influence)
        self._set_frame_visible(row["dual_frame"], dual_influence)

    def _set_frame_visible(self, frame: ttk.Frame, visible: bool) -> None:
        if visible:
            frame.grid()
        else:
            frame.grid_remove()

    def _collect_wind_group_settings(self) -> tuple[DynamicWindSimulationGroup, ...]:
        return tuple(
            DynamicWindSimulationGroup(
                group_index=int(row["group_index"]),
                branch_order=int(row["branch_order"]),
                influence=float(row["influence_var"].get()),
                shift_top=float(row["shift_var"].get()),
                is_trunk_group=bool(row["is_trunk_group"]),
                use_dual_influence=bool(row["dual_influence_var"].get()),
                min_influence=float(row["min_influence_var"].get()),
                max_influence=float(row["max_influence_var"].get()),
            )
            for row in self._wind_group_rows
        )

    def _handle_gust_change(self, value: float) -> None:
        self.gust_value_var.set(f"{value:.2f}")
        self._schedule_settings_save()

    def _handle_scale_change(self, value: str, value_var: tk.StringVar) -> None:
        value_var.set(f"{float(value):.2f}")
        self._schedule_settings_save()

    def _schedule_settings_save(self) -> None:
        if self._suspend_settings_save:
            return
        if self._pending_settings_save_job is not None:
            try:
                self.root.after_cancel(self._pending_settings_save_job)
            except tk.TclError:
                pass
        self._pending_settings_save_job = self.root.after(150, self._flush_scheduled_settings_save)

    def _flush_scheduled_settings_save(self) -> None:
        self._pending_settings_save_job = None
        self._save_settings()


def format_conversion_results(
    results,
    cpu_profile: CpuProfile = CpuProfile.BALANCED,
    cleanup_policy: CleanupPolicy = CleanupPolicy.EPHEMERAL,
    material_policy: MaterialPolicy = MaterialPolicy.SOURCE_MATERIAL_ROLES,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    base_material_overrides: tuple[BaseMaterialOverride, ...] = (),
    use_explicit_material_contract: bool = False,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
) -> str:
    lines: list[str] = [
        f"CPU profile: {cpu_profile.value}",
        f"Cleanup policy: {cleanup_policy.value}",
    ]
    if use_explicit_material_contract:
        lines.append("Material contract: explicit_base_and_part_materials")
        if base_material_overrides:
            lines.append("Base XML material overrides:")
            for override in base_material_overrides:
                lines.append(
                    f"  - {override.source_name or f'Material_{override.source_id}'} "
                    f"(ID {override.source_id}): {override.ue_asset_path or '<none>'}"
                )
            lines.append("")
    else:
        lines.append(f"Material policy: {material_policy.value}")
    if not use_explicit_material_contract and material_policy == MaterialPolicy.SINGLE_MATERIAL and single_material_path:
        lines.append(f"Single material path: {single_material_path}")
        lines.append("")
    elif not use_explicit_material_contract and (bark_material_path or leaves_material_path):
        lines.append("Material overrides:")
        lines.append(f"  - bark: {bark_material_path or '<none>'}")
        lines.append(f"  - leaves: {leaves_material_path or '<none>'}")
        lines.append("")
    if use_existing_part_meshes:
        lines.append("Existing PartMesh overrides:")
        if part_mesh_asset_paths:
            for source_key, asset_path in part_mesh_asset_paths:
                lines.append(f"  - {source_key}: {asset_path}")
        else:
            lines.append("  - enabled with no explicit mappings")
        lines.append("")
    if prototype_source_configs:
        lines.append("Prototype source overrides:")
        for config in prototype_source_configs:
            source_label = config.source_name or config.source_key
            if config.mode == PrototypeSourceMode.UNREAL_ASSET:
                lines.append(f"  - {source_label}: unreal_asset -> {config.asset_path or '<missing>'}")
            elif config.mode == PrototypeSourceMode.FBX_FILE:
                lines.append(
                    f"  - {source_label}: fbx_file[{config.fbx_material_mode.value}] -> {config.fbx_path or '<missing>'}"
                )
            else:
                lines.append(f"  - {source_label}: xml_mesh[{config.fbx_material_mode.value}]")
            if use_explicit_material_contract and config.mode != PrototypeSourceMode.UNREAL_ASSET:
                lines.append(f"      single: {config.single_material_path or '<none>'}")
                lines.append(f"      black: {config.black_material_path or '<none>'}")
                lines.append(f"      white: {config.white_material_path or '<none>'}")
                if config.fbx_material_slot_overrides:
                    lines.append("      slots:")
                    for override in config.fbx_material_slot_overrides:
                        lines.append(
                            f"        - {override.slot_name}: {override.ue_asset_path or '<none>'}"
                        )
        lines.append("")
    for result in results:
        lines.append(f"Input: {result.input_path}")
        lines.append(f"Output: {result.output_path or '<not written>'}")
        if result.diagnostics:
            lines.append("Diagnostics:")
            for issue in result.diagnostics:
                lines.append(f"  - [{issue.severity}] {issue.code}: {issue.message}")
        else:
            lines.append("Diagnostics: none")
        stats = getattr(result.usda_document, "stats", None) if result.usda_document is not None else None
        streamed = bool(getattr(stats, "streamed", False)) if type(stats).__name__ == "ExportStats" else False
        if streamed:
            lines.append(
                "Streaming export: "
                f"{stats.bytes_written} bytes in "
                f"{stats.duration_seconds:.2f}s"
            )
        if result.runtime_job_dir:
            lines.append(f"Preserved job temp dir: {result.runtime_job_dir}")
        lines.append("Status: success" if result.usda_document is not None else "Status: failed")
        lines.append("")
    return "\n".join(lines).strip()


def format_wind_group_summary(dynamic_wind) -> str:
    lines = [
        f"Wind groups detected: {len(dynamic_wind.simulation_groups)}",
        f"Joints classified: {len(dynamic_wind.joint_assignments)}",
        "",
    ]
    for group in dynamic_wind.simulation_groups:
        joint_count = sum(
            1 for assignment in dynamic_wind.joint_assignments if assignment.simulation_group_index == group.group_index
        )
        label = "Trunk" if group.is_trunk_group else f"Generator level {group.branch_order}"
        mode = "Dual" if group.use_dual_influence else "Single"
        lines.append(
            f"Group {group.group_index}: {label}, branch_order={group.branch_order}, joints={joint_count}, mode={mode}"
        )
    return "\n".join(lines)


def format_wind_json_result(result) -> str:
    lines = [
        f"Input: {result.input_path}",
        f"Output: {result.output_path}",
        f"Wind groups: {len(result.dynamic_wind.simulation_groups)}",
        f"Joints: {len(result.dynamic_wind.joint_assignments)}",
        f"Gust Attenuation: {result.dynamic_wind.gust_attenuation:.2f}",
        f"Ground Cover: {result.dynamic_wind.is_ground_cover}",
        "",
    ]
    for group in result.dynamic_wind.simulation_groups:
        mode = "dual" if group.use_dual_influence else "single"
        influence_info = (
            f"min={group.min_influence:.2f}, max={group.max_influence:.2f}"
            if group.use_dual_influence
            else f"influence={group.influence:.2f}"
        )
        shift_top = group.shift_top if group.use_dual_influence else 0.0
        lines.append(
            f"Group {group.group_index}: mode={mode}, level={group.branch_order}, {influence_info}, shiftTop={shift_top:.2f}, trunk={group.is_trunk_group}"
        )
    return "\n".join(lines)


def _is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def _format_telemetry_status(telemetry: ConversionTelemetry) -> str:
    detail = telemetry.message or telemetry.phase.value.replace("_", " ").title()
    progress = ""
    if telemetry.total_units > 0:
        progress = f" ({telemetry.completed_units}/{telemetry.total_units})"
    if telemetry.output_bytes_written > 0:
        progress += f" [{telemetry.output_bytes_written} bytes]"
    if telemetry.elapsed_seconds > 0:
        progress += f" {telemetry.elapsed_seconds:.1f}s"
    return f"{detail}{progress}"


def main() -> int:
    import multiprocessing

    multiprocessing.freeze_support()
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0
