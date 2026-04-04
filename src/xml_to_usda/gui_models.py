from __future__ import annotations

from dataclasses import dataclass, field
import tkinter as tk
from tkinter import ttk

from .settings_service import FbxMaterialSlotSettingRecord


class CompatUiState:
    def __getitem__(self, key: str):
        return getattr(self, key)

    def __setitem__(self, key: str, value) -> None:
        setattr(self, key, value)

    def get(self, key: str, default=None):
        return getattr(self, key, default)


@dataclass
class SectionUiState(CompatUiState):
    container: ttk.Frame
    content: ttk.Frame
    button_text: tk.StringVar
    title: str
    expanded: tk.BooleanVar


@dataclass
class BaseMaterialRowUi(CompatUiState):
    source_id: int
    source_name: str
    material_path_var: tk.StringVar
    entry: ttk.Entry


@dataclass
class PartMaterialSlotRowUi(CompatUiState):
    slot_name: str
    face_count: int
    path_var: tk.StringVar
    entry: ttk.Entry


@dataclass
class PartSourceRowUi(CompatUiState):
    source_key: str
    source_name: str
    mesh_id: int | None
    instance_count: int
    source_mode_var: tk.StringVar
    use_unreal_var: tk.BooleanVar
    asset_var: tk.StringVar
    fbx_var: tk.StringVar
    fbx_material_mode_var: tk.StringVar
    single_material_var: tk.StringVar
    black_material_var: tk.StringVar
    white_material_var: tk.StringVar
    asset_entry: ttk.Entry
    fbx_entry: ttk.Entry
    fbx_material_mode_combo: ttk.Combobox
    single_material_entry: ttk.Entry
    black_material_entry: ttk.Entry
    white_material_entry: ttk.Entry
    browse_button: ttk.Button
    source_mode_combo: ttk.Combobox
    material_slot_container: ttk.Frame
    material_slot_placeholder: ttk.Label
    material_slot_rows: list[PartMaterialSlotRowUi] = field(default_factory=list)
    restored_slot_override_records: tuple[FbxMaterialSlotSettingRecord, ...] = ()


@dataclass
class WindGroupRowUi(CompatUiState):
    group_index: int
    branch_order: int
    is_trunk_group: bool
    influence_var: tk.DoubleVar
    shift_var: tk.DoubleVar
    dual_influence_var: tk.BooleanVar
    min_influence_var: tk.DoubleVar
    max_influence_var: tk.DoubleVar
    single_frame: ttk.Frame
    dual_frame: ttk.Frame
