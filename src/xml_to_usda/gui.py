from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .pipeline import convert_file


class ConversionApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Convert XML -> USDA")
        self.root.minsize(760, 480)

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.bark_material_var = tk.StringVar()
        self.leaves_material_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Single-file mode. Batch and naming rules will be added in a later phase.")

        self._build_layout()

    def _build_layout(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)

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

        ttk.Label(frame, textvariable=self.status_var).grid(row=4, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Button(frame, text="Convert", command=self.run_conversion).grid(row=4, column=2, sticky="ew", pady=(0, 12))

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(button_row, text="Copy Log", command=self.copy_log).pack(side="right")

        self.log_widget = tk.Text(frame, wrap="word", height=18)
        self.log_widget.grid(row=6, column=0, columnspan=3, sticky="nsew")
        self.log_widget.configure(state="disabled")
        self.log_widget.bind("<Control-c>", self._handle_copy_shortcut)
        self.log_widget.bind("<Control-C>", self._handle_copy_shortcut)

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
            result = convert_file(
                input_path,
                output_path,
                bark_material_path=bark_material_path or None,
                leaves_material_path=leaves_material_path or None,
            )
        except Exception as exc:
            self.status_var.set("Conversion failed.")
            self._set_log(str(exc))
            messagebox.showerror("Conversion failed", str(exc))
            return

        self._set_log(
            format_conversion_results(
                (result,),
                bark_material_path=bark_material_path or None,
                leaves_material_path=leaves_material_path or None,
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


def format_conversion_results(results, bark_material_path: str | None = None, leaves_material_path: str | None = None) -> str:
    lines: list[str] = []
    if bark_material_path or leaves_material_path:
        lines.append("Material overrides:")
        lines.append(f"  - bark: {bark_material_path or '<none>'}")
        lines.append(f"  - leaves: {leaves_material_path or '<none>'}")
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
