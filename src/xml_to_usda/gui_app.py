"""Tk app shell and UI wiring over modular GUI controllers.

Layer: UI.

This module owns the real `ConversionApp` implementation, top-level widget
layout, and wiring between UI controllers, persistence, and background job
bridges. Public launch compatibility stays in `gui.py`.
"""

from __future__ import annotations

import gc
import json
import multiprocessing
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from queue import Queue
import tkinter as tk
import traceback
from tkinter import ttk

from .gui_background_jobs import GuiBackgroundJobsBridge
from .gui_formatters import format_conversion_results, format_wind_group_summary, format_wind_json_result
from .gui_materials_panel import MaterialsPanelController
from .gui_models import SectionUiState
from .gui_part_sources_panel import PartSourcesPanelController
from .gui_persistence import GuiPersistenceController
from .gui_wind_panel import WindPanelController
from .models import CleanupPolicy, ConversionMode, ConversionRequest, CpuProfile, MaterialPolicy
from .runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces


@dataclass(frozen=True)
class GuiDependencies:
    """Injected runtime dependencies so the public GUI facade can stay stable."""
    prepare_conversion_plan: object
    start_conversion_process: object
    close_process_queue: object
    drain_process_queue: object
    convert_request: object
    inspect_fbx_material_slot_rows: object
    load_gui_settings: object
    save_gui_settings: object
    resolve_input_settings_key: object
    prepare_wind_inspection_plan: object
    inspect_wind_groups: object
    WindGenerationRequest: object
    generate_wind_json_from_request: object
    derive_wind_json_output_path: object
    format_wind_error: object
    should_retry_wind_error: object
    messagebox: object
    filedialog: object
    sys: object


class ConversionApp:
    SETTINGS_DIR = Path.home() / ".xml_to_usda"
    SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"
    RUNTIME_LOG_PATH = SETTINGS_DIR / "gui_runtime.log"
    RUNTIME_CACHE_ROOT = resolve_runtime_paths().cache_root
    MAX_WIND_INFLUENCE = 1.0
    MAX_SHIFT_TOP = 1.0
    ASYNC_WIND_REFRESH_THRESHOLD_BYTES = 5 * 1024 * 1024
    ASYNC_CONVERSION_THRESHOLD_BYTES = 5 * 1024 * 1024

    def __init__(self, root: tk.Tk, *, dependencies: GuiDependencies) -> None:
        self.root = root
        self._deps = dependencies
        self.root.title("Convert XML -> USDA")
        self.root.minsize(900, 620)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.cpu_profile_var = tk.StringVar(value=CpuProfile.BALANCED.value)
        self.preserve_temp_files_var = tk.BooleanVar(value=False)
        self._persisted_conversion_mode = ConversionMode.SKELETAL_ASSEMBLY
        # Retained compatibility state: older tests and UI assumptions still
        # introspect this variable even though per-row source configs now drive
        # the actual repeated-part conversion semantics.
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

        self._sections: dict[str, SectionUiState] = {}
        self._base_material_rows = []
        self._part_mesh_rows = []
        self._wind_group_rows = []
        self._persisted_wind_group_settings = {}
        self._legacy_wind_group_settings = {}
        self._persisted_base_material_settings = ()
        self._persisted_part_mesh_settings = ()
        self._current_wind_settings_key: str | None = None
        self._current_base_material_settings_key: str | None = None
        self._current_part_mesh_settings_key: str | None = None
        self._pending_settings_save_job: str | None = None
        self._suspend_settings_save = False
        self._startup_restored_input_path = ""
        self._current_source_path = ""
        self._auto_output_path: str | None = None
        self._remembered_output_path = ""
        self._conversion_process = None
        self._conversion_cancel_event = None
        self._conversion_queue = None
        self._conversion_queue_job: str | None = None
        self._conversion_context: ConversionRequest | None = None
        self._conversion_result_received = False
        self._conversion_error_traceback: str | None = None
        self._last_conversion_telemetry = None
        self._wind_thread = None
        self._wind_queue: Queue[tuple[str, object]] = Queue()
        self._wind_queue_job: str | None = None
        self._active_wind_request_id = 0

        self._persistence = GuiPersistenceController(
            self,
            load_gui_settings=self._deps.load_gui_settings,
            save_gui_settings=self._deps.save_gui_settings,
        )
        self._background_jobs = GuiBackgroundJobsBridge(self)

        self._load_settings()
        self._runtime_cleanup_summary = sweep_stale_job_workspaces(self._runtime_paths())

        self._build_layout()
        self._install_persistence_hooks()
        self.root.after_idle(self._restore_previous_session_state)
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
        ttk.Entry(self.content_frame, textvariable=self.input_var).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Button(self.content_frame, text="Browse...", command=self.browse_input).grid(row=row, column=2, sticky="ew", pady=(0, 8))

        row += 1
        ttk.Label(self.content_frame, text="Output USDA").grid(row=row, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.content_frame, textvariable=self.output_var).grid(row=row, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Button(self.content_frame, text="Save As...", command=self.browse_output).grid(row=row, column=2, sticky="ew", pady=(0, 8))

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

        row += 1
        part_mesh_content = self._create_collapsible_section(self.content_frame, row, "Part Mesh Reuse", "part_mesh")
        self.part_mesh_frame = part_mesh_content
        part_mesh_content.columnconfigure(0, weight=1)
        ttk.Label(
            part_mesh_content,
            text=(
                "Rows are discovered from the XML leaf-reference mesh library. Choose XML mesh, existing Unreal asset, "
                "or a disk FBX file for each repeated prototype."
            ),
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.part_mesh_summary_var = tk.StringVar(value="Repeated branch analysis has not run yet.")
        ttk.Label(part_mesh_content, textvariable=self.part_mesh_summary_var).grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.part_mesh_rows_container = ttk.Frame(part_mesh_content)
        self.part_mesh_rows_container.grid(row=2, column=0, sticky="ew")
        self.part_mesh_rows_container.columnconfigure(0, weight=1)

        row += 1
        wind_content = self._create_collapsible_section(self.content_frame, row, "Wind Profile", "wind")
        self.wind_frame = wind_content
        wind_content.columnconfigure(1, weight=1)
        wind_content.columnconfigure(3, weight=1)

        self.refresh_wind_button = ttk.Button(wind_content, text="Refresh Wind Groups", command=self.refresh_wind_groups)
        self.refresh_wind_button.grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Checkbutton(wind_content, text="Ground Cover", variable=self.is_ground_cover_var).grid(
            row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 8)
        )
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
        ttk.Label(wind_content, textvariable=self.gust_value_var, width=6).grid(row=1, column=3, sticky="e", pady=(0, 8))
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

        self._materials_panel = MaterialsPanelController(
            summary_var=self.base_material_summary_var,
            rows_container=self.base_material_rows_container,
            refresh_scroll_region=self._refresh_scroll_region,
            on_persisted_field_change=self._handle_persisted_field_change,
        )
        self._part_sources_panel = PartSourcesPanelController(
            summary_var=self.part_mesh_summary_var,
            rows_container=self.part_mesh_rows_container,
            refresh_scroll_region=self._refresh_scroll_region,
            on_persisted_field_change=self._handle_persisted_field_change,
            cpu_profile_getter=self._current_cpu_profile,
            inspect_fbx_material_slot_rows_fn=self._deps.inspect_fbx_material_slot_rows,
        )
        self._wind_panel = WindPanelController(
            container=self.wind_groups_container,
            max_wind_influence=self.MAX_WIND_INFLUENCE,
            max_shift_top=self.MAX_SHIFT_TOP,
            schedule_settings_save=self._schedule_settings_save,
        )
        self._base_material_rows = self._materials_panel.rows
        self._part_mesh_rows = self._part_sources_panel.rows
        self._wind_group_rows = self._wind_panel.rows
        self._clear_base_material_rows()
        self._clear_part_mesh_rows()
        self._clear_wind_group_controls()
        self._refresh_scroll_region()

    def browse_input(self) -> None:
        initial_input = self.input_var.get().strip()
        if not initial_input and self._startup_restored_input_path:
            initial_input = str(Path(self._startup_restored_input_path).parent)
        elif initial_input:
            initial_path = Path(initial_input)
            if initial_path.suffix:
                initial_input = str(initial_path.parent)
        selected = self._deps.filedialog.askopenfilename(
            title="Select SpeedTree XML",
            initialdir=initial_input,
            filetypes=[("XML files", "*.xml"), ("All files", "*.*")],
        )
        if not selected:
            return
        current_input = self.input_var.get().strip()
        previous_auto_output = self._auto_output_path
        self.status_var.set("Source XML selected. Running XML analysis...")
        self.input_var.set(selected)
        self._set_default_output_from_source(current_input, previous_auto_output)
        if current_input == selected:
            self._handle_source_path_change()
        self._save_settings()

    def browse_output(self) -> None:
        current_output = self.output_var.get().strip()
        if current_output and current_output != self._auto_output_path:
            initial = Path(current_output)
        elif self._remembered_output_path:
            initial = Path(self._remembered_output_path)
        elif current_output:
            initial = Path(current_output)
        else:
            initial = Path("tree.usda")
        selected = self._deps.filedialog.asksaveasfilename(
            title="Select USDA output",
            defaultextension=".usda",
            initialdir=str(initial.parent) if str(initial.parent) != "." else "",
            initialfile=initial.name,
            filetypes=[("USDA files", "*.usda"), ("All files", "*.*")],
        )
        if selected:
            self.output_var.set(selected)
            self._save_settings()

    def _set_default_output_from_source(self, previous_input: str, previous_auto_output: str | None) -> None:
        source_path = self.input_var.get().strip()
        if not source_path:
            self._auto_output_path = None
            return
        new_auto_output = str(Path(source_path).with_suffix(".usda"))
        current_output = self.output_var.get().strip()
        previous_default = previous_auto_output or (str(Path(previous_input).with_suffix(".usda")) if previous_input else "")
        if not current_output or current_output == previous_default:
            next_output = new_auto_output
        else:
            current_path = Path(current_output)
            next_output = str(current_path.with_name(f"{Path(source_path).stem}{current_path.suffix or '.usda'}"))
        if next_output != current_output:
            self._suspend_settings_save = True
            try:
                self.output_var.set(next_output)
            finally:
                self._suspend_settings_save = False
        self._auto_output_path = new_auto_output

    def refresh_wind_groups(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file before loading wind groups.")
            return
        plan = self._deps.prepare_wind_inspection_plan(
            input_path=input_path,
            is_ground_cover=bool(self.is_ground_cover_var.get()),
            async_threshold_bytes=self.ASYNC_WIND_REFRESH_THRESHOLD_BYTES,
        )
        if plan.run_async:
            self._start_wind_group_refresh_async(plan.request)
            return
        try:
            dynamic_wind = self._deps.inspect_wind_groups(plan.request)
        except Exception as exc:
            self._report_error("Wind group inspection failed", str(exc), status="Wind group inspection failed.")
            return
        self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
        self.status_var.set(f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels.")
        self._set_log(format_wind_group_summary(dynamic_wind))
        gc.collect()

    def run_conversion(self) -> None:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        try:
            base_material_overrides = self._collect_base_material_overrides()
            prototype_source_configs = self._collect_part_source_configs()
            use_existing_part_meshes, part_mesh_asset_paths = self._collect_part_mesh_overrides()
        except ValueError as exc:
            self._report_error("Invalid PartMesh mapping", str(exc))
            return
        try:
            plan = self._deps.prepare_conversion_plan(
                input_path=input_path,
                output_path=output_path,
                cpu_profile=self._current_cpu_profile(),
                cleanup_policy=self._current_cleanup_policy(),
                material_policy=self._current_material_policy(),
                bark_material_path=self.bark_material_var.get().strip() or None,
                leaves_material_path=self.leaves_material_var.get().strip() or None,
                single_material_path=self.single_material_var.get().strip() or None,
                base_material_overrides=base_material_overrides,
                prototype_source_configs=prototype_source_configs,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
                async_threshold_bytes=self.ASYNC_CONVERSION_THRESHOLD_BYTES,
            )
        except ValueError as exc:
            message = str(exc)
            if message == "Select a source XML file.":
                self._report_error("Missing input", message)
            elif message == "Select an output USDA path.":
                self._report_error("Missing output", message)
            else:
                self._report_error("Invalid material path", message)
            return

        if plan.run_async:
            self._start_conversion_async(plan.request)
            return
        try:
            result = self._deps.convert_request(plan.request, runtime_paths=self._runtime_paths())[0]
        except Exception as exc:
            self._report_error("Conversion failed", str(exc), status="Conversion failed.")
            gc.collect()
            return
        self._save_settings()
        self._set_log(format_conversion_results((result,), plan.request))
        if result.usda_document is None:
            self.status_var.set("Conversion finished with errors.")
            self._append_runtime_log_entry("error", "Conversion failed", "See diagnostics in the log area.")
            gc.collect()
            return
        self.status_var.set(f"Wrote USDA to {result.output_path}")
        self._deps.messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")
        gc.collect()

    def run_generate_wind_json(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            self._report_error("Missing input", "Select a source XML file.")
            return
        if not self._wind_group_rows:
            self.refresh_wind_groups()
            if not self._wind_group_rows:
                return
        output_path = str(self._deps.derive_wind_json_output_path(input_path, self.output_var.get().strip()))
        try:
            result = self._deps.generate_wind_json_from_request(
                self._deps.WindGenerationRequest(
                    input_path=input_path,
                    output_path=output_path,
                    group_settings=self._collect_wind_group_settings(),
                    gust_attenuation=float(self.gust_attenuation_var.get()),
                    is_ground_cover=bool(self.is_ground_cover_var.get()),
                )
            )
        except Exception as exc:
            self._report_error("Wind JSON generation failed", str(exc), status="Wind JSON generation failed.")
            return
        self._save_settings()
        self._set_log(format_wind_json_result(result))
        self.status_var.set(f"Wrote wind JSON to {result.output_path}")
        self._deps.messagebox.showinfo("Wind JSON complete", f"Wrote wind JSON to {result.output_path}")
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
        for raw_path in (self._deps.sys.argv[0] if self._deps.sys.argv else "", self._deps.sys.executable):
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
        meipass = getattr(self._deps.sys, "_MEIPASS", None)
        lines = [
            "Runtime info:",
            f"  frozen: {bool(getattr(self._deps.sys, 'frozen', False))}",
            f"  executable: {self._deps.sys.executable}",
            f"  argv0: {self._deps.sys.argv[0] if self._deps.sys.argv else ''}",
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

    def _collect_base_material_overrides(self):
        return self._materials_panel.collect_overrides()

    def _collect_part_mesh_overrides(self):
        return self._part_sources_panel.collect_existing_part_overrides()

    def _collect_part_source_configs(self):
        return self._part_sources_panel.collect_part_source_configs()

    def _handle_source_path_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        self._active_wind_request_id += 1
        input_path = self.input_var.get().strip()
        previous_input = self._current_source_path
        input_changed = input_path != previous_input
        if input_changed:
            self._set_default_output_from_source(previous_input, self._auto_output_path)
            self._current_source_path = input_path
        if not input_path:
            self._current_wind_settings_key = None
            self._clear_base_material_rows()
            self._clear_part_mesh_rows()
            self._clear_wind_group_controls()
            return
        path = Path(input_path)
        if not path.exists():
            return
        resolved_key = self._deps.resolve_input_settings_key(input_path)
        self._current_wind_settings_key = resolved_key
        self._persisted_wind_group_settings = self._resolve_persisted_wind_settings_for_key(resolved_key)
        self._wind_panel.set_persisted_settings(self._persisted_wind_group_settings)
        self._clear_wind_group_controls("Analyzing XML and loading wind groups...")
        try:
            self._refresh_base_material_rows(input_path)
            self._refresh_part_mesh_rows(input_path)
        except Exception as exc:
            self._report_error("XML analysis failed", str(exc), status="XML analysis failed.")
            return
        self.refresh_wind_groups()

    def _clear_base_material_rows(self) -> None:
        self._current_base_material_settings_key = None
        self._materials_panel.clear()

    def _refresh_base_material_rows(self, input_path: str) -> None:
        if self._suspend_settings_save:
            return
        self._suspend_settings_save = True
        try:
            self._current_base_material_settings_key = self._materials_panel.refresh(
                input_path,
                persisted_records=self._persisted_base_material_settings,
            )
        finally:
            self._suspend_settings_save = False

    def _rebuild_base_material_rows(self, discovery) -> None:
        self._materials_panel.rebuild(discovery)

    def _clear_part_mesh_rows(self) -> None:
        self._current_part_mesh_settings_key = None
        self._part_sources_panel.clear()

    def _clear_wind_group_controls(self, message: str = "Click Refresh Wind Groups to inspect wind settings.") -> None:
        if hasattr(self, "refresh_wind_button"):
            self.refresh_wind_button.configure(state="normal")
        self._wind_panel.clear(message)
        self._refresh_scroll_region()

    def _refresh_part_mesh_rows(self, input_path: str) -> None:
        if self._suspend_settings_save:
            return
        self._suspend_settings_save = True
        try:
            self._current_part_mesh_settings_key = self._part_sources_panel.refresh(
                input_path,
                persisted_records=self._persisted_part_mesh_settings,
            )
        finally:
            self._suspend_settings_save = False

    def _rebuild_part_mesh_rows(self, discovery) -> None:
        self._part_sources_panel.rebuild(discovery)

    def _browse_part_fbx(self, target_var: tk.StringVar) -> None:
        self._part_sources_panel.browse_part_fbx(target_var)

    def _handle_source_mode_trace(self, row, use_unreal_var: tk.BooleanVar) -> None:
        self._part_sources_panel.handle_source_mode_trace(row, use_unreal_var)

    def _handle_legacy_unreal_toggle(self, source_mode_var: tk.StringVar, use_unreal_var: tk.BooleanVar) -> None:
        self._part_sources_panel.handle_legacy_unreal_toggle(source_mode_var, use_unreal_var)

    def _handle_part_source_mode_change(self, row) -> None:
        self._part_sources_panel.handle_part_source_mode_change(row)

    def _refresh_part_row_material_slot_controls(self, row) -> None:
        self._part_sources_panel.refresh_part_row_material_slot_controls(row)

    def _collect_part_row_material_slot_overrides(self, row):
        return self._part_sources_panel.collect_part_row_material_slot_overrides(row)

    def _create_collapsible_section(self, parent: ttk.Frame, row: int, title: str, key: str) -> ttk.Frame:
        container = ttk.Frame(parent)
        container.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(0, 12))
        container.columnconfigure(0, weight=1)

        header = ttk.Frame(container)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        button_text = tk.StringVar(value=f"[-] {title}")
        ttk.Button(header, textvariable=button_text, command=lambda: self._toggle_section(key)).grid(
            row=0, column=0, sticky="w"
        )

        content = ttk.Frame(container, padding=(12, 8, 0, 0))
        content.grid(row=1, column=0, sticky="ew")

        self._sections[key] = SectionUiState(
            container=container,
            content=content,
            button_text=button_text,
            title=title,
            expanded=tk.BooleanVar(value=True),
        )
        return content

    def _toggle_section(self, key: str) -> None:
        section = self._sections[key]
        expanded = not bool(section.expanded.get())
        section.expanded.set(expanded)
        if expanded:
            section.content.grid()
            section.button_text.set(f"[-] {section.title}")
        else:
            section.content.grid_remove()
            section.button_text.set(f"[+] {section.title}")
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
        self.output_var.trace_add("write", self._handle_persisted_field_change)
        self.preserve_temp_files_var.trace_add("write", self._handle_persisted_field_change)
        self.material_policy_var.trace_add("write", self._handle_material_policy_change)
        self.bark_material_var.trace_add("write", self._handle_persisted_field_change)
        self.leaves_material_var.trace_add("write", self._handle_persisted_field_change)
        self.single_material_var.trace_add("write", self._handle_persisted_field_change)
        self.gust_attenuation_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_ground_cover_change)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close)

    def _restore_previous_session_state(self) -> None:
        input_path = self._startup_restored_input_path.strip()
        self._startup_restored_input_path = ""
        if not input_path:
            return
        if self.input_var.get().strip() != input_path:
            return
        if not Path(input_path).exists():
            self.status_var.set("Saved source XML path is unavailable.")
            self._append_log(f"Saved source XML path is unavailable: {input_path}")
            return
        self.status_var.set("Restoring previous session settings...")
        self._handle_source_path_change()

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
        return CpuProfile.BALANCED

    def _current_cleanup_policy(self) -> CleanupPolicy:
        return CleanupPolicy.PRESERVE_FOR_DEBUGGING if bool(self.preserve_temp_files_var.get()) else CleanupPolicy.EPHEMERAL

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
            failed_paths = "\n".join(f"  - {failed_path}" for failed_path in self._runtime_cleanup_summary.failed_paths)
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
        self._report_error("UI callback failed", str(exc_value), details=formatted, status="UI callback failed.")

    def _load_settings(self) -> None:
        self._persistence.load_settings()

    def _save_settings(self) -> None:
        self._persistence.save_settings()

    def _resolve_persisted_wind_settings_for_key(self, settings_key: str):
        return self._persistence.resolve_persisted_wind_settings_for_key(settings_key)

    def _serialize_base_material_settings(self):
        return self._materials_panel.serialize_settings()

    def _serialize_part_mesh_settings(self):
        return self._part_sources_panel.serialize_settings()

    def _serialize_wind_group_settings(self):
        return self._wind_panel.serialize_settings()

    def _rebuild_wind_group_controls(self, groups) -> None:
        self._wind_panel.rebuild(groups)
        self._save_settings()

    def _persisted_group_value(self, group_index: int, field_name: str, default: float) -> float:
        return self._wind_panel.persisted_group_value(group_index, field_name, default)

    def _persisted_group_bool(self, group_index: int, field_name: str, default: bool) -> bool:
        return self._wind_panel.persisted_group_bool(group_index, field_name, default)

    def _handle_wind_group_mode_change(self, row) -> None:
        self._wind_panel.handle_wind_group_mode_change(row)

    def _apply_wind_group_mode(self, row) -> None:
        self._wind_panel.apply_wind_group_mode(row)

    def _set_frame_visible(self, frame: ttk.Frame, visible: bool) -> None:
        self._wind_panel.set_frame_visible(frame, visible)

    def _collect_wind_group_settings(self):
        return self._wind_panel.collect_group_settings()

    def _handle_gust_change(self, value: float) -> None:
        self.gust_value_var.set(f"{value:.2f}")
        self._schedule_settings_save()

    def _handle_scale_change(self, value: str, value_var: tk.StringVar) -> None:
        value_var.set(f"{float(value):.2f}")
        self._schedule_settings_save()

    def _schedule_settings_save(self) -> None:
        self._persistence.schedule_settings_save()

    def _flush_scheduled_settings_save(self) -> None:
        self._persistence.flush_scheduled_settings_save()

    def _start_wind_group_refresh_async(self, request) -> None:
        self._background_jobs.start_wind_group_refresh_async(request)

    def _run_wind_group_worker(self, *, request_id: int, request) -> None:
        self._background_jobs.run_wind_group_worker(request_id=request_id, request=request)

    def _schedule_wind_queue_poll(self) -> None:
        self._background_jobs.schedule_wind_queue_poll()

    def _poll_wind_queue(self) -> None:
        self._background_jobs.poll_wind_queue()

    def _retry_wind_group_refresh_if_needed(self, *, request, error_payload: dict[str, str]):
        return self._background_jobs.retry_wind_group_refresh_if_needed(request=request, error_payload=error_payload)

    def _start_conversion_async(self, request: ConversionRequest) -> None:
        self._background_jobs.start_conversion_async(request)

    def _schedule_conversion_queue_poll(self) -> None:
        self._background_jobs.schedule_conversion_queue_poll()

    def _poll_conversion_queue(self) -> None:
        self._background_jobs.poll_conversion_queue()

    def _handle_conversion_telemetry(self, telemetry) -> None:
        self._background_jobs.handle_conversion_telemetry(telemetry)

    def _format_runtime_crash_context(self) -> str:
        return self._background_jobs.format_runtime_crash_context()

    def _handle_conversion_job_result(self, job_result, request: ConversionRequest | None) -> None:
        self._background_jobs.handle_conversion_job_result(job_result, request)

    def _set_conversion_running(self, active: bool) -> None:
        self.convert_button.configure(state="disabled" if active else "normal")
        self.cancel_button.configure(state="normal" if active else "disabled")

    def cancel_conversion(self) -> None:
        if self._conversion_process is None or not self._conversion_process.is_alive():
            return
        if self._conversion_cancel_event is not None:
            self._conversion_cancel_event.set()
        self.status_var.set("Cancelling conversion...")

    def _close_conversion_process(self) -> None:
        self._background_jobs.close_conversion_process()
