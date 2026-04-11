"""Small utility dialogs for the PySide6 beta shell."""

from __future__ import annotations

from PySide6.QtWidgets import QDialog, QPlainTextEdit, QVBoxLayout


class TextDialog(QDialog):
    def __init__(self, *, title: str, text: str, parent=None, read_only: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.editor = QPlainTextEdit(self)
        self.editor.setReadOnly(read_only)
        self.editor.setPlainText(text)
        layout.addWidget(self.editor)

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)
