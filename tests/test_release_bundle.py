from __future__ import annotations

import zipfile
from pathlib import Path

from xml_to_usda.release_bundle import build_release_bundle


def test_release_bundle_packages_exe_examples_and_help_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    dist_path = repo_root / "dist-next"
    sample_xml = repo_root / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
    exe_path = dist_path / "SpeedAssembly.exe"
    build_info_path = dist_path / "build_info.json"

    sample_xml.parent.mkdir(parents=True)
    sample_xml.write_text("<tree/>", encoding="utf-8")
    (repo_root / "LICENSE").write_text("MIT License", encoding="utf-8")
    (repo_root / "THIRD_PARTY_NOTICES.md").write_text("Third-party notices", encoding="utf-8")
    ufbx_license = repo_root / "src" / "xml_to_usda" / "vendor" / "ufbx" / "LICENSE"
    ufbx_license.parent.mkdir(parents=True)
    ufbx_license.write_text("ufbx license", encoding="utf-8")
    sample_xml.with_name(".gitkeep").write_text("", encoding="utf-8")
    dist_path.mkdir(parents=True)
    exe_path.write_bytes(b"exe")
    build_info_path.write_text('{"build_mode":"release"}', encoding="utf-8")

    bundle_path = build_release_bundle(repo_root=repo_root, dist_path=dist_path)

    assert bundle_path == dist_path / "SpeedAssembly_release.zip"
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        assert "SpeedAssembly.exe" in names
        assert "XMLtoUSDAWorker.exe" not in names
        assert "build_info.json" not in names
        assert "help/How_to_use.txt" not in names
        assert names == {
            "SpeedAssembly.exe",
            "LICENSE",
            "THIRD_PARTY_NOTICES.md",
            "licenses/ufbx-LICENSE",
            "examples/SimpleTree_01.xml",
        }


def test_qt_package_script_builds_release_zip() -> None:
    script_text = Path("scripts/build_qt_gui_exe.ps1").read_text(encoding="utf-8")

    assert "[switch]$Quick" in script_text
    assert "[switch]$SkipSmoke" in script_text
    assert "dist-preview" in script_text
    assert "SpeedAssembly_preview.cmd" in script_text
    assert "Quick preview import check failed." in script_text
    assert "This source-backed preview skips PyInstaller" in script_text
    assert ".venv310\\Scripts\\pythonw.exe" in script_text
    assert "xml_to_usda.release_bundle" in script_text
    assert "SpeedAssembly_release.zip" in script_text
    assert "XMLtoUSDAWorker.exe" in script_text
    assert "scripts\\launch_worker.py" not in script_text
    assert "xml_to_usda/embedded_worker" not in script_text
    assert "'--add-binary'" not in script_text
    assert "External worker exe must not be distributed" in script_text
    assert "smoke --scenario packaged-stability --repeat 2 --fail-on-retry" in script_text
    assert "fracture-preview-recovery" in script_text
    assert "pytest -q -m packaged" in script_text
    assert "Packaged Fracture worker recovery smoke failed" in script_text
    assert "smoke_report.json" in script_text
    assert "Packaged Detailed Cuts stability smoke failed" in script_text
    assert "xml_to_usda.qt_ui.release_build" in script_text
    assert "Missing application icon" in script_text
    assert "'--icon', $iconPath" in script_text
    assert "'--additional-hooks-dir', $hooksPath" in script_text
    assert "'--add-data', \"$qtUiStagingRoot;xml_to_usda/qt_ui\"" in script_text
    assert "'--exclude-module', $exclude" in script_text
    assert "'PySide6.QtOpenGL'" not in script_text
    assert "'PySide6.QtOpenGLWidgets'" not in script_text
