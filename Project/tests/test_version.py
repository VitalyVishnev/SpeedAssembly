from __future__ import annotations

import json

import pytest

from xml_to_usda import version


def test_source_preview_keeps_release_version_without_claiming_a_packaged_build(tmp_path) -> None:
    from xml_to_usda.qt_ui.entry import main

    output = tmp_path / "identity.json"
    assert main(["--build-info", str(output)]) == 0
    identity = json.loads(output.read_text(encoding="utf-8"))
    assert identity["version"] == version.__version__
    assert identity["build_mode"] == "dev"
    assert identity["git_commit"] is None
    assert version.application_title() == f"SpeedAssembly v{version.__version__} DEV"


def test_frozen_build_uses_embedded_identity_and_rejects_version_drift(monkeypatch, tmp_path) -> None:
    identity = {
        "version": version.__version__, "build_mode": "package",
        "git_commit": "a" * 40, "git_dirty": False,
        "built_at": "2026-10-03T00:00:00+00:00",
    }
    identity_path = tmp_path / "build_identity.json"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    monkeypatch.setattr(version.sys, "frozen", True, raising=False)
    monkeypatch.setattr(version, "files", lambda _package: tmp_path)
    assert version.build_identity() == identity
    assert version.application_title() == f"SpeedAssembly v{version.__version__}"
    assert identity["git_commit"] in version.build_details()

    identity["version"] = "0.0.0"
    identity_path.write_text(json.dumps(identity), encoding="utf-8")
    with pytest.raises(RuntimeError, match="does not match"):
        version.build_identity()
    identity_path.unlink()
    with pytest.raises(FileNotFoundError):
        version.build_identity()
