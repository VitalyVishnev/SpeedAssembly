from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .pipeline import convert_file


class ConversionApp:
    SETTINGS_DIR = Path.home() / ".xml_to_usda"
    SETTINGS_PATH = SETTINGS_DIR / "gui_settings.json"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convert XML -> USDA")
        self.root.minsize(760, 480)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.bark_material_var = tk.StringVar()
        self.leaves_material_var = tk.StringVar()
        self.use_existing_part_meshes_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Single-file mode. Batch and naming rules will be added in a later phase.")
        self._load_settings()

        self._build_layout()
        self._install_persistence_hooks()

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(9, weight=1)

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

        ttk.Label(frame, textvariable=self.status_var).grid(row=7, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Button(frame, text="Convert", command=self.run_conversion).grid(row=7, column=2, sticky="ew", pady=(0, 12))

        button_row = ttk.Frame(frame)
        button_row.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(button_row, text="Copy Log", command=self.copy_log).pack(side="right")

        self.log_widget = tk.Text(frame, wrap="word", height=18)
        self.log_widget.grid(row=9, column=0, columnspan=3, sticky="nsew")
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
        self.root.protocol("WM_DELETE_WINDOW", self._handle_window_close)

    def _handle_persisted_field_change(self, *_args) -> None:
        self._save_settings()

    def _handle_window_close(self) -> None:
        self._save_settings()
        self.root.destroy()

    def _load_settings(self) -> None:
        settings = self._read_settings()
        self.bark_material_var.set(settings.get("bark_material_path", ""))
        self.leaves_material_var.set(settings.get("leaves_material_path", ""))

    def _read_settings(self) -> dict[str, str]:
        if not self.SETTINGS_PATH.exists():
            return {}
        try:
            payload = json.loads(self.SETTINGS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return {
            key: value
            for key, value in payload.items()
            if key in {"bark_material_path", "leaves_material_path"} and isinstance(value, str)
        }

    def _save_settings(self) -> None:
        try:
            self.SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
            payload = {
                "bark_material_path": self.bark_material_var.get().strip(),
                "leaves_material_path": self.leaves_material_var.get().strip(),
            }
            self.SETTINGS_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:
            # Persistence must not block the GUI or conversion flow.
            return


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


def _is_valid_unreal_asset_path(path: str) -> bool:
    return path.startswith("/Game/")


def main() -> int:
    root = tk.Tk()
    ConversionApp(root)
    root.mainloop()
    return 0
