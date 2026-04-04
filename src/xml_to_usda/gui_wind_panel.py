from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .gui_models import WindGroupRowUi
from .models import DynamicWindSimulationGroup
from .settings_service import WindGroupSettingRecord


class WindPanelController:
    def __init__(
        self,
        *,
        container: ttk.Frame,
        max_wind_influence: float,
        max_shift_top: float,
        schedule_settings_save,
    ) -> None:
        self.container = container
        self.max_wind_influence = max_wind_influence
        self.max_shift_top = max_shift_top
        self._schedule_settings_save = schedule_settings_save
        self.rows: list[WindGroupRowUi] = []
        self.persisted_settings: dict[str, WindGroupSettingRecord] = {}

    def set_persisted_settings(self, settings: dict[str, WindGroupSettingRecord]) -> None:
        self.persisted_settings = dict(settings)

    def clear(self, message: str = "Click Refresh Wind Groups to inspect wind settings.") -> None:
        for child in self.container.winfo_children():
            child.destroy()
        self.rows.clear()
        ttk.Label(self.container, text=message).grid(row=0, column=0, sticky="w")

    def rebuild(self, groups: tuple[DynamicWindSimulationGroup, ...]) -> None:
        for child in self.container.winfo_children():
            child.destroy()
        self.rows.clear()

        if not groups:
            ttk.Label(self.container, text="No skeleton joints found.").grid(row=0, column=0, sticky="w")
            return

        for row_index, group in enumerate(groups):
            group_frame = ttk.Frame(self.container, padding=(0, 6, 0, 10))
            group_frame.grid(row=row_index, column=0, sticky="ew")
            group_frame.columnconfigure(0, weight=1)
            group_frame.columnconfigure(1, weight=1)

            header = ttk.Frame(group_frame)
            header.grid(row=0, column=0, columnspan=2, sticky="ew")
            header.columnconfigure(0, weight=1)

            title = f"Group {group.group_index} ({'Trunk' if group.is_trunk_group else f'Generator level {group.branch_order}'})"
            ttk.Label(header, text=title).grid(row=0, column=0, sticky="w")

            dual_influence_var = tk.BooleanVar(
                value=self.persisted_group_bool(group.group_index, "use_dual_influence", group.use_dual_influence)
            )
            ttk.Checkbutton(header, text="Dual Influence", variable=dual_influence_var).grid(row=0, column=1, sticky="e")

            single_frame = ttk.Frame(group_frame)
            single_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            single_frame.columnconfigure(1, weight=1)
            influence_var = tk.DoubleVar(value=self.persisted_group_value(group.group_index, "influence", group.influence))
            influence_value_var = tk.StringVar(value=f"{influence_var.get():.2f}")
            influence_scale = tk.Scale(
                single_frame,
                from_=0.0,
                to=self.max_wind_influence,
                resolution=0.05,
                orient="horizontal",
                variable=influence_var,
                command=lambda value, value_var=influence_value_var: self.handle_scale_change(value, value_var),
            )
            ttk.Label(single_frame, text="Influence").grid(row=0, column=0, sticky="w")
            influence_scale.grid(row=0, column=1, sticky="ew", padx=(12, 12))
            ttk.Label(single_frame, textvariable=influence_value_var, width=6).grid(row=0, column=2, sticky="e")

            dual_frame = ttk.Frame(group_frame)
            dual_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            dual_frame.columnconfigure(1, weight=1)
            min_influence_var = tk.DoubleVar(
                value=self.persisted_group_value(group.group_index, "min_influence", group.min_influence)
            )
            min_influence_value_var = tk.StringVar(value=f"{min_influence_var.get():.2f}")
            min_influence_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.max_wind_influence,
                resolution=0.01,
                orient="horizontal",
                variable=min_influence_var,
                command=lambda value, value_var=min_influence_value_var: self.handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Min Influence").grid(row=0, column=0, sticky="w")
            min_influence_scale.grid(row=0, column=1, sticky="ew", padx=(12, 12))
            ttk.Label(dual_frame, textvariable=min_influence_value_var, width=6).grid(row=0, column=2, sticky="e")

            max_influence_default = self.persisted_group_value(
                group.group_index,
                "max_influence",
                group.max_influence if group.max_influence else influence_var.get(),
            )
            max_influence_var = tk.DoubleVar(value=max_influence_default)
            max_influence_value_var = tk.StringVar(value=f"{max_influence_var.get():.2f}")
            max_influence_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.max_wind_influence,
                resolution=0.01,
                orient="horizontal",
                variable=max_influence_var,
                command=lambda value, value_var=max_influence_value_var: self.handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Max Influence").grid(row=1, column=0, sticky="w")
            max_influence_scale.grid(row=1, column=1, sticky="ew", padx=(12, 12), pady=(6, 0))
            ttk.Label(dual_frame, textvariable=max_influence_value_var, width=6).grid(
                row=1, column=2, sticky="e", pady=(6, 0)
            )

            shift_var = tk.DoubleVar(
                value=self.persisted_group_value(group.group_index, "shift_top", group.shift_top)
            )
            shift_value_var = tk.StringVar(value=f"{shift_var.get():.2f}")
            shift_scale = tk.Scale(
                dual_frame,
                from_=0.0,
                to=self.max_shift_top,
                resolution=0.01,
                orient="horizontal",
                variable=shift_var,
                command=lambda value, value_var=shift_value_var: self.handle_scale_change(value, value_var),
            )
            ttk.Label(dual_frame, text="Shift Top").grid(row=2, column=0, sticky="w")
            shift_scale.grid(row=2, column=1, sticky="ew", padx=(12, 12), pady=(6, 0))
            ttk.Label(dual_frame, textvariable=shift_value_var, width=6).grid(row=2, column=2, sticky="e", pady=(6, 0))

            row_ui = WindGroupRowUi(
                group_index=group.group_index,
                branch_order=group.branch_order,
                is_trunk_group=group.is_trunk_group,
                influence_var=influence_var,
                shift_var=shift_var,
                dual_influence_var=dual_influence_var,
                min_influence_var=min_influence_var,
                max_influence_var=max_influence_var,
                single_frame=single_frame,
                dual_frame=dual_frame,
            )
            self.rows.append(row_ui)
            dual_influence_var.trace_add("write", lambda *_args, row=row_ui: self.handle_wind_group_mode_change(row))
            self.apply_wind_group_mode(row_ui)

    def persisted_group_value(self, group_index: int, field_name: str, default: float) -> float:
        persisted = self.persisted_settings.get(str(group_index))
        value = getattr(persisted, field_name, default)
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return default
        maximum = self.max_shift_top if field_name == "shift_top" else self.max_wind_influence
        return max(0.0, min(numeric_value, maximum))

    def persisted_group_bool(self, group_index: int, field_name: str, default: bool) -> bool:
        persisted = self.persisted_settings.get(str(group_index))
        value = getattr(persisted, field_name, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        return bool(value)

    def handle_wind_group_mode_change(self, row: WindGroupRowUi) -> None:
        self.apply_wind_group_mode(row)
        self._schedule_settings_save()

    def apply_wind_group_mode(self, row: WindGroupRowUi) -> None:
        dual_influence = bool(row.dual_influence_var.get())
        self.set_frame_visible(row.single_frame, not dual_influence)
        self.set_frame_visible(row.dual_frame, dual_influence)

    @staticmethod
    def set_frame_visible(frame: ttk.Frame, visible: bool) -> None:
        if visible:
            frame.grid()
        else:
            frame.grid_remove()

    def collect_group_settings(self) -> tuple[DynamicWindSimulationGroup, ...]:
        return tuple(
            DynamicWindSimulationGroup(
                group_index=int(row.group_index),
                branch_order=int(row.branch_order),
                influence=float(row.influence_var.get()),
                shift_top=float(row.shift_var.get()),
                is_trunk_group=bool(row.is_trunk_group),
                use_dual_influence=bool(row.dual_influence_var.get()),
                min_influence=float(row.min_influence_var.get()),
                max_influence=float(row.max_influence_var.get()),
            )
            for row in self.rows
        )

    def serialize_settings(self) -> dict[str, WindGroupSettingRecord]:
        if not self.rows:
            return dict(self.persisted_settings)
        serialized: dict[str, WindGroupSettingRecord] = {}
        for row in self.rows:
            serialized[str(row.group_index)] = WindGroupSettingRecord(
                use_dual_influence=bool(row.dual_influence_var.get()),
                influence=float(row.influence_var.get()),
                min_influence=float(row.min_influence_var.get()),
                max_influence=float(row.max_influence_var.get()),
                shift_top=float(row.shift_var.get()),
            )
        self.persisted_settings = dict(serialized)
        return serialized

    def handle_scale_change(self, value: str, value_var: tk.StringVar) -> None:
        value_var.set(f"{float(value):.2f}")
        self._schedule_settings_save()
