from __future__ import annotations

from pathlib import Path

from xml_to_usda.conversion_orchestrator import convert_request
from xml_to_usda.models import CleanupPolicy, ConversionMode, ConversionRequest
from xml_to_usda.runtime_paths import resolve_runtime_paths


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)

INVALID_SKELETON = Path(__file__).parent / "data" / "missing_skeleton.xml"


def _runtime_paths(tmp_path: Path):
    return resolve_runtime_paths(
        settings_dir=tmp_path / "settings",
        settings_path=tmp_path / "settings" / "gui_settings.json",
        cache_root=tmp_path / "runtime_cache",
    )


class _CleanupWarningWorkspace:
    def __init__(self, job_dir: Path) -> None:
        self.job_dir = job_dir
        self.debug_preserve = False

    def update_phase(self, _phase) -> None:
        pass

    def finalize(self, *, status: str, error_message: str | None = None) -> str | None:
        if status == "succeeded":
            return "cleanup deferred"
        return None


def test_convert_request_resolves_output_path_per_input(tmp_path: Path) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    first_input = tmp_path / "tree_a.xml"
    second_input = tmp_path / "tree_b.xml"
    first_input.write_text(SIMPLE_TREE_01.read_text(encoding="utf-8"), encoding="utf-8")
    second_input.write_text(SIMPLE_TREE_01.read_text(encoding="utf-8"), encoding="utf-8")

    request = ConversionRequest(
        input_paths=(str(first_input), str(second_input)),
        output_directory=str(tmp_path / "exports"),
        output_naming_template="{stem}_converted",
    )

    results = convert_request(request, runtime_paths=runtime_paths)

    assert len(results) == 2
    assert results[0].output_path == str(tmp_path / "exports" / "tree_a_converted.usda")
    assert results[1].output_path == str(tmp_path / "exports" / "tree_b_converted.usda")
    assert Path(results[0].output_path).exists()
    assert Path(results[1].output_path).exists()
    assert results[0].usda_document is not None
    assert results[1].usda_document is not None


def test_convert_request_reports_validation_error_without_writing_output(tmp_path: Path) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    output_path = tmp_path / "invalid.usda"
    request = ConversionRequest(input_paths=(str(INVALID_SKELETON),), output_path=str(output_path))

    result = convert_request(request, runtime_paths=runtime_paths)[0]

    assert result.output_path == str(output_path)
    assert result.usda_document is None
    assert any(issue.code == "missing_skeleton" and issue.severity == "error" for issue in result.diagnostics)
    assert not output_path.exists()


def test_convert_request_propagates_cleanup_warning(tmp_path: Path, monkeypatch) -> None:
    runtime_paths = _runtime_paths(tmp_path)
    output_path = tmp_path / "tree.usda"
    request = ConversionRequest(
        input_paths=(str(SIMPLE_TREE_01),),
        output_path=str(output_path),
        cleanup_policy=CleanupPolicy.EPHEMERAL,
    )

    monkeypatch.setattr(
        "xml_to_usda.conversion_orchestrator.JobWorkspace.create",
        lambda *args, **kwargs: _CleanupWarningWorkspace(job_dir=tmp_path / "job"),
    )

    result = convert_request(request, runtime_paths=runtime_paths)[0]

    assert result.usda_document is not None
    assert any(issue.code == "runtime_cleanup_warning" and issue.severity == "warning" for issue in result.diagnostics)
