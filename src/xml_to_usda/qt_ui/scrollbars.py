"""Shared scrollbar policy for Qt operator surfaces."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractScrollArea


def keep_vertical_scrollbar_visible(widget: QAbstractScrollArea) -> None:
    widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
    widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
