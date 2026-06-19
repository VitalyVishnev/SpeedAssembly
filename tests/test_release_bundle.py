from __future__ import annotations

import zipfile
from pathlib import Path

from xml_to_usda.qt_ui.help_deck import HELP_SLIDES
from xml_to_usda.release_bundle import build_release_bundle


def test_release_bundle_packages_exe_examples_and_help_assets(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    dist_path = repo_root / "dist-next"
    sample_xml = repo_root / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
    sample_readme = repo_root / "samples" / "README.md"
    exe_path = dist_path / "XMLtoUSDAConverter.exe"
    worker_exe_path = dist_path / "XMLtoUSDAWorker.exe"
    build_info_path = dist_path / "build_info.json"

    sample_xml.parent.mkdir(parents=True)
    sample_xml.write_text("<tree/>", encoding="utf-8")
    sample_xml.with_name(".gitkeep").write_text("", encoding="utf-8")
    sample_readme.parent.mkdir(parents=True, exist_ok=True)
    sample_readme.write_text("# Samples\n", encoding="utf-8")
    dist_path.mkdir(parents=True)
    exe_path.write_bytes(b"exe")
    worker_exe_path.write_bytes(b"worker")
    build_info_path.write_text('{"build_mode":"release"}', encoding="utf-8")

    bundle_path = build_release_bundle(repo_root=repo_root, dist_path=dist_path)

    assert bundle_path == dist_path / "XMLtoUSDAConverter_release.zip"
    with zipfile.ZipFile(bundle_path) as archive:
        names = set(archive.namelist())
        assert "XMLtoUSDAConverter.exe" in names
        assert "XMLtoUSDAWorker.exe" in names
        assert "build_info.json" in names
        assert "examples/samples/README.md" in names
        assert "examples/samples/speedtree/simple_tree/variants/SimpleTree_01.xml" in names
        assert "examples/samples/speedtree/simple_tree/variants/.gitkeep" not in names
        assert "help/How_to_use.txt" in names
        help_text = archive.read("help/How_to_use.txt").decode("utf-8")
        assert HELP_SLIDES[0].title in help_text


def test_qt_package_script_builds_release_zip() -> None:
    script_text = Path("scripts/build_qt_gui_exe.ps1").read_text(encoding="utf-8")

    assert "[switch]$SkipSmoke" in script_text
    assert "xml_to_usda.release_bundle" in script_text
    assert "XMLtoUSDAConverter_release.zip" in script_text
    assert "XMLtoUSDAWorker.exe" in script_text
    assert "scripts\\launch_worker.py" in script_text
    assert "smoke --scenario high-risk" in script_text
    assert "smoke_report.json" in script_text
    assert "Packaged high-risk smoke failed" in script_text
    assert "xml_to_usda.qt_ui.release_build" in script_text
    assert "Missing application icon" in script_text
    assert "'--icon', $iconPath" in script_text
    assert "'--additional-hooks-dir', $hooksPath" in script_text
    assert "'--add-data', \"$qtUiStagingRoot;xml_to_usda/qt_ui\"" in script_text
    assert "'--exclude-module', $exclude" in script_text
    assert "'PySide6.QtOpenGL'" not in script_text
    assert "'PySide6.QtOpenGLWidgets'" not in script_text
