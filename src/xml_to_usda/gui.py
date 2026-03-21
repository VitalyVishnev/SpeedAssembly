from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import DynamicWindSimulationGroup
from .pipeline import convert_file, generate_wind_json, inspect_wind_data, load_canonical_model


class ConversionApp:
    SETTINGS_DIR = Path.home() / ".xml_to_usda"
    SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"
    MAX_WIND_INFLUENCE = 1.0
    MAX_SHIFT_TOP = 1.0

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convert XML -> USDA")
        self.root.minsize(900, 620)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.bark_material_var = tk.StringVar()
        self.leaves_material_var = tk.StringVar()
        self.use_existing_part_meshes_var = tk.BooleanVar(value=False)
        self.gust_attenuation_var = tk.DoubleVar(value=0.0)
        self.is_ground_cover_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(
            value="Single-file mode. Convert and Dynamic Wind JSON generation are available."
        )
        self._sections: dict[str, dict[str, object]] = {}
        self._part_mesh_rows: list[dict[str, object]] = []
        self._wind_group_rows: list[dict[str, object]] = []
        self._persisted_wind_group_settings: dict[str, dict[str, float]] = {}
        self._persisted_part_mesh_settings_by_input_path: dict[str, list[dict[str, object]]] = {}
        self._current_part_mesh_settings_key: str | None = None
        self._suspend_settings_save = False
        self._load_settings()

        self._build_layout()
        self._install_persistence_hooks()

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
        materials_content = self._create_collapsible_section(self.content_frame, row, "Materials", "materials")
        self.materials_frame = materials_content
        materials_content.columnconfigure(1, weight=1)
        ttk.Label(materials_content, text="Bark Material Path").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(materials_content, textvariable=self.bark_material_var).grid(
            row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )

        ttk.Label(materials_content, text="Leaves Material Path").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(materials_content, textvariable=self.leaves_material_var).grid(
            row=1, column=1, sticky="ew", padx=(12, 12), pady=(0, 8)
        )

        row += 1
        part_mesh_content = self._create_collapsible_section(self.content_frame, row, "Part Mesh Reuse", "part_mesh")
        self.part_mesh_frame = part_mesh_content
        part_mesh_content.columnconfigure(0, weight=1)
        part_mesh_intro = ttk.Label(
            part_mesh_content,
            text="Rows are discovered from the XML leaf-reference mesh library. Enable Unreal reference to reuse an existing asset.",
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
        ttk.Button(action_row, text="Generate Wind JSON", command=self.run_generate_wind_json).pack(side="right")
        ttk.Button(action_row, text="Convert", command=self.run_conversion).pack(side="right", padx=(0, 8))

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
        bark_material_path = self.bark_material_var.get().strip()
        leaves_material_path = self.leaves_material_var.get().strip()
        if not input_path:
            messagebox.showerror("Missing input", "Select a source XML file.")
            return
        if not output_path:
            messagebox.showerror("Missing output", "Select an output USDA path.")
            return
        validation_error = self._validate_material_paths(bark_material_path, leaves_material_path)
        if validation_error is not None:
            messagebox.showerror("Invalid material path", validation_error)
            return
        try:
            use_existing_part_meshes, part_mesh_asset_paths = self._collect_part_mesh_overrides()
        except ValueError as exc:
            messagebox.showerror("Invalid PartMesh mapping", str(exc))
            return

        try:
            result = convert_file(
                input_path,
                output_path,
                bark_material_path=bark_material_path or None,
                leaves_material_path=leaves_material_path or None,
                use_existing_part_meshes=use_existing_part_meshes,
                part_mesh_asset_paths=part_mesh_asset_paths,
            )
        except Exception as exc:
            self.status_var.set("Conversion failed.")
            self._set_log(str(exc))
            messagebox.showerror("Conversion failed", str(exc))
            return

        self._save_settings()
        self._set_log(
            format_conversion_results(
                (result,),
                bark_material_path=bark_material_path or None,
                leaves_material_path=leaves_material_path or None,
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

    def _validate_material_paths(self, bark_material_path: str, leaves_material_path: str) -> str | None:
        for label, path in (("Bark", bark_material_path), ("Leaves", leaves_material_path)):
            if path and not _is_valid_unreal_asset_path(path):
                return f"{label} material path must start with /Game/."
        return None

    def _collect_part_mesh_overrides(self) -> tuple[bool, tuple[tuple[str, str], ...]]:
        if not self._part_mesh_rows:
            return False, ()

        mappings: list[tuple[str, str]] = []
        use_existing_part_meshes = False
        for row in self._part_mesh_rows:
            if not bool(row["use_unreal_var"].get()):
                continue
            use_existing_part_meshes = True
            asset_path = str(row["asset_var"].get()).strip()
            if not asset_path:
                continue
            if not _is_valid_unreal_asset_path(asset_path):
                label = str(row["source_name"])
                raise ValueError(f"PartMesh asset path for {label} must start with /Game/.")
            mappings.append((str(row["source_name"]), asset_path))
        return use_existing_part_meshes, tuple(mappings)

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
        header.columnconfigure(0, weight=3)
        header.columnconfigure(1, weight=0)
        header.columnconfigure(2, weight=0)
        header.columnconfigure(3, weight=5)
        ttk.Label(header, text="XML Mesh").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Mesh ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Use Unreal reference").grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Unreal Object Path").grid(row=0, column=3, sticky="w")

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
            row_frame.columnconfigure(0, weight=3)
            row_frame.columnconfigure(3, weight=5)

            mesh_id_text = f"Mesh_{prototype.source_mesh_id}" if prototype.source_mesh_id is not None else "<none>"
            display_name = prototype.source_name or prototype.source_key
            ttk.Label(row_frame, text=display_name).grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=mesh_id_text).grid(row=0, column=1, sticky="w", padx=(12, 12))

            use_unreal_var = tk.BooleanVar(value=False)
            asset_var = tk.StringVar(value="")
            asset_entry = ttk.Entry(row_frame, textvariable=asset_var)
            checkbox = ttk.Checkbutton(
                row_frame,
                variable=use_unreal_var,
                command=lambda entry=asset_entry, var=use_unreal_var: self._handle_part_mesh_toggle(entry, var),
            )
            checkbox.grid(row=0, column=2, sticky="w", padx=(0, 12))
            asset_entry.grid(row=0, column=3, sticky="ew")

            record = persisted_by_name.get(display_name) or persisted_by_key.get(str(prototype.source_key))
            if record is not None:
                use_unreal_var.set(bool(record.get("use_unreal_reference", False)))
                asset_var.set(str(record.get("unreal_asset_path", "")))

            self._handle_part_mesh_toggle(asset_entry, use_unreal_var)
            asset_var.trace_add("write", self._handle_persisted_field_change)
            use_unreal_var.trace_add("write", self._handle_persisted_field_change)

            self._part_mesh_rows.append(
                {
                    "source_key": prototype.source_key,
                    "source_name": display_name,
                    "mesh_id": prototype.source_mesh_id,
                    "use_unreal_var": use_unreal_var,
                    "asset_var": asset_var,
                    "asset_entry": asset_entry,
                    "checkbox": checkbox,
                }
            )
            row_index += 1

        self._refresh_scroll_region()

    def _handle_part_mesh_toggle(self, asset_entry: ttk.Entry, use_unreal_var: tk.BooleanVar) -> None:
        asset_entry.configure(state="normal" if bool(use_unreal_var.get()) else "disabled")

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
        self.bark_material_var.trace_add("write", self._handle_persisted_field_change)
        self.leaves_material_var.trace_add("write", self._handle_persisted_field_change)
        self.gust_attenuation_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_ground_cover_change)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close)

    def _handle_persisted_field_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        self._save_settings()

    def _handle_ground_cover_change(self, *_args) -> None:
        if self._suspend_settings_save:
            return
        if self.input_var.get().strip():
            self.refresh_wind_groups()

    def _handle_window_close(self) -> None:
        self._save_settings()
        self.root.destroy()

    def _load_settings(self) -> None:
        settings = self._read_settings()
        self.bark_material_var.set(str(settings.get("bark_material_path", "")))
        self.leaves_material_var.set(str(settings.get("leaves_material_path", "")))
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
            "bark_material_path": payload.get("bark_material_path", ""),
            "leaves_material_path": payload.get("leaves_material_path", ""),
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
            self.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            part_mesh_settings_by_input_path = dict(self._persisted_part_mesh_settings_by_input_path)
            current_part_mesh_settings = self._serialize_part_mesh_settings()
            if self._current_part_mesh_settings_key is not None:
                if current_part_mesh_settings:
                    part_mesh_settings_by_input_path[self._current_part_mesh_settings_key] = current_part_mesh_settings
                else:
                    part_mesh_settings_by_input_path.pop(self._current_part_mesh_settings_key, None)
            payload = {
                "bark_material_path": self.bark_material_var.get().strip(),
                "leaves_material_path": self.leaves_material_var.get().strip(),
                "gust_attenuation": round(float(self.gust_attenuation_var.get()), 4),
                "is_ground_cover": bool(self.is_ground_cover_var.get()),
                "wind_group_settings": self._serialize_wind_group_settings(),
            }
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
            use_unreal_reference = bool(row["use_unreal_var"].get())
            asset_path = str(row["asset_var"].get()).strip()
            if not use_unreal_reference and not asset_path:
                continue
            serialized.append(
                {
                    "source_name": str(row["source_name"]),
                    "source_key": str(row["source_key"]),
                    "use_unreal_reference": use_unreal_reference,
                    "unreal_asset_path": asset_path,
                }
            )
        return serialized

    def _serialize_wind_group_settings(self) -> dict[str, dict[str, float]]:
        if not self._wind_group_rows:
            return dict(self._persisted_wind_group_settings)
        serialized: dict[str, dict[str, float]] = {}
        for row in self._wind_group_rows:
            group_index = int(row["group_index"])
            influence_var = row["influence_var"]
            shift_var = row["shift_var"]
            serialized[str(group_index)] = {
                "influence": round(float(influence_var.get()), 4),
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
            title = f"Group {group.group_index} ({'Trunk' if group.is_trunk_group else f'Generator level {group.branch_order}'})"
            ttk.Label(self.wind_groups_container, text=title).grid(row=row_index * 2, column=0, sticky="w", pady=(4, 0))

            influence_var = tk.DoubleVar(value=self._persisted_group_value(group.group_index, "influence", group.influence))
            influence_value_var = tk.StringVar(value=f"{influence_var.get():.2f}")
            tk.Scale(
                self.wind_groups_container,
                from_=0.0,
                to=self.MAX_WIND_INFLUENCE,
                resolution=0.05,
                orient="horizontal",
                variable=influence_var,
                command=lambda value, value_var=influence_value_var: self._handle_scale_change(value, value_var),
            ).grid(row=row_index * 2, column=1, sticky="ew", padx=(12, 12), pady=(4, 0))
            ttk.Label(self.wind_groups_container, textvariable=influence_value_var, width=6).grid(
                row=row_index * 2, column=2, sticky="e", pady=(4, 0)
            )

            shift_var = tk.DoubleVar(value=self._persisted_group_value(group.group_index, "shift_top", group.shift_top))
            shift_value_var = tk.StringVar(value=f"{shift_var.get():.2f}")
            ttk.Label(self.wind_groups_container, text="Shift Top").grid(row=row_index * 2 + 1, column=0, sticky="w")
            tk.Scale(
                self.wind_groups_container,
                from_=0.0,
                to=self.MAX_SHIFT_TOP,
                resolution=0.01,
                orient="horizontal",
                variable=shift_var,
                command=lambda value, value_var=shift_value_var: self._handle_scale_change(value, value_var),
            ).grid(row=row_index * 2 + 1, column=1, sticky="ew", padx=(12, 12), pady=(0, 4))
            ttk.Label(self.wind_groups_container, textvariable=shift_value_var, width=6).grid(
                row=row_index * 2 + 1, column=2, sticky="e", pady=(0, 4)
            )

            self._wind_group_rows.append(
                {
                    "group_index": group.group_index,
                    "branch_order": group.branch_order,
                    "is_trunk_group": group.is_trunk_group,
                    "influence_var": influence_var,
                    "shift_var": shift_var,
                }
            )

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

    def _collect_wind_group_settings(self) -> tuple[DynamicWindSimulationGroup, ...]:
        return tuple(
            DynamicWindSimulationGroup(
                group_index=int(row["group_index"]),
                branch_order=int(row["branch_order"]),
                influence=float(row["influence_var"].get()),
                shift_top=float(row["shift_var"].get()),
                is_trunk_group=bool(row["is_trunk_group"]),
            )
            for row in self._wind_group_rows
        )

    def _handle_gust_change(self, value: float) -> None:
        self.gust_value_var.set(f"{value:.2f}")
        self._save_settings()

    def _handle_scale_change(self, value: str, value_var: tk.StringVar) -> None:
        value_var.set(f"{float(value):.2f}")
        self._save_settings()


def format_conversion_results(
    results,
    bark_material_path: str | None = None,
    leaves_material_path: str | None = None,
    use_existing_part_meshes: bool = False,
    part_mesh_asset_paths: tuple[tuple[str, str], ...] = (),
) -> str:
    lines: list[str] = []
    if bark_material_path or leaves_material_path:
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
    for result in results:
        lines.append(f"Input: {result.input_path}")
        lines.append(f"Output: {result.output_path or '<not written>'}")
        if result.diagnostics:
            lines.append("Diagnostics:")
            for issue in result.diagnostics:
                lines.append(f"  - [{issue.severity}] {issue.code}: {issue.message}")
        else:
            lines.append("Diagnostics: none")
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
        lines.append(
            f"Group {group.group_index}: {label}, branch_order={group.branch_order}, joints={joint_count}"
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
        lines.append(
            f"Group {group.group_index}: level={group.branch_order}, influence={group.influence:.2f}, shiftTop={group.shift_top:.2f}, trunk={group.is_trunk_group}"
        )
    return "\n".join(lines)


def _is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def main() -> int:
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0
