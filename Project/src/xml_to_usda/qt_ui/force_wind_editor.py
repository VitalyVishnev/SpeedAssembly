"""Shared Force Based group controls for the main and advanced Wind panels."""

from dataclasses import replace
from typing import Callable

from PySide6.QtWidgets import QCheckBox, QFrame, QLabel, QVBoxLayout

from ..wind_profiles import FORCE_PARAMETERS, ForceWindSettings


class ForceWindEditor(QFrame):
    def __init__(self, settings: ForceWindSettings, on_change: Callable[[ForceWindSettings], None], parent=None):
        from .panels import SliderSpinEditor

        super().__init__(parent)
        self._settings = settings
        self._on_change = on_change
        self.editors = {}
        self.overrides = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.trunk = QCheckBox("Trunk", self)
        self.trunk.setChecked(settings.is_trunk_group)
        self.trunk.setToolTip("Uses trunk taper and trunk physics defaults. Off uses branch physics.")
        layout.addWidget(self.trunk)
        self.trunk.toggled.connect(lambda value: self._set("is_trunk_group", value))
        for name, label, minimum, maximum, default, help_text in FORCE_PARAMETERS:
            value = getattr(settings, name)
            editor = SliderSpinEditor(
                minimum=minimum,
                maximum=max(maximum, value or 0),
                step=0.05,
                value=default if value is None else value,
                parent=self,
            )
            editor.setToolTip(help_text)
            self.editors[name] = editor
            if name == "wind_response_scale":
                heading = QLabel(label, self)
            else:
                heading = QCheckBox(label, self)
                heading.setChecked(value is not None)
                heading.setToolTip("Override this parameter for this group. Off uses Unreal defaults. " + help_text)
                self.overrides[name] = heading
                editor.setVisible(value is not None)
                heading.toggled.connect(lambda checked, key=name, control=editor: self._toggle(key, control, checked))
            layout.addWidget(heading)
            layout.addWidget(editor)
            editor.valueChanged.connect(lambda value, key=name: self._set(key, float(value)))

    def settings(self) -> ForceWindSettings:
        return self._settings

    def _toggle(self, name, editor, checked):
        editor.setVisible(checked)
        self._set(name, float(editor.value()) if checked else None)

    def _set(self, name: str, value: bool | float | None) -> None:
        self._settings = replace(self._settings, **{name: value})
        self._on_change(self._settings)
