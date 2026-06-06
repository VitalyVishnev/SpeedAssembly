from __future__ import annotations

from pathlib import Path

import pytest

from xml_to_usda.models import ConversionRequest
from xml_to_usda.output_resolution import (
    REPO_ROOT,
    ensure_output_path_allowed,
    render_output_file_name,
    resolve_output_path,
    resolve_skeletal_parts_output_directory,
)


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


@pytest.mark.parametrize(
    "template",
    [
        "../outside",
        "nested/{stem}",
        r"nested\{stem}",
        "C:/outside/{stem}",
        r"C:\outside\{stem}",
        "..",
    ],
)
def test_output_resolution_rejects_batch_template_paths(tmp_path: Path, template: str) -> None:
    request = ConversionRequest(
        input_paths=("a.xml", "b.xml"),
        output_directory=str(tmp_path),
        output_naming_template=template,
    )

    with pytest.raises(ValueError, match="Output naming template must produce a USDA filename"):
        resolve_output_path(request, "D:/trees/SimpleTree_01.xml")


def test_output_resolution_rejects_writes_inside_vault() -> None:
    illegal_output = REPO_ROOT / "vault" / "notes" / "illegal_output.usda"

    with pytest.raises(ValueError, match="immutable vault"):
        ensure_output_path_allowed(illegal_output)


def test_skeletal_parts_output_directory_uses_output_file_stem() -> None:
    assert resolve_skeletal_parts_output_directory(Path("D:/trees/SimpleTree_01_Branches.usda")) == Path(
        "D:/trees/SimpleTree_01_Branches"
    )
    assert resolve_skeletal_parts_output_directory(Path("D:/trees/ExistingFolder")) == Path("D:/trees/ExistingFolder")
