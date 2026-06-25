from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from xml_to_usda.models import ConversionResult, UsdAssemblyDocument
from xml_to_usda.runtime_paths import resolve_runtime_paths


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def _runtime_paths(tmp_path: Path):
    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )


def _install_runtime_paths(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("xml_to_usda.cli.resolve_runtime_paths", lambda: _runtime_paths(tmp_path))
    monkeypatch.setattr(
        "xml_to_usda.cli.sweep_stale_job_workspaces",
        lambda _runtime_paths: SimpleNamespace(has_activity=False, failed_paths=(), to_message=lambda: ""),
    )


def test_cli_source_materials_uses_shared_plan_to_ignore_broad_material_paths(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from xml_to_usda.cli import main

    _install_runtime_paths(monkeypatch, tmp_path)
    output_path = tmp_path / "source_materials.usda"

    exit_code = main(
        [
            "convert",
            str(SIMPLE_TREE_01),
            str(output_path),
            "--material-policy",
            "source_materials",
            "--bark-material-path",
            "Not/Game/Bark",
            "--leaves-material-path",
            "Not/Game/Leaves",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert output_path.exists()
    assert "Wrote USDA" in captured.out
    assert "must start with /Game/" not in captured.err


def test_cli_rejects_invalid_material_paths_before_writing_output(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from xml_to_usda.cli import main

    _install_runtime_paths(monkeypatch, tmp_path)
    output_path = tmp_path / "invalid_material.usda"

    exit_code = main(
        [
            "convert",
            str(SIMPLE_TREE_01),
            str(output_path),
            "--material-policy",
            "vertex_color_split",
            "--bark-material-path",
            "Not/Game/Bark",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "Bark material path must start with /Game/." in captured.err
    assert not output_path.exists()


def test_cli_part_source_config_uses_shared_explicit_material_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import xml_to_usda.cli as cli_module

    _install_runtime_paths(monkeypatch, tmp_path)
    observed = {}

    def fake_convert_request(request, *, telemetry_callback=None, cancel_event=None, runtime_paths=None):  # noqa: ARG001
        observed["request"] = request
        return (
            ConversionResult(
                input_path=request.input_paths[0],
                output_path=request.output_path,
                diagnostics=(),
                usda_document=UsdAssemblyDocument(text="#usda 1.0\n", diagnostics=()),
            ),
        )

    monkeypatch.setattr(cli_module, "convert_request", fake_convert_request)
    part_source_config_path = tmp_path / "part_sources.json"
    part_source_config_path.write_text(
        json.dumps(
            {
                "Mesh_1": {
                    "mode": "xml_mesh",
                    "fbx_material_mode": "single_material",
                    "single_material_path": "/Game/TreeParts/M_Twig.M_Twig",
                }
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli_module.main(
        [
            "convert",
            str(SIMPLE_TREE_01),
            str(tmp_path / "explicit.usda"),
            "--material-policy",
            "source_materials",
            "--part-source-config",
            str(part_source_config_path),
        ]
    )

    assert exit_code == 0
    assert observed["request"].use_explicit_material_contract is True
    assert observed["request"].prototype_source_configs[0].single_material_path == "/Game/TreeParts/M_Twig.M_Twig"


def test_cli_benchmark_normalizer_reports_stage_medians(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from xml_to_usda.cli import main

    _install_runtime_paths(monkeypatch, tmp_path)

    exit_code = main(["benchmark-normalizer", str(SIMPLE_TREE_01), "--iterations", "1", "--warmup", "0"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Normalizer benchmark:" in captured.out
    assert "parse_seconds_median:" in captured.out
    assert "inspect_seconds_median:" in captured.out
    assert "normalize_seconds_median:" in captured.out
    assert "base_faces:" in captured.out
