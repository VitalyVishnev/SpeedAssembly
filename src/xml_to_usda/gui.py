from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue
from tkinter import filedialog, messagebox, ttk

from .models import (
    CleanupPolicy,
    ConversionJobResult,
    ConversionPhase,
    ConversionTelemetry,
    CpuProfile,
    DynamicWindSimulationGroup,
    FbxMaterialMode,
    MaterialPolicy,
    PrototypeSourceConfig,
    PrototypeSourceMode,
)
from .pipeline import convert_file, generate_wind_json, inspect_wind_data, load_canonical_model
from .runtime_paths import resolve_runtime_paths, sweep_stale_job_workspaces


class ConversionApp:
    SETTINGS_DIR = Path.home() / ".xml_to_usda"
    SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"
    RUNTIME_CACHE_ROOT = resolve_runtime_paths().cache_root
    MAX_WIND_INFLUENCE = 1.0
    MAX_SHIFT_TOP = 1.0

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convert XML -> USDA")
        self.root.minsize(900, 620)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.cpu_profile_var = tk.StringVar(value=CpuProfile.BALANCED.value)
        self.preserve_temp_files_var = tk.BooleanVar(value=False)
        self.use_existing_part_meshes_var = tk.BooleanVar(value=False)
        self.material_policy_var = tk.StringVar(value=MaterialPolicy.LEGACY_ROLE_IDS.value)
        self.bark_material_var = tk.StringVar()
        self.leaves_material_var = tk.StringVar()
        self.single_material_var = tk.StringVar()
        self.gust_attenuation_var = tk.DoubleVar(value=0.0)
        self.is_ground_cover_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(
            value="Single-file mode. Convert and Dynamic Wind JSON generation are available."
        )
        self._sections: dict[str, dict[str, object]] = {}
        self._part_mesh_rows: list[dict[str, object]] = []
        self._wind_group_rows: list[dict[str, object]] = []
        self._persisted_wind_group_settings: dict[str, dict[str, object]] = {}
        self._persisted_part_mesh_settings_by_input_path: dict[str, list[dict[str, object]]] = {}
        self._current_part_mesh_settings_key: str | None = None
        self._pending_settings_save_job: str | None = None
        self._suspend_settings_save = False
        self._conversion_thread: threading.Thread | None = None
        self._conversion_cancel_event = threading.Event()
        self._conversion_queue: Queue[tuple[str, object]] = Queue()
        self._conversion_queue_job: str | None = None
        self._load_settings()
        self._runtime_cleanup_summary = sweep_stale_job_workspaces(self._runtime_paths())

        self._build_layout()
        self._install_persistence_hooks()
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
            text="Balanced keeps 2 logical CPUs free for the system during heavy FBX export.",
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
        materials_content.columnconfigure(1, weight=1)
        ttk.Label(materials_content, text="Material Policy").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.material_policy_combo = ttk.Combobox(
            materials_content,
            textvariable=self.material_policy_var,
            state="readonly",
            values=tuple(policy.value for policy in MaterialPolicy),
        )
        self.material_policy_combo.grid(row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))

        self.bark_material_row = ttk.Frame(materials_content)
        self.bark_material_row.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.bark_material_row.columnconfigure(1, weight=1)
        ttk.Label(self.bark_material_row, text="Bark Material Path").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.bark_material_row, textvariable=self.bark_material_var).grid(
            row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )

        self.leaves_material_row = ttk.Frame(materials_content)
        self.leaves_material_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.leaves_material_row.columnconfigure(1, weight=1)
        ttk.Label(self.leaves_material_row, text="Leaves Material Path").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.leaves_material_row, textvariable=self.leaves_material_var).grid(
            row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )

        self.single_material_row = ttk.Frame(materials_content)
        self.single_material_row.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.single_material_row.columnconfigure(1, weight=1)
        ttk.Label(self.single_material_row, text="Single Material Path").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(self.single_material_row, textvariable=self.single_material_var).grid(
            row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )
        self._apply_material_policy_visibility()

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

        self.part_mesh_rows_container = ttk.Frame(part_mesh_content)
        self.part_mesh_rows_container.grid(row=1, column=0, sticky="ew")
        self.part_mesh_rows_container.columnconfigure(0, weight=1)

        self._part_mesh_rows_placeholder = ttk.Label(self.part_mesh_rows_container, text="Select an XML file to load part meshes.")
        self._part_mesh_rows_placeholder.grid(row=0, column=0, sticky="w")

        row += 1
        wind_content = self._create_collapsible_section(self.content_frame, row, "Wind Profile", "wind")
        self.wind_frame = wind_content
        wind_content.columnconfigure(1, weight=1)
        wind_content.columnconfigure(3, weight=1)

        ttk.Button(wind_content, text="Refresh Wind Groups", command=self.refresh_wind_groups).grid(
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
        self.input_var.set(selected)
        if not self.output_var.get():
            self.output_var.set(str(Path(selected).with_suffix(".usda")))
        self.refresh_wind_groups()

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
            messagebox.showerror("Missing input", "Select a source XML file before loading wind groups.")
            return
        try:
            dynamic_wind = inspect_wind_data(input_path, is_ground_cover=bool(self.is_ground_cover_var.get()))
        except Exception as exc:
            self.status_var.set("Wind group inspection failed.")
            self._set_log(str(exc))
            messagebox.showerror("Wind group inspection failed", str(exc))
            return

        self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
        self.status_var.set(
            f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from generator levels."
        )
        self._set_log(format_wind_group_summary(dynamic_wind))

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
            messagebox.showerror("Missing input", "Select a source XML file.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Select an output USDA path.")
            return
        validation_error = self._validate_material_paths(
            material_policy,
            bark_material_path,
            leaves_material_path,
            single_material_path,
        )
        if validation_error is not None:
            messagebox.showerror("Invalid material path", validation_error)
            return
        try:
            prototype_source_configs = self._collect_part_source_configs()
            use_existing_part_meshes, part_mesh_asset_paths = self._collect_part_mesh_overrides()
        except ValueError as exc:
            messagebox.showerror("Invalid PartMesh mapping", str(exc))
            return

        has_fbx_sources = any(config.mode == PrototypeSourceMode.FBX_FILE for config in prototype_source_configs)
        uses_new_source_contract = has_fbx_sources or (
            prototype_source_configs
            and (
                cpu_profile != CpuProfile.BALANCED
                or any(config.mode != PrototypeSourceMode.UNREAL_ASSET for config in prototype_source_configs)
            )
        )

        if has_fbx_sources:
            self._start_conversion_async(
                input_path=input_path,
                output_path=output_path,
                cpu_profile=cpu_profile,
                cleanup_policy=cleanup_policy,
                material_policy=material_policy,
                bark_material_path=effective_bark_material_path,
                leaves_material_path=effective_leaves_material_path,
                single_material_path=effective_single_material_path,
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
            if uses_new_source_contract:
                convert_kwargs["cpu_profile"] = cpu_profile
                convert_kwargs["cleanup_policy"] = cleanup_policy
                convert_kwargs["prototype_source_configs"] = prototype_source_configs
            else:
                convert_kwargs["use_existing_part_meshes"] = use_existing_part_meshes
                convert_kwargs["part_mesh_asset_paths"] = part_mesh_asset_paths
                convert_kwargs["cleanup_policy"] = cleanup_policy
            convert_kwargs["runtime_paths"] = self._runtime_paths()
            result = convert_file(input_path, output_path, **convert_kwargs)
        except Exception as exc:
            self.status_var.set("Conversion failed.")
            self._set_log(str(exc))
            messagebox.showerror("Conversion failed", str(exc))
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
                prototype_source_configs=prototype_source_configs,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
            )
        )
        if result.usda_document is None:
            self.status_var.set("Conversion finished with errors.")
            messagebox.showerror("Conversion failed", "See diagnostics in the log area.")
            return

        self.status_var.set(f"Wrote USDA to {result.output_path}")
        messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")

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
        use_existing_part_meshes: bool,
        part_mesh_asset_paths: tuple[tuple[str, str], ...],
        prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    ) -> None:
        if self._conversion_thread is not None and self._conversion_thread.is_alive():
            messagebox.showerror("Conversion running", "A conversion is already running.")
            return

        self._conversion_cancel_event = threading.Event()
        self._set_conversion_running(True)
        self.status_var.set("Preparing FBX conversion job.")
        self._set_log(
            "Starting background FBX conversion.\n"
            "The UI stays responsive while geometry is imported and the USDA file is streamed to disk."
        )
        self._conversion_thread = threading.Thread(
            target=self._run_conversion_worker,
            kwargs={
                "input_path": input_path,
                "output_path": output_path,
                "cpu_profile": cpu_profile,
                "cleanup_policy": cleanup_policy,
                "material_policy": material_policy,
                "bark_material_path": bark_material_path,
                "leaves_material_path": leaves_material_path,
                "single_material_path": single_material_path,
                "use_existing_part_meshes": use_existing_part_meshes,
                "part_mesh_asset_paths": part_mesh_asset_paths,
                "prototype_source_configs": prototype_source_configs,
            },
            daemon=True,
        )
        self._conversion_thread.start()
        self._schedule_conversion_queue_poll()

    def _run_conversion_worker(
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
        use_existing_part_meshes: bool,
        part_mesh_asset_paths: tuple[tuple[str, str], ...],
        prototype_source_configs: tuple[PrototypeSourceConfig, ...],
    ) -> None:
        try:
            result = convert_file(
                input_path,
                output_path,
                material_policy=material_policy,
                bark_material_path=bark_material_path,
                leaves_material_path=leaves_material_path,
                single_material_path=single_material_path,
                cpu_profile=cpu_profile,
                cleanup_policy=cleanup_policy,
                prototype_source_configs=prototype_source_configs,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
                telemetry_callback=self._enqueue_conversion_telemetry,
                cancel_event=self._conversion_cancel_event,
                runtime_paths=self._runtime_paths(),
            )
            self._conversion_queue.put(
                (
                    "result",
                    (
                        ConversionJobResult(result=result),
                        {
                            "cpu_profile": cpu_profile,
                            "cleanup_policy": cleanup_policy,
                            "material_policy": material_policy,
                            "bark_material_path": bark_material_path,
                            "leaves_material_path": leaves_material_path,
                            "single_material_path": single_material_path,
                            "prototype_source_configs": prototype_source_configs,
                            "use_existing_part_meshes": use_existing_part_meshes,
                            "part_mesh_asset_paths": part_mesh_asset_paths,
                        },
                    ),
                )
            )
        except Exception as exc:
            cancelled = bool(self._conversion_cancel_event.is_set())
            self._conversion_queue.put(
                (
                    "result",
                    (
                        ConversionJobResult(cancelled=cancelled, error_message=str(exc)),
                        {
                            "cpu_profile": cpu_profile,
                            "cleanup_policy": cleanup_policy,
                            "material_policy": material_policy,
                            "bark_material_path": bark_material_path,
                            "leaves_material_path": leaves_material_path,
                            "single_material_path": single_material_path,
                            "prototype_source_configs": prototype_source_configs,
                            "use_existing_part_meshes": use_existing_part_meshes,
                            "part_mesh_asset_paths": part_mesh_asset_paths,
                        },
                    ),
                )
            )

    def _enqueue_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        self._conversion_queue.put(("telemetry", telemetry))

    def _schedule_conversion_queue_poll(self) -> None:
        if self._conversion_queue_job is not None:
            return
        self._conversion_queue_job = self.root.after(100, self._poll_conversion_queue)

    def _poll_conversion_queue(self) -> None:
        self._conversion_queue_job = None
        keep_polling = False
        while True:
            try:
                event_name, payload = self._conversion_queue.get_nowait()
            except Empty:
                break
            if event_name == "telemetry":
                self._handle_conversion_telemetry(payload)
                keep_polling = True
                continue
            if event_name == "result":
                job_result, context = payload
                self._handle_conversion_job_result(job_result, context)
                keep_polling = False
                continue
        if self._conversion_thread is not None and self._conversion_thread.is_alive():
            keep_polling = True
        if keep_polling:
            self._schedule_conversion_queue_poll()

    def _handle_conversion_telemetry(self, telemetry: ConversionTelemetry) -> None:
        self.status_var.set(_format_telemetry_status(telemetry))

    def _handle_conversion_job_result(self, job_result: ConversionJobResult, context: dict[str, object]) -> None:
        self._set_conversion_running(False)
        self._conversion_thread = None
        self._save_settings()

        if job_result.error_message:
            status = "Conversion cancelled." if job_result.cancelled else "Conversion failed."
            self.status_var.set(status)
            self._set_log(job_result.error_message)
            if not job_result.cancelled:
                messagebox.showerror("Conversion failed", job_result.error_message)
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
                prototype_source_configs=context["prototype_source_configs"],
                use_existing_part_meshes=context["use_existing_part_meshes"],
                part_mesh_asset_paths=context["part_mesh_asset_paths"],
            )
        )
        if result.usda_document is None:
            self.status_var.set("Conversion finished with errors.")
            messagebox.showerror("Conversion failed", "See diagnostics in the log area.")
            return

        self.status_var.set(f"Wrote USDA to {result.output_path}")
        messagebox.showinfo("Conversion complete", f"Wrote USDA to {result.output_path}")

    def _set_conversion_running(self, active: bool) -> None:
        self.convert_button.configure(state="disabled" if active else "normal")
        self.cancel_button.configure(state="normal" if active else "disabled")

    def cancel_conversion(self) -> None:
        if self._conversion_thread is None or not self._conversion_thread.is_alive():
            return
        self._conversion_cancel_event.set()
        self.status_var.set("Cancelling conversion...")

    def run_generate_wind_json(self) -> None:
        input_path = self.input_var.get().strip()
        if not input_path:
            messagebox.showerror("Missing input", "Select a source XML file.")
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
            self.status_var.set("Wind JSON generation failed.")
            self._set_log(str(exc))
            messagebox.showerror("Wind JSON generation failed", str(exc))
            return

        self._save_settings()
        self._set_log(format_wind_json_result(result))
        self.status_var.set(f"Wrote wind JSON to {result.output_path}")
        messagebox.showinfo("Wind JSON complete", f"Wrote wind JSON to {result.output_path}")

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
            if mode == PrototypeSourceMode.XML_MESH:
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
                    fbx_material_mode=fbx_material_mode,
                    fbx_path=str(resolved),
                )
            )
        return tuple(configs)

    def _handle_source_path_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        input_path = self.input_var.get().strip()
        if not input_path:
            self._clear_part_mesh_rows()
            return
        path = Path(input_path)
        if not path.exists():
            return
        try:
            self._refresh_part_mesh_rows(input_path)
        except Exception as exc:
            self.status_var.set("Part mesh discovery failed.")
            self._set_log(str(exc))
            messagebox.showerror("Part mesh discovery failed", str(exc))

    def _clear_part_mesh_rows(self) -> None:
        self._current_part_mesh_settings_key = None
        self._part_mesh_rows.clear()
        for child in self.part_mesh_rows_container.winfo_children():
            child.destroy()
        self._part_mesh_rows_placeholder = ttk.Label(
            self.part_mesh_rows_container,
            text="Select an XML file to load part meshes.",
        )
        self._part_mesh_rows_placeholder.grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def _refresh_part_mesh_rows(self, input_path: str) -> None:
        if self._suspend_settings_save:
            return
        self._suspend_settings_save = True
        try:
            _, model, _diagnostics = load_canonical_model(input_path)
            resolved_key = self._resolve_input_settings_key(input_path)
            self._current_part_mesh_settings_key = resolved_key
            persisted_rows = self._persisted_part_mesh_settings_by_input_path.get(resolved_key, [])
            self._rebuild_part_mesh_rows(model.prototypes, persisted_rows)
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
            ttk.Label(self.part_mesh_rows_container, text="No repeated part meshes found in this XML.").grid(
                row=0, column=0, sticky="w"
            )
            self._refresh_scroll_region()
            return

        self.part_mesh_rows_container.columnconfigure(0, weight=1)
        header = ttk.Frame(self.part_mesh_rows_container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(0, weight=2)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=1)
        header.columnconfigure(3, weight=4)
        header.columnconfigure(4, weight=4)
        header.columnconfigure(5, weight=2)
        header.columnconfigure(6, weight=0)
        ttk.Label(header, text="XML Mesh").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Mesh ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Source Mode").grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Unreal Object Path").grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Label(header, text="FBX File").grid(row=0, column=4, sticky="w")
        ttk.Label(header, text="FBX Materials").grid(row=0, column=5, sticky="w", padx=(12, 12))

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
            row_frame.columnconfigure(2, weight=1)
            row_frame.columnconfigure(3, weight=4)
            row_frame.columnconfigure(4, weight=4)
            row_frame.columnconfigure(5, weight=2)

            mesh_id_text = f"Mesh_{prototype.source_mesh_id}" if prototype.source_mesh_id is not None else "<none>"
            display_name = prototype.source_name or prototype.source_key
            ttk.Label(row_frame, text=display_name).grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=mesh_id_text).grid(row=0, column=1, sticky="w", padx=(12, 12))

            source_mode_var = tk.StringVar(value=PrototypeSourceMode.XML_MESH.value)
            use_unreal_var = tk.BooleanVar(value=False)
            asset_var = tk.StringVar(value="")
            fbx_var = tk.StringVar(value="")
            fbx_material_mode_var = tk.StringVar(value=FbxMaterialMode.AUTO.value)
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
                values=tuple(mode.value for mode in FbxMaterialMode),
                width=18,
            )
            browse_button = ttk.Button(
                row_frame,
                text="Browse...",
                command=lambda var=fbx_var: self._browse_part_fbx(var),
            )
            source_mode_combo.grid(row=0, column=2, sticky="ew", padx=(0, 12))
            asset_entry.grid(row=0, column=3, sticky="ew")
            fbx_entry.grid(row=0, column=4, sticky="ew", padx=(12, 8))
            fbx_material_mode_combo.grid(row=0, column=5, sticky="ew", padx=(0, 12))
            browse_button.grid(row=0, column=6, sticky="ew")

            record = persisted_by_name.get(display_name) or persisted_by_key.get(str(prototype.source_key))
            if record is not None:
                restored_mode = str(record.get("source_mode", "")).strip() or (
                    PrototypeSourceMode.UNREAL_ASSET.value if bool(record.get("use_unreal_reference", False)) else PrototypeSourceMode.XML_MESH.value
                )
                if restored_mode not in {mode.value for mode in PrototypeSourceMode}:
                    restored_mode = PrototypeSourceMode.XML_MESH.value
                restored_fbx_material_mode = str(
                    record.get("fbx_material_mode", FbxMaterialMode.AUTO.value)
                ).strip()
                if restored_fbx_material_mode not in {mode.value for mode in FbxMaterialMode}:
                    restored_fbx_material_mode = FbxMaterialMode.AUTO.value
                source_mode_var.set(restored_mode)
                fbx_material_mode_var.set(restored_fbx_material_mode)
                use_unreal_var.set(restored_mode == PrototypeSourceMode.UNREAL_ASSET.value)
                asset_var.set(str(record.get("unreal_asset_path", "")))
                fbx_var.set(str(record.get("fbx_path", "")))

            self._handle_part_source_mode_change(
                asset_entry,
                fbx_entry,
                fbx_material_mode_combo,
                browse_button,
                source_mode_var,
            )
            asset_var.trace_add("write", self._handle_persisted_field_change)
            fbx_var.trace_add("write", self._handle_persisted_field_change)
            fbx_material_mode_var.trace_add("write", self._handle_persisted_field_change)
            source_mode_var.trace_add("write", self._handle_persisted_field_change)
            source_mode_var.trace_add(
                "write",
                lambda *_args, entry=asset_entry, fbx_entry=fbx_entry, material_combo=fbx_material_mode_combo, button=browse_button, var=source_mode_var, unreal_var=use_unreal_var: self._handle_source_mode_trace(entry, fbx_entry, material_combo, button, var, unreal_var),
            )
            use_unreal_var.trace_add("write", lambda *_args, mode_var=source_mode_var, unreal_var=use_unreal_var: self._handle_legacy_unreal_toggle(mode_var, unreal_var))

            self._part_mesh_rows.append(
                {
                    "source_key": prototype.source_key,
                    "source_name": display_name,
                    "mesh_id": prototype.source_mesh_id,
                    "source_mode_var": source_mode_var,
                    "use_unreal_var": use_unreal_var,
                    "asset_var": asset_var,
                    "fbx_var": fbx_var,
                    "fbx_material_mode_var": fbx_material_mode_var,
                    "asset_entry": asset_entry,
                    "fbx_entry": fbx_entry,
                    "fbx_material_mode_combo": fbx_material_mode_combo,
                    "browse_button": browse_button,
                    "source_mode_combo": source_mode_combo,
                }
            )
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
        asset_entry: ttk.Entry,
        fbx_entry: ttk.Entry,
        fbx_material_mode_combo: ttk.Combobox,
        browse_button: ttk.Button,
        source_mode_var: tk.StringVar,
        use_unreal_var: tk.BooleanVar,
    ) -> None:
        self._handle_part_source_mode_change(asset_entry, fbx_entry, fbx_material_mode_combo, browse_button, source_mode_var)
        use_unreal_var.set(source_mode_var.get() == PrototypeSourceMode.UNREAL_ASSET.value)

    def _handle_legacy_unreal_toggle(self, source_mode_var: tk.StringVar, use_unreal_var: tk.BooleanVar) -> None:
        if bool(use_unreal_var.get()):
            source_mode_var.set(PrototypeSourceMode.UNREAL_ASSET.value)
        elif source_mode_var.get() == PrototypeSourceMode.UNREAL_ASSET.value:
            source_mode_var.set(PrototypeSourceMode.XML_MESH.value)

    def _handle_part_source_mode_change(
        self,
        asset_entry: ttk.Entry,
        fbx_entry: ttk.Entry,
        fbx_material_mode_combo: ttk.Combobox,
        browse_button: ttk.Button,
        source_mode_var: tk.StringVar,
    ) -> None:
        mode = PrototypeSourceMode(source_mode_var.get())
        asset_entry.configure(state="normal" if mode == PrototypeSourceMode.UNREAL_ASSET else "disabled")
        fbx_state = "normal" if mode == PrototypeSourceMode.FBX_FILE else "disabled"
        fbx_entry.configure(state=fbx_state)
        fbx_material_mode_combo.configure(state="readonly" if mode == PrototypeSourceMode.FBX_FILE else "disabled")
        browse_button.configure(state=fbx_state)

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
        if self.input_var.get().strip():
            self.refresh_wind_groups()

    def _current_material_policy(self) -> MaterialPolicy:
        try:
            return MaterialPolicy(self.material_policy_var.get())
        except ValueError:
            return MaterialPolicy.LEGACY_ROLE_IDS

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
        self._set_log(summary_message)

    def _apply_material_policy_visibility(self) -> None:
        if not hasattr(self, "bark_material_row"):
            return
        material_policy = self._current_material_policy()
        show_single = material_policy == MaterialPolicy.SINGLE_MATERIAL
        self._set_frame_visible(self.single_material_row, show_single)
        self._set_frame_visible(self.bark_material_row, not show_single)
        self._set_frame_visible(self.leaves_material_row, not show_single)

    def _handle_window_close(self) -> None:
        if self._conversion_queue_job is not None:
            try:
                self.root.after_cancel(self._conversion_queue_job)
            except tk.TclError:
                pass
            self._conversion_queue_job = None
        if self._conversion_thread is not None and self._conversion_thread.is_alive():
            self._conversion_cancel_event.set()
        if self._pending_settings_save_job is not None:
            try:
                self.root.after_cancel(self._pending_settings_save_job)
            except tk.TclError:
                pass
            self._pending_settings_save_job = None
        self._save_settings()
        self.root.destroy()

    def _load_settings(self) -> None:
        settings = self._read_settings()
        self.cpu_profile_var.set(str(settings.get("cpu_profile", CpuProfile.BALANCED.value)))
        self.preserve_temp_files_var.set(bool(settings.get("preserve_temp_files", False)))
        self.material_policy_var.set(str(settings.get("material_policy", MaterialPolicy.LEGACY_ROLE_IDS.value)))
        self.bark_material_var.set(str(settings.get("bark_material_path", "")))
        self.leaves_material_var.set(str(settings.get("leaves_material_path", "")))
        self.single_material_var.set(str(settings.get("single_material_path", "")))
        self.gust_attenuation_var.set(float(settings.get("gust_attenuation", 0.0)))
        self.is_ground_cover_var.set(bool(settings.get("is_ground_cover", False)))
        self._persisted_wind_group_settings = dict(settings.get("wind_group_settings", {}))
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
        part_mesh_settings = payload.get("part_mesh_settings_by_input_path", {})
        if not isinstance(part_mesh_settings, dict):
            part_mesh_settings = {}
        return {
            "cpu_profile": payload.get("cpu_profile", CpuProfile.BALANCED.value),
            "preserve_temp_files": payload.get("preserve_temp_files", False),
            "material_policy": payload.get("material_policy", MaterialPolicy.LEGACY_ROLE_IDS.value),
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
            part_mesh_settings_by_input_path = dict(self._persisted_part_mesh_settings_by_input_path)
            current_part_mesh_settings = self._serialize_part_mesh_settings()
            if self._current_part_mesh_settings_key is not None:
                if current_part_mesh_settings:
                    part_mesh_settings_by_input_path[self._current_part_mesh_settings_key] = current_part_mesh_settings
                else:
                    part_mesh_settings_by_input_path.pop(self._current_part_mesh_settings_key, None)
            payload = {
                "material_policy": self._current_material_policy().value,
                "bark_material_path": self.bark_material_var.get().strip(),
                "leaves_material_path": self.leaves_material_var.get().strip(),
                "single_material_path": self.single_material_var.get().strip(),
                "gust_attenuation": round(float(self.gust_attenuation_var.get()), 4),
                "is_ground_cover": bool(self.is_ground_cover_var.get()),
                "wind_group_settings": self._serialize_wind_group_settings(),
            }
            if self._current_cpu_profile() != CpuProfile.BALANCED:
                payload["cpu_profile"] = self._current_cpu_profile().value
            if bool(self.preserve_temp_files_var.get()):
                payload["preserve_temp_files"] = True
            if part_mesh_settings_by_input_path:
                payload["part_mesh_settings_by_input_path"] = part_mesh_settings_by_input_path
            self.SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._persisted_part_mesh_settings_by_input_path = part_mesh_settings_by_input_path
        except OSError:
            return

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
            if source_mode == PrototypeSourceMode.XML_MESH and not use_unreal_reference and not asset_path and not fbx_path:
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
    material_policy: MaterialPolicy = MaterialPolicy.LEGACY_ROLE_IDS,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    single_material_path: str | None = None,
    prototype_source_configs: tuple[PrototypeSourceConfig, ...] = (),
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
) -> str:
    lines: list[str] = [
        f"CPU profile: {cpu_profile.value}",
        f"Cleanup policy: {cleanup_policy.value}",
        f"Material policy: {material_policy.value}",
    ]
    if material_policy == MaterialPolicy.SINGLE_MATERIAL and single_material_path:
        lines.append(f"Single material path: {single_material_path}")
        lines.append("")
    elif bark_material_path or leaves_material_path:
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
                lines.append(f"  - {source_label}: xml_mesh")
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
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0
