from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .discovery_service import discover_base_material_rows
from .gui_models import BaseMaterialRowUi
from .models import BaseMaterialOverride, UdimMaterialSetting, UdimMode
from .settings_service import BaseMaterialSettingRecord, resolve_input_settings_key


UDIM_MODE_VALUES = tuple(mode.value for mode in UdimMode)


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
        ttk.Label(header, text="UDIM Mode").grid(row=0, column=3, sticky="w", padx=(12, 12))
        ttk.Label(header, text="UDIM ID").grid(row=0, column=4, sticky="w")

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
            udim_mode_var = tk.StringVar(value=material.udim_mode.value)
            udim_id_var = tk.IntVar(value=material.udim_id)
            entry = ttk.Entry(row_frame, textvariable=material_path_var)
            entry.grid(row=0, column=2, sticky="ew")
            udim_mode_combo = ttk.Combobox(
                row_frame,
                textvariable=udim_mode_var,
                values=UDIM_MODE_VALUES,
                state="readonly",
                width=24,
            )
            udim_mode_combo.grid(row=0, column=3, sticky="ew", padx=(12, 12))
            udim_id_spin = ttk.Spinbox(row_frame, from_=1001, to=1999, textvariable=udim_id_var, width=8)
            udim_id_spin.grid(row=0, column=4, sticky="w")
            material_path_var.trace_add("write", self._on_persisted_field_change)
            udim_mode_var.trace_add("write", self._on_persisted_field_change)
            udim_id_var.trace_add("write", self._on_persisted_field_change)
            self.rows.append(
                BaseMaterialRowUi(
                    source_id=material.source_id,
                    source_name=material.source_name,
                    material_path_var=material_path_var,
                    udim_mode_var=udim_mode_var,
                    udim_id_var=udim_id_var,
                    entry=entry,
                    udim_mode_combo=udim_mode_combo,
                    udim_id_spin=udim_id_spin,
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

    def collect_udim_material_settings(self) -> tuple[UdimMaterialSetting, ...]:
        if not self.rows:
            return ()
        settings: list[UdimMaterialSetting] = []
        for row in self.rows:
            mode = UdimMode.parse(row.udim_mode_var.get())
            if mode == UdimMode.OFF:
                continue
            settings.append(
                UdimMaterialSetting(
                    material_id=int(row.source_id),
                    mode=mode,
                    udim_id=int(row.udim_id_var.get()),
                )
            )
        return tuple(settings)

    def serialize_settings(self) -> tuple[BaseMaterialSettingRecord, ...]:
        if not self.rows:
            return ()
        serialized: list[BaseMaterialSettingRecord] = []
        for row in self.rows:
            ue_asset_path = str(row.material_path_var.get()).strip()
            udim_mode = UdimMode.parse(row.udim_mode_var.get())
            udim_id = int(row.udim_id_var.get())
            if not ue_asset_path and udim_mode == UdimMode.OFF:
                continue
            serialized.append(
                BaseMaterialSettingRecord(
                    source_id=int(row.source_id),
                    source_name=str(row.source_name),
                    ue_asset_path=ue_asset_path,
                    udim_mode=udim_mode,
                    udim_id=udim_id,
                )
            )
        return tuple(serialized)
