from __future__ import annotations

from pathlib import Path

import pytest

from xml_to_usda.models import ConversionRequest
from xml_to_usda.output_resolution import REPO_ROOT, ensure_output_path_allowed, render_output_file_name, resolve_output_path


def test_output_resolution_defaults_to_single_file_usda() -> None:
    request = ConversionRequest(input_paths=("D:/trees/SimpleTree_01.xml",))

    output_path = resolve_output_path(request, "D:/trees/SimpleTree_01.xml")

    assert output_path == Path("D:/trees/SimpleTree_01.usda")


def test_output_resolution_supports_batch_directory_and_template(tmp_path: Path) -> None:
    request = ConversionRequest(
        input_paths=("a.xml", "b.xml"),
        output_directory=str(tmp_path),
        output_naming_template="{stem}_generated",
    )

    output_path = resolve_output_path(request, "D:/trees/SimpleTree_01.xml")

    assert output_path == tmp_path / "SimpleTree_01_generated.usda"
    assert render_output_file_name(Path("SimpleTree_01.xml"), "{stem}_generated") == "SimpleTree_01_generated.usda"


def test_output_resolution_rejects_writes_inside_vault() -> None:
    illegal_output = REPO_ROOT / "vault" / "notes" / "illegal_output.usda"

    with pytest.raises(ValueError, match="immutable vault"):
        ensure_output_path_allowed(illegal_output)
