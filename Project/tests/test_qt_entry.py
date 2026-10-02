from __future__ import annotations

from xml_to_usda.qt_ui import entry


def test_gui_import_failure_uses_dialog_when_windowed_stderr_is_missing(monkeypatch) -> None:
    messages: list[tuple[object, str, str, int]] = []
    monkeypatch.setattr(entry.sys, "stderr", None)
    monkeypatch.setattr(entry.ctypes.windll.user32, "MessageBoxW", lambda *args: messages.append(args))

    entry._report_gui_import_failure(ImportError("bad Qt DLL"))

    assert messages == [(None, "SpeedAssembly could not load its Qt runtime.\n\nbad Qt DLL", "SpeedAssembly startup failed", 0x10)]
