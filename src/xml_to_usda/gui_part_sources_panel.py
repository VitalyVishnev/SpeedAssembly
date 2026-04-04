from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import filedialog, ttk

from .asset_paths import is_valid_unreal_asset_path
from .discovery_service import discover_part_prototype_rows, inspect_fbx_material_slot_rows
from .gui_models import PartMaterialSlotRowUi, PartSourceRowUi
from .models import FbxMaterialMode, FbxMaterialSlotOverride, PrototypeSourceConfig, PrototypeSourceMode
from .settings_service import FbxMaterialSlotSettingRecord, PartSourceSettingRecord, resolve_input_settings_key


class PartSourcesPanelController:
    def __init__(
        self,
        *,
        summary_var: tk.StringVar,
        rows_container: ttk.Frame,
        refresh_scroll_region,
        on_persisted_field_change,
        cpu_profile_getter,
        inspect_fbx_material_slot_rows_fn=inspect_fbx_material_slot_rows,
    ) -> None:
        self.summary_var = summary_var
        self.rows_container = rows_container
        self._refresh_scroll_region = refresh_scroll_region
        self._on_persisted_field_change = on_persisted_field_change
        self._cpu_profile_getter = cpu_profile_getter
        self._inspect_fbx_material_slot_rows = inspect_fbx_material_slot_rows_fn
        self.rows: list[PartSourceRowUi] = []

    def clear(self) -> None:
        self.rows.clear()
        self.summary_var.set("Repeated branch analysis has not run yet.")
        for child in self.rows_container.winfo_children():
            child.destroy()
        ttk.Label(
            self.rows_container,
            text="Select an XML file to load part meshes.",
        ).grid(row=0, column=0, sticky="w")
        self._refresh_scroll_region()

    def refresh(
        self,
        input_path: str,
        *,
        persisted_records: tuple[PartSourceSettingRecord, ...] = (),
    ) -> str:
        resolved_key = resolve_input_settings_key(input_path)
        discovery = discover_part_prototype_rows(
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
                text="No repeated part meshes found in this XML.",
            ).grid(row=0, column=0, sticky="w")
            self._refresh_scroll_region()
            return

        self.summary_var.set(discovery.summary)
        self.rows_container.columnconfigure(0, weight=1)
        header = ttk.Frame(self.rows_container)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        for column, weight in ((0, 2), (1, 0), (2, 0), (3, 1), (4, 4), (5, 4), (6, 2), (7, 3), (8, 3), (9, 3), (10, 0)):
            header.columnconfigure(column, weight=weight)
        ttk.Label(header, text="XML Mesh").grid(row=0, column=0, sticky="w")
        ttk.Label(header, text="Mesh ID").grid(row=0, column=1, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Instances").grid(row=0, column=2, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Source Mode").grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Label(header, text="Unreal Object Path").grid(row=0, column=4, sticky="w", padx=(0, 12))
        ttk.Label(header, text="FBX File").grid(row=0, column=5, sticky="w")
        ttk.Label(header, text="Part Materials").grid(row=0, column=6, sticky="w", padx=(12, 12))
        ttk.Label(header, text="Single Material").grid(row=0, column=7, sticky="w")
        ttk.Label(header, text="Black Material").grid(row=0, column=8, sticky="w", padx=(12, 0))
        ttk.Label(header, text="White Material").grid(row=0, column=9, sticky="w", padx=(12, 0))

        row_index = 1
        for prototype in discovery.rows:
            row_frame = ttk.Frame(self.rows_container)
            row_frame.grid(row=row_index, column=0, sticky="ew", pady=(0, 6))
            for column, weight in ((0, 2), (3, 1), (4, 4), (5, 4), (6, 2), (7, 3), (8, 3), (9, 3)):
                row_frame.columnconfigure(column, weight=weight)

            mesh_id_text = f"Mesh_{prototype.source_mesh_id}" if prototype.source_mesh_id is not None else "<none>"
            display_name = prototype.source_name or prototype.source_key
            ttk.Label(row_frame, text=display_name).grid(row=0, column=0, sticky="w")
            ttk.Label(row_frame, text=mesh_id_text).grid(row=0, column=1, sticky="w", padx=(12, 12))
            ttk.Label(row_frame, text=str(prototype.instance_count)).grid(row=0, column=2, sticky="w", padx=(0, 12))

            source_mode_var = tk.StringVar(value=prototype.source_mode.value)
            use_unreal_var = tk.BooleanVar(value=prototype.source_mode == PrototypeSourceMode.UNREAL_ASSET)
            asset_var = tk.StringVar(value=prototype.unreal_asset_path)
            fbx_var = tk.StringVar(value=prototype.fbx_path)
            fbx_material_mode_var = tk.StringVar(value=prototype.fbx_material_mode.value)
            single_material_var = tk.StringVar(value=prototype.single_material_path)
            black_material_var = tk.StringVar(value=prototype.black_material_path)
            white_material_var = tk.StringVar(value=prototype.white_material_path)

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
                values=(
                    FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                    FbxMaterialMode.SINGLE_MATERIAL.value,
                    FbxMaterialMode.MATERIAL_SLOTS.value,
                ),
                width=18,
            )
            single_material_entry = ttk.Entry(row_frame, textvariable=single_material_var)
            black_material_entry = ttk.Entry(row_frame, textvariable=black_material_var)
            white_material_entry = ttk.Entry(row_frame, textvariable=white_material_var)
            browse_button = ttk.Button(
                row_frame,
                text="Browse...",
                command=lambda var=fbx_var: self.browse_part_fbx(var),
            )

            source_mode_combo.grid(row=0, column=3, sticky="ew", padx=(0, 12))
            asset_entry.grid(row=0, column=4, sticky="ew")
            fbx_entry.grid(row=0, column=5, sticky="ew", padx=(12, 8))
            fbx_material_mode_combo.grid(row=0, column=6, sticky="ew", padx=(0, 12))
            single_material_entry.grid(row=0, column=7, sticky="ew")
            black_material_entry.grid(row=0, column=8, sticky="ew", padx=(12, 0))
            white_material_entry.grid(row=0, column=9, sticky="ew", padx=(12, 12))
            browse_button.grid(row=0, column=10, sticky="ew")

            material_slot_container = ttk.Frame(row_frame)
            material_slot_container.grid(row=1, column=4, columnspan=7, sticky="ew", pady=(4, 0))
            material_slot_container.columnconfigure(1, weight=1)
            material_slot_placeholder = ttk.Label(
                material_slot_container,
                text="FBX material slots appear here when Material Slots mode is enabled.",
            )
            material_slot_placeholder.grid(row=0, column=0, sticky="w")

            row_ui = PartSourceRowUi(
                source_key=prototype.source_key,
                source_name=display_name,
                mesh_id=prototype.source_mesh_id,
                instance_count=prototype.instance_count,
                source_mode_var=source_mode_var,
                use_unreal_var=use_unreal_var,
                asset_var=asset_var,
                fbx_var=fbx_var,
                fbx_material_mode_var=fbx_material_mode_var,
                single_material_var=single_material_var,
                black_material_var=black_material_var,
                white_material_var=white_material_var,
                asset_entry=asset_entry,
                fbx_entry=fbx_entry,
                fbx_material_mode_combo=fbx_material_mode_combo,
                single_material_entry=single_material_entry,
                black_material_entry=black_material_entry,
                white_material_entry=white_material_entry,
                browse_button=browse_button,
                source_mode_combo=source_mode_combo,
                material_slot_container=material_slot_container,
                material_slot_placeholder=material_slot_placeholder,
                restored_slot_override_records=prototype.fbx_material_slot_overrides,
            )
            self.rows.append(row_ui)
            self.handle_part_source_mode_change(row_ui)

            asset_var.trace_add("write", self._on_persisted_field_change)
            fbx_var.trace_add("write", self._on_persisted_field_change)
            fbx_var.trace_add("write", lambda *_args, row=row_ui: self.handle_part_source_mode_change(row))
            fbx_material_mode_var.trace_add("write", self._on_persisted_field_change)
            single_material_var.trace_add("write", self._on_persisted_field_change)
            black_material_var.trace_add("write", self._on_persisted_field_change)
            white_material_var.trace_add("write", self._on_persisted_field_change)
            source_mode_var.trace_add("write", self._on_persisted_field_change)
            source_mode_var.trace_add(
                "write",
                lambda *_args, row=row_ui, unreal_var=use_unreal_var: self.handle_source_mode_trace(row, unreal_var),
            )
            fbx_material_mode_var.trace_add(
                "write",
                lambda *_args, row=row_ui: self.handle_part_source_mode_change(row),
            )
            use_unreal_var.trace_add(
                "write",
                lambda *_args, mode_var=source_mode_var, unreal_var=use_unreal_var: self.handle_legacy_unreal_toggle(
                    mode_var,
                    unreal_var,
                ),
            )
            row_index += 1

        self._refresh_scroll_region()

    def browse_part_fbx(self, target_var: tk.StringVar) -> None:
        selected = filedialog.askopenfilename(
            title="Select part FBX",
            filetypes=[("FBX files", "*.fbx"), ("JSON test payloads", "*.json"), ("All files", "*.*")],
        )
        if selected:
            target_var.set(selected)

    def handle_source_mode_trace(self, row: PartSourceRowUi, use_unreal_var: tk.BooleanVar) -> None:
        self.handle_part_source_mode_change(row)
        use_unreal_var.set(str(row.source_mode_var.get()) == PrototypeSourceMode.UNREAL_ASSET.value)

    def handle_legacy_unreal_toggle(self, source_mode_var: tk.StringVar, use_unreal_var: tk.BooleanVar) -> None:
        if bool(use_unreal_var.get()):
            source_mode_var.set(PrototypeSourceMode.UNREAL_ASSET.value)
        elif source_mode_var.get() == PrototypeSourceMode.UNREAL_ASSET.value:
            source_mode_var.set(PrototypeSourceMode.XML_MESH.value)

    def handle_part_source_mode_change(self, row: PartSourceRowUi) -> None:
        mode = PrototypeSourceMode(str(row.source_mode_var.get()))
        row.asset_entry.configure(state="normal" if mode == PrototypeSourceMode.UNREAL_ASSET else "disabled")
        fbx_state = "normal" if mode == PrototypeSourceMode.FBX_FILE else "disabled"
        row.fbx_entry.configure(state=fbx_state)
        row.browse_button.configure(state=fbx_state)

        if mode == PrototypeSourceMode.FBX_FILE:
            allowed_material_modes = (
                FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                FbxMaterialMode.SINGLE_MATERIAL.value,
                FbxMaterialMode.MATERIAL_SLOTS.value,
            )
        else:
            allowed_material_modes = (
                FbxMaterialMode.VERTEX_COLOR_SPLIT.value,
                FbxMaterialMode.SINGLE_MATERIAL.value,
            )
        row.fbx_material_mode_combo.configure(
            state="readonly" if mode != PrototypeSourceMode.UNREAL_ASSET else "disabled",
            values=allowed_material_modes,
        )
        if str(row.fbx_material_mode_var.get()) not in allowed_material_modes:
            row.fbx_material_mode_var.set(FbxMaterialMode.VERTEX_COLOR_SPLIT.value)

        material_controls_enabled = mode != PrototypeSourceMode.UNREAL_ASSET
        material_mode = FbxMaterialMode(str(row.fbx_material_mode_var.get()))
        row.single_material_entry.configure(
            state="normal" if material_controls_enabled and material_mode == FbxMaterialMode.SINGLE_MATERIAL else "disabled"
        )
        split_state = "normal" if material_controls_enabled and material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT else "disabled"
        row.black_material_entry.configure(state=split_state)
        row.white_material_entry.configure(state=split_state)
        self.refresh_part_row_material_slot_controls(row)

    def refresh_part_row_material_slot_controls(self, row: PartSourceRowUi) -> None:
        container = row.material_slot_container
        for child in container.winfo_children():
            child.destroy()
        row.material_slot_rows.clear()
        row.material_slot_placeholder = ttk.Label(
            container,
            text="FBX material slots appear here when Material Slots mode is enabled.",
        )
        mode = PrototypeSourceMode(str(row.source_mode_var.get()))
        material_mode = FbxMaterialMode(str(row.fbx_material_mode_var.get()))
        if mode != PrototypeSourceMode.FBX_FILE or material_mode != FbxMaterialMode.MATERIAL_SLOTS:
            container.grid_remove()
            return

        fbx_path = str(row.fbx_var.get()).strip()
        container.grid()
        if not fbx_path:
            row.material_slot_placeholder.configure(text="Choose an FBX file to inspect material slots.")
            row.material_slot_placeholder.grid(row=0, column=0, sticky="w")
            return
        try:
            slot_specs = self._inspect_fbx_material_slot_rows(
                fbx_path,
                cpu_profile=self._cpu_profile_getter(),
                persisted_records=row.restored_slot_override_records,
            )
        except Exception as exc:
            row.material_slot_placeholder.configure(text=f"FBX material slot analysis failed: {exc}")
            row.material_slot_placeholder.grid(row=0, column=0, sticky="w")
            return
        if not slot_specs:
            row.material_slot_placeholder.configure(text="No face-used FBX material slots were found in this file.")
            row.material_slot_placeholder.grid(row=0, column=0, sticky="w")
            return

        container.columnconfigure(1, weight=1)
        ttk.Label(container, text="FBX Material Slots").grid(row=0, column=0, sticky="w", pady=(0, 4))
        ttk.Label(container, text="Unreal Material Path").grid(row=0, column=1, sticky="w", pady=(0, 4))
        for slot_index, slot_spec in enumerate(slot_specs, start=1):
            path_var = tk.StringVar(value=slot_spec.ue_asset_path)
            path_var.trace_add("write", self._on_persisted_field_change)
            ttk.Label(
                container,
                text=f"{slot_spec.slot_name} ({slot_spec.face_count} faces)",
            ).grid(row=slot_index, column=0, sticky="w", padx=(0, 12), pady=(0, 4))
            entry = ttk.Entry(container, textvariable=path_var)
            entry.grid(row=slot_index, column=1, sticky="ew", pady=(0, 4))
            row.material_slot_rows.append(
                PartMaterialSlotRowUi(
                    slot_name=slot_spec.slot_name,
                    face_count=slot_spec.face_count,
                    path_var=path_var,
                    entry=entry,
                )
            )
        row.restored_slot_override_records = ()

    def collect_part_row_material_slot_overrides(
        self,
        row: PartSourceRowUi,
    ) -> tuple[FbxMaterialSlotOverride, ...]:
        overrides: list[FbxMaterialSlotOverride] = []
        for slot_row in row.material_slot_rows:
            slot_name = str(slot_row.slot_name).strip()
            ue_asset_path = str(slot_row.path_var.get()).strip() or None
            if not slot_name:
                continue
            overrides.append(FbxMaterialSlotOverride(slot_name=slot_name, ue_asset_path=ue_asset_path))
        return tuple(overrides)

    def collect_part_source_configs(self) -> tuple[PrototypeSourceConfig, ...]:
        if not self.rows:
            return ()

        configs: list[PrototypeSourceConfig] = []
        for row in self.rows:
            mode = PrototypeSourceMode(str(row.source_mode_var.get()))
            source_name = str(row.source_name)
            source_key = str(row.source_key)
            part_material_mode = FbxMaterialMode(str(row.fbx_material_mode_var.get()))
            single_material_path = str(row.single_material_var.get()).strip() or None
            black_material_path = str(row.black_material_var.get()).strip() or None
            white_material_path = str(row.white_material_var.get()).strip() or None
            material_slot_overrides = self.collect_part_row_material_slot_overrides(row)
            if mode == PrototypeSourceMode.XML_MESH:
                if (
                    part_material_mode != FbxMaterialMode.VERTEX_COLOR_SPLIT
                    or single_material_path
                    or black_material_path
                    or white_material_path
                ):
                    configs.append(
                        PrototypeSourceConfig(
                            source_key=source_key,
                            source_name=source_name,
                            mode=mode,
                            fbx_material_mode=part_material_mode,
                            single_material_path=single_material_path,
                            black_material_path=black_material_path,
                            white_material_path=white_material_path,
                        )
                    )
                continue
            if mode == PrototypeSourceMode.UNREAL_ASSET:
                asset_path = str(row.asset_var.get()).strip()
                if not asset_path:
                    continue
                if not is_valid_unreal_asset_path(asset_path):
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

            fbx_path = str(row.fbx_var.get()).strip()
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
                    fbx_material_mode=part_material_mode,
                    fbx_path=str(resolved),
                    single_material_path=single_material_path,
                    black_material_path=black_material_path,
                    white_material_path=white_material_path,
                    fbx_material_slot_overrides=material_slot_overrides,
                )
            )
        return tuple(configs)

    def collect_existing_part_overrides(self) -> tuple[bool, tuple[tuple[str, str], ...]]:
        configs = self.collect_part_source_configs()
        mappings = tuple(
            (config.source_name or config.source_key, config.asset_path or "")
            for config in configs
            if config.mode == PrototypeSourceMode.UNREAL_ASSET and config.asset_path
        )
        return bool(mappings), mappings

    def serialize_settings(self) -> tuple[PartSourceSettingRecord, ...]:
        if not self.rows:
            return ()
        serialized: list[PartSourceSettingRecord] = []
        for row in self.rows:
            source_mode = PrototypeSourceMode(str(row.source_mode_var.get()))
            use_unreal_reference = bool(row.use_unreal_var.get())
            asset_path = str(row.asset_var.get()).strip()
            fbx_path = str(row.fbx_var.get()).strip()
            fbx_material_mode = FbxMaterialMode(str(row.fbx_material_mode_var.get()))
            single_material_path = str(row.single_material_var.get()).strip()
            black_material_path = str(row.black_material_var.get()).strip()
            white_material_path = str(row.white_material_var.get()).strip()
            material_slot_overrides = self.collect_part_row_material_slot_overrides(row)
            if (
                source_mode == PrototypeSourceMode.XML_MESH
                and not use_unreal_reference
                and not asset_path
                and not fbx_path
                and fbx_material_mode == FbxMaterialMode.VERTEX_COLOR_SPLIT
                and not single_material_path
                and not black_material_path
                and not white_material_path
                and not material_slot_overrides
            ):
                continue
            if use_unreal_reference and source_mode != PrototypeSourceMode.UNREAL_ASSET:
                source_mode = PrototypeSourceMode.UNREAL_ASSET
            serialized.append(
                PartSourceSettingRecord(
                    source_name=str(row.source_name),
                    source_key=str(row.source_key),
                    source_mode=source_mode,
                    unreal_asset_path=asset_path,
                    fbx_path=fbx_path,
                    fbx_material_mode=fbx_material_mode,
                    single_material_path=single_material_path,
                    black_material_path=black_material_path,
                    white_material_path=white_material_path,
                    fbx_material_slot_overrides=tuple(
                        FbxMaterialSlotSettingRecord(
                            slot_name=override.slot_name,
                            ue_asset_path=override.ue_asset_path or "",
                        )
                        for override in material_slot_overrides
                    ),
                )
            )
        return tuple(serialized)
