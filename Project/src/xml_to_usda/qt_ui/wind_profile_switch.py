"""Two-position export profile selector."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QPushButton, QSizePolicy

from ..wind_profiles import FORCE_BASED, LEGACY, wind_profile


class WindProfileSwitch(QFrame):
    profileChanged = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("WindProfileSwitch")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._group = QButtonGroup(self)
        self.buttons = {}
        for profile, label, help_text in (
            (LEGACY, "Legacy\n5.7–5.8", "Exports the older parametric wind settings. Compatible with UE 5.7, 5.8 and Legacy mode in 5.9. Force Based is recommended for 5.9."),
            (FORCE_BASED, "Force Based\n5.9", "Exports physics settings and structural radii for UE 5.9 only, in JSON and Skeletal Assembly USD. Select Force Based mode in Unreal to use them."),
        ):
            button = QPushButton(label, self)
            button.setObjectName("WindProfileLegacy" if profile == LEGACY else "WindProfileForce")
            button.setCheckable(True)
            button.setMinimumWidth(0)
            button.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            button.setMinimumHeight(38)
            button.setToolTip(help_text)
            button.clicked.connect(lambda _checked=False, value=profile: self.profileChanged.emit(value))
            self._group.addButton(button)
            self.buttons[profile] = button
            layout.addWidget(button, 1)
        self.set_profile(FORCE_BASED)

    def set_profile(self, profile: str) -> None:
        self.buttons[wind_profile(profile)].setChecked(True)
