from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .models import DynamicWindSimulationGroup
from .pipeline import convert_file, generate_wind_json, inspect_wind_data


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
        self._wind_group_rows: list[dict[str, object]] = []
        self._persisted_wind_group_settings: dict[str, dict[str, float]] = {}
        self._load_settings()

        self._build_layout()
        self._install_persistence_hooks()

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(11, weight=1)

        ttk.Label(frame, text="Source XML").grid(row=0, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Button(frame, text="Browse...", command=self.browse_input).grid(row=0, column=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Output USDA").grid(row=1, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Button(frame, text="Save As...", command=self.browse_output).grid(row=1, column=2, sticky="ew", pady=(0, 8))

        ttk.Label(frame, text="Bark Material Path").grid(row=2, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.bark_material_var).grid(row=2, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))

        ttk.Label(frame, text="Leaves Material Path").grid(row=3, column=0, sticky="w", pady=(0, 8))
        ttk.Entry(frame, textvariable=self.leaves_material_var).grid(row=3, column=1, sticky="ew", padx=(12, 12), pady=(0, 8))

        ttk.Checkbutton(
            frame,
            text="Use Existing PartMeshes",
            variable=self.use_existing_part_meshes_var,
            command=self._toggle_part_mesh_mapping_state,
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(frame, text="PartMesh Asset Mappings").grid(row=5, column=0, sticky="nw", pady=(0, 8))
        self.part_mesh_mapping_widget = tk.Text(frame, wrap="word", height=4)
        self.part_mesh_mapping_widget.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=(0, 8))

        ttk.Label(
            frame,
            text="One mapping per line. Supported keys: Mesh_1, 1, meshid:1.",
        ).grid(row=6, column=1, columnspan=2, sticky="w", pady=(0, 8))

        self.wind_frame = ttk.LabelFrame(frame, text="Wind Profile", padding=12)
        self.wind_frame.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(4, 12))
        self.wind_frame.columnconfigure(1, weight=1)
        self.wind_frame.columnconfigure(3, weight=1)

        ttk.Button(self.wind_frame, text="Refresh Wind Groups", command=self.refresh_wind_groups).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        ttk.Checkbutton(
            self.wind_frame,
            text="Ground Cover",
            variable=self.is_ground_cover_var,
        ).grid(row=0, column=1, sticky="w", padx=(12, 0), pady=(0, 8))

        ttk.Label(self.wind_frame, text="Gust Attenuation").grid(row=1, column=0, sticky="w", pady=(0, 8))
        self.gust_value_var = tk.StringVar(value=f"{self.gust_attenuation_var.get():.2f}")
        tk.Scale(
            self.wind_frame,
            from_=0.0,
            to=5.0,
            resolution=0.05,
            orient="horizontal",
            variable=self.gust_attenuation_var,
            command=lambda value: self._handle_gust_change(float(value)),
        ).grid(row=1, column=1, columnspan=2, sticky="ew", padx=(12, 12), pady=(0, 8))
        ttk.Label(self.wind_frame, textvariable=self.gust_value_var, width=6).grid(row=1, column=3, sticky="e", pady=(0, 8))

        ttk.Label(
            self.wind_frame,
            text="Group sliders are built from the normalized skeleton hierarchy. Trunk = Group 0.",
        ).grid(row=2, column=0, columnspan=4, sticky="w", pady=(0, 8))

        self.wind_groups_container = ttk.Frame(self.wind_frame)
        self.wind_groups_container.grid(row=3, column=0, columnspan=4, sticky="ew")
        self.wind_groups_container.columnconfigure(1, weight=1)
        self.wind_groups_container.columnconfigure(3, weight=1)

        ttk.Label(frame, textvariable=self.status_var).grid(row=8, column=0, columnspan=2, sticky="w", pady=(0, 12))
        action_row = ttk.Frame(frame)
        action_row.grid(row=8, column=2, sticky="e", pady=(0, 12))
        ttk.Button(action_row, text="Generate Wind JSON", command=self.run_generate_wind_json).pack(side="right")
        ttk.Button(action_row, text="Convert", command=self.run_conversion).pack(side="right", padx=(0, 8))

        button_row = ttk.Frame(frame)
        button_row.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(button_row, text="Copy Log", command=self.copy_log).pack(side="right")

        self.log_widget = tk.Text(frame, wrap="word", height=18)
        self.log_widget.grid(row=11, column=0, columnspan=3, sticky="nsew")
        self.log_widget.configure(state="disabled")
        self.log_widget.bind("<Control-c>", self._handle_copy_shortcut)
        self.log_widget.bind("<Control-C>", self._handle_copy_shortcut)
        self._toggle_part_mesh_mapping_state()

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
            dynamic_wind = inspect_wind_data(input_path)
        except Exception as exc:
            self.status_var.set("Wind group inspection failed.")
            self._set_log(str(exc))
            messagebox.showerror("Wind group inspection failed", str(exc))
            return

        self._rebuild_wind_group_controls(dynamic_wind.simulation_groups)
        self.status_var.set(
            f"Loaded {len(dynamic_wind.simulation_groups)} wind groups from skeleton hierarchy."
        )
        self._set_log(format_wind_group_summary(dynamic_wind))

    def run_conversion(self) -> None:
        input_path = self.input_var.get().strip()
        output_path = self.output_var.get().strip()
        bark_material_path = self.bark_material_var.get().strip()
        leaves_material_path = self.leaves_material_var.get().strip()
        use_existing_part_meshes = bool(self.use_existing_part_meshes_var.get())
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
            part_mesh_asset_paths = self._parse_part_mesh_asset_paths(use_existing_part_meshes)
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

    def _parse_part_mesh_asset_paths(self, use_existing_part_meshes: bool) -> tuple[tuple[str, str], ...]:
        if not use_existing_part_meshes:
            return ()

        mappings: list[tuple[str, str]] = []
        raw_text = self.part_mesh_mapping_widget.get("1.0", "end-1c")
        for line_number, raw_line in enumerate(raw_text.splitlines(), start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                raise ValueError(f"PartMesh mapping line {line_number} must use KEY=/Game/... format.")
            source_key, asset_path = (segment.strip() for segment in line.split("=", 1))
            if not source_key:
                raise ValueError(f"PartMesh mapping line {line_number} is missing a prototype key.")
            if not _is_valid_unreal_asset_path(asset_path):
                raise ValueError(f"PartMesh asset path on line {line_number} must start with /Game/.")
            mappings.append((source_key, asset_path))
        return tuple(mappings)

    def _toggle_part_mesh_mapping_state(self) -> None:
        state = "normal" if self.use_existing_part_meshes_var.get() else "disabled"
        self.part_mesh_mapping_widget.configure(state=state)

    def _install_persistence_hooks(self) -> None:
        self.bark_material_var.trace_add("write", self._handle_persisted_field_change)
        self.leaves_material_var.trace_add("write", self._handle_persisted_field_change)
        self.gust_attenuation_var.trace_add("write", self._handle_persisted_field_change)
        self.is_ground_cover_var.trace_add("write", self._handle_persisted_field_change)
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close)

    def _handle_persisted_field_change(self, *_args) -> None:
        self._save_settings()

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
        }

    def _save_settings(self) -> None:
        try:
            self.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "bark_material_path": self.bark_material_var.get().strip(),
                "leaves_material_path": self.leaves_material_var.get().strip(),
                "gust_attenuation": round(float(self.gust_attenuation_var.get()), 4),
                "is_ground_cover": bool(self.is_ground_cover_var.get()),
                "wind_group_settings": self._serialize_wind_group_settings(),
            }
            self.SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            return

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
            title = f"Group {group.group_index} ({'Trunk' if group.is_trunk_group else f'Branch Level {group.branch_order}'})"
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
        label = "Trunk" if group.is_trunk_group else f"Branch level {group.branch_order}"
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
            f"Group {group.group_index}: influence={group.influence:.2f}, shiftTop={group.shift_top:.2f}, trunk={group.is_trunk_group}"
        )
    return "\n".join(lines)


def _is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def main() -> int:
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0
