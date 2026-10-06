"""Public documentation destinations and contextual help buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QMessageBox, QPushButton, QWidget


DOCUMENTATION_URL = "https://vitalyvishnev.github.io/SpeedAssembly/"
DOCUMENTATION_TOPICS = {
    "home": ("", "SpeedAssembly"),
    "proxy_mesh": ("workflows/proxy-mesh/", "Proxy Mesh"),
    "udim": ("workflows/udim/", "UDIM"),
}


def open_documentation(parent: QWidget, topic: str = "home") -> None:
    route, _title = DOCUMENTATION_TOPICS[topic]
    url = DOCUMENTATION_URL + route
    if not QDesktopServices.openUrl(QUrl(url)):
        QMessageBox.warning(parent, "Documentation", f"Could not open the browser.\n{url}")


class DocumentationButton(QPushButton):
    def __init__(self, topic: str, parent: QWidget) -> None:
        super().__init__(parent)
        _route, title = DOCUMENTATION_TOPICS[topic]
        self.setObjectName("DocumentationButton")
        self.setText("?")
        self.setFixedSize(24, 24)
        self.setAutoDefault(False)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Open {title} documentation in your browser.")
        self.setAccessibleName(f"{title} documentation")
        self.clicked.connect(lambda _checked=False: open_documentation(self, topic))
