"""Small utility dialogs for the PySide6 shell."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from .help_deck import HELP_SLIDES, HelpSlide
from .scrollbars import keep_vertical_scrollbar_visible


class TextDialog(QDialog):
    def __init__(self, *, title: str, text: str, parent=None, read_only: bool = True) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        self.editor = QPlainTextEdit(self)
        keep_vertical_scrollbar_visible(self.editor)
        self.editor.setReadOnly(read_only)
        self.editor.setPlainText(text)
        layout.addWidget(self.editor)

    def set_text(self, text: str) -> None:
        self.editor.setPlainText(text)


class HelpDeckDialog(QDialog):
    def __init__(self, *, slides: tuple[HelpSlide, ...] = HELP_SLIDES, parent=None) -> None:
        super().__init__(parent)
        if not slides:
            raise ValueError("Help deck requires at least one slide.")
        self._slides = slides
        self._current_index = 0
        self.setWindowTitle("How to use")
        self.resize(760, 520)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        topic_row = QHBoxLayout()
        self.topic_buttons: list[QPushButton] = []
        for index, slide in enumerate(slides):
            button = QPushButton(slide.topic, self)
            button.setCheckable(True)
            button.clicked.connect(lambda _checked=False, selected=index: self.set_slide(selected))
            topic_row.addWidget(button)
            self.topic_buttons.append(button)
        topic_row.addStretch(1)
        layout.addLayout(topic_row)

        self.slide_title_label = QLabel(self)
        self.slide_title_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(self.slide_title_label)

        self.slide_body_label = QLabel(self)
        self.slide_body_label.setWordWrap(True)
        self.slide_body_label.setMinimumHeight(220)
        self.slide_body_label.setStyleSheet("font-size: 13px; line-height: 1.35;")
        layout.addWidget(self.slide_body_label, 1)

        footer = QHBoxLayout()
        self.previous_button = QPushButton("Back", self)
        self.previous_button.clicked.connect(self.previous_slide)
        self.next_button = QPushButton("Next", self)
        self.next_button.clicked.connect(self.next_slide)
        self.slide_counter_label = QLabel(self)
        footer.addWidget(self.previous_button)
        footer.addWidget(self.next_button)
        footer.addStretch(1)
        footer.addWidget(self.slide_counter_label)
        layout.addLayout(footer)
        self.set_slide(0)

    def set_slide(self, index: int) -> None:
        self._current_index = max(0, min(index, len(self._slides) - 1))
        slide = self._slides[self._current_index]
        self.slide_title_label.setText(slide.title)
        self.slide_body_label.setText(slide.body)
        self.slide_counter_label.setText(f"{self._current_index + 1} / {len(self._slides)}")
        self.previous_button.setEnabled(self._current_index > 0)
        self.next_button.setEnabled(self._current_index < len(self._slides) - 1)
        for button_index, button in enumerate(self.topic_buttons):
            button.setChecked(button_index == self._current_index)

    def next_slide(self) -> None:
        self.set_slide(self._current_index + 1)

    def previous_slide(self) -> None:
        self.set_slide(self._current_index - 1)


class SupportDialog(QDialog):
    def __init__(self, *, on_export_diagnostics: Callable[[], None], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Support / About")
        self.resize(640, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)

        self.title_label = QLabel("XML to USDA Converter", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: 700;")
        layout.addWidget(self.title_label)

        self.summary_label = QLabel(
            "Diagnostics are local-only. Export a bundle when you need to share "
            "the current preset, settings snapshot, runtime log, in-app log, and "
            "latest job manifest for a reproducible bug report.",
            self,
        )
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label, 1)

        footer = QHBoxLayout()
        footer.addStretch(1)
        self.export_button = QPushButton("Export Diagnostics", self)
        self.export_button.clicked.connect(on_export_diagnostics)
        footer.addWidget(self.export_button)
        layout.addLayout(footer)
