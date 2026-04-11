from __future__ import annotations

import tkinter as tk

from .settings_service import GuiSettingsSnapshot


class GuiPersistenceController:
    def __init__(
        self,
        app,
        *,
        load_gui_settings,
        save_gui_settings,
    ) -> None:
        self.app = app
        self._load_gui_settings = load_gui_settings
        self._save_gui_settings = save_gui_settings

    def load_settings(self) -> None:
        settings = self._load_gui_settings(self.app.SETTINGS_PATH)
        self.app._startup_restored_input_path = settings.last_input_path
        self.app.input_var.set(self.app._startup_restored_input_path)
        self.app.output_var.set(settings.last_output_path)
        self.app.cpu_profile_var.set(settings.cpu_profile.value)
        self.app.preserve_temp_files_var.set(bool(settings.preserve_temp_files))
        self.app._persisted_conversion_mode = settings.conversion_mode
        self.app.material_policy_var.set(settings.material_policy.value)
        self.app.bark_material_var.set(settings.bark_material_path)
        self.app.leaves_material_var.set(settings.leaves_material_path)
        self.app.single_material_var.set(settings.single_material_path)
        self.app.gust_attenuation_var.set(float(settings.gust_attenuation))
        self.app.is_ground_cover_var.set(bool(settings.is_ground_cover))
        self.app._legacy_wind_group_settings = dict(settings.wind_group_settings)
        self.app._persisted_wind_group_settings = dict(self.app._legacy_wind_group_settings)
        self.app._persisted_wind_group_settings_by_input_path = dict(settings.wind_group_settings_by_input_path)
        self.app._persisted_base_material_settings_by_input_path = dict(settings.base_material_settings_by_input_path)
        self.app._persisted_part_mesh_settings_by_input_path = dict(settings.part_mesh_settings_by_input_path)

    def save_settings(self) -> None:
        try:
            if self.app._pending_settings_save_job is not None:
                try:
                    self.app.root.after_cancel(self.app._pending_settings_save_job)
                except tk.TclError:
                    pass
                self.app._pending_settings_save_job = None

            base_material_settings_by_input_path = dict(self.app._persisted_base_material_settings_by_input_path)
            part_mesh_settings_by_input_path = dict(self.app._persisted_part_mesh_settings_by_input_path)
            wind_group_settings_by_input_path = dict(self.app._persisted_wind_group_settings_by_input_path)

            current_base_material_settings = self.app._materials_panel.serialize_settings()
            current_part_mesh_settings = self.app._part_sources_panel.serialize_settings()
            current_wind_group_settings = self.app._wind_panel.serialize_settings()

            if self.app._current_base_material_settings_key is not None:
                if current_base_material_settings:
                    base_material_settings_by_input_path[self.app._current_base_material_settings_key] = current_base_material_settings
                else:
                    base_material_settings_by_input_path.pop(self.app._current_base_material_settings_key, None)
            if self.app._current_part_mesh_settings_key is not None:
                if current_part_mesh_settings:
                    part_mesh_settings_by_input_path[self.app._current_part_mesh_settings_key] = current_part_mesh_settings
                else:
                    part_mesh_settings_by_input_path.pop(self.app._current_part_mesh_settings_key, None)
            if self.app._current_wind_settings_key is not None:
                if current_wind_group_settings:
                    wind_group_settings_by_input_path[self.app._current_wind_settings_key] = current_wind_group_settings
                else:
                    wind_group_settings_by_input_path.pop(self.app._current_wind_settings_key, None)

            self._save_gui_settings(
                self.app.SETTINGS_PATH,
                GuiSettingsSnapshot(
                    last_input_path=self.app.input_var.get().strip(),
                    last_output_path=self.app.output_var.get().strip(),
                    cpu_profile=self.app._current_cpu_profile(),
                    preserve_temp_files=bool(self.app.preserve_temp_files_var.get()),
                    conversion_mode=self.app._persisted_conversion_mode,
                    material_policy=self.app._current_material_policy(),
                    bark_material_path=self.app.bark_material_var.get().strip(),
                    leaves_material_path=self.app.leaves_material_var.get().strip(),
                    single_material_path=self.app.single_material_var.get().strip(),
                    gust_attenuation=float(self.app.gust_attenuation_var.get()),
                    is_ground_cover=bool(self.app.is_ground_cover_var.get()),
                    wind_group_settings=current_wind_group_settings,
                    wind_group_settings_by_input_path=wind_group_settings_by_input_path,
                    base_material_settings_by_input_path=base_material_settings_by_input_path,
                    part_mesh_settings_by_input_path=part_mesh_settings_by_input_path,
                ),
            )
            self.app._persisted_base_material_settings_by_input_path = base_material_settings_by_input_path
            self.app._persisted_part_mesh_settings_by_input_path = part_mesh_settings_by_input_path
            self.app._persisted_wind_group_settings_by_input_path = wind_group_settings_by_input_path
        except OSError:
            return

    def schedule_settings_save(self) -> None:
        if self.app._suspend_settings_save:
            return
        if self.app._pending_settings_save_job is not None:
            try:
                self.app.root.after_cancel(self.app._pending_settings_save_job)
            except tk.TclError:
                pass
        self.app._pending_settings_save_job = self.app.root.after(150, self.flush_scheduled_settings_save)

    def flush_scheduled_settings_save(self) -> None:
        self.app._pending_settings_save_job = None
        self.save_settings()

    def resolve_persisted_wind_settings_for_key(self, settings_key: str):
        if settings_key in self.app._persisted_wind_group_settings_by_input_path:
            return dict(self.app._persisted_wind_group_settings_by_input_path[settings_key])
        if not self.app._persisted_wind_group_settings_by_input_path:
            return dict(self.app._legacy_wind_group_settings)
        return {}
