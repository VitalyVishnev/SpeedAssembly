from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .discovery_service import discover_base_material_rows
from .gui_models import BaseMaterialRowUi
from .models import BaseMaterialOverride
from .settings_service import BaseMaterialSettingRecord, resolve_input_settings_key


class MaterialsPanelController:
    def __init__(
        self,
        *,
        summary_var: tk.StringVar,
        rows_container: ttk.Frame,
        refresh_scroll_region,
        on_persisted_field_change,
    ) -> None:
        self.summary_var = summary_var
        self.rows_container = rows_container
        self._refresh_scroll_region = refresh_scroll_region
        self._on_persisted_field_change = on_persisted_field_change
        self.rows: list[BaseMaterialRowUi] = []

    def clear(self) -> None:
        self.rows.clear()
        self.summary_var.set("Base XML material analysis has not run yet.")
        for child in self.rows_container.winfo_children():
            child.destroy()
        ttk.Label(
            self.rows_container,
            text="Select an XML file to load base XML materials.",
        ).grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def refresh(
        self,
        input_path: str,
        *,
        persisted_records: tuple[BaseMaterialSettingRecord, ...] = (),
    ) -> str:
        resolved_key = resolve_input_settings_key(input_path)
        discovery = discover_base_material_rows(
            input_path,
            persisted_records=persisted_records,
        )
        self.rebuild(discovery)
        return resolved_key

    def rebuild(self, discovery) -> None:
        for child in self.rows_container.winfo_children():
            child.destroy()
        self.rows.clear()

        if not discovery.rows:
            self.summary_var.set(discovery.summary)
            ttk.Label(
                self.rows_container,
                text="No XML material slots found in this XML.",
            ).grid(row=0, column=0, sticky="w")
            self._refresh_scroll_region()
            return

        self.summary_var.set(discovery.summary)
        self.rows_container.columnconfigure(0, weight=1)
        header = ttk.Frame(self.rows_container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        header.columnconfigure(2, weight=1)
        ttk.Label(header, text="XML Material").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Unreal Material Path").grid(row=0, column=2, sticky="w")

        for row_index, material in enumerate(discovery.rows, start=1):
            row_frame = ttk.Frame(self.rows_container)
            row_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 6))
            row_frame.columnconfigure(2, weight=1)
            ttk.Label(
                row_frame,
                text=material.source_name or f"Material_{material.source_id}",
            ).grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=str(material.source_id)).grid(row=0, column=1, sticky="w", padx=(12, 12))
            material_path_var = tk.StringVar(value=material.ue_asset_path)
            entry = ttk.Entry(row_frame, textvariable=material_path_var)
            entry.grid(row=0, column=2, sticky="ew")
            material_path_var.trace_add("write", self._on_persisted_field_change)
            self.rows.append(
                BaseMaterialRowUi(
                    source_id=material.source_id,
                    source_name=material.source_name,
                    material_path_var=material_path_var,
                    entry=entry,
                )
            )
        self._refresh_scroll_region()

    def collect_overrides(self) -> tuple[BaseMaterialOverride, ...]:
        if not self.rows:
            return ()
        return tuple(
            BaseMaterialOverride(
                source_id=int(row.source_id),
                source_name=str(row.source_name),
                ue_asset_path=str(row.material_path_var.get()).strip() or None,
            )
            for row in self.rows
        )

    def serialize_settings(self) -> tuple[BaseMaterialSettingRecord, ...]:
        if not self.rows:
            return ()
        serialized: list[BaseMaterialSettingRecord] = []
        for row in self.rows:
            ue_asset_path = str(row.material_path_var.get()).strip()
            if not ue_asset_path:
                continue
            serialized.append(
                BaseMaterialSettingRecord(
                    source_id=int(row.source_id),
                    source_name=str(row.source_name),
                    ue_asset_path=ue_asset_path,
                )
            )
        return tuple(serialized)
