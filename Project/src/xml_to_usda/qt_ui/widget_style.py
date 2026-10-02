"""Keep native checkbox rendering while switching its state without transitions."""

from PySide6.QtWidgets import QApplication, QProxyStyle, QStyle, QStyleOptionButton


class InstantCheckboxStyle(QProxyStyle):
    def drawPrimitive(self, element, option, painter, widget=None):
        if element == QStyle.PrimitiveElement.PE_IndicatorCheckBox:
            # Windows 11 hardcodes a 150 ms transition, ignoring the duration hint.
            # A paint-only option preserves native appearance without animation state.
            option = QStyleOptionButton(option)
            option.styleObject = None
        super().drawPrimitive(element, option, painter, widget)


def install_widget_style() -> None:
    app = QApplication.instance()
    if app is not None and not app.property("instantCheckboxes"):
        app.setStyle(InstantCheckboxStyle(app.style().objectName()))
        app.setProperty("instantCheckboxes", True)
