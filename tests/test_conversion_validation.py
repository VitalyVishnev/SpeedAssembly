from __future__ import annotations

import pytest

from xml_to_usda.conversion_validation import validate_conversion_request
from xml_to_usda.models import ConversionRequest, MaterialPolicy


def test_validate_conversion_request_rejects_empty_inputs() -> None:
    with pytest.raises(ValueError, match="at least one input path"):
        validate_conversion_request(ConversionRequest(input_paths=()))


def test_validate_conversion_request_rejects_explicit_output_for_batch() -> None:
    request = ConversionRequest(
        input_paths=("a.xml", "b.xml"),
        output_path="out.usda",
    )

    with pytest.raises(ValueError, match="single-file conversion"):
        validate_conversion_request(request)


def test_validate_conversion_request_rejects_invalid_legacy_part_mesh_contract() -> None:
    request = ConversionRequest(
        input_paths=("a.xml",),
        part_mesh_asset_paths=(("Mesh_1", "/Game/TreeParts/SK_Twig01.SK_Twig01"),),
    )

    with pytest.raises(ValueError, match="use_existing_part_meshes=True"):
        validate_conversion_request(request)


@pytest.mark.parametrize(
    ("conversion_request", "message"),
    (
        (
            ConversionRequest(
                input_paths=("a.xml",),
                material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
                bark_material_path="Not/Game/Path",
            ),
            "Bark material path must start with /Game/.",
        ),
        (
            ConversionRequest(
                input_paths=("a.xml",),
                material_policy=MaterialPolicy.SOURCE_MATERIAL_ROLES,
                leaves_material_path="Not/Game/Path",
            ),
            "Leaves material path must start with /Game/.",
        ),
        (
            ConversionRequest(
                input_paths=("a.xml",),
                material_policy=MaterialPolicy.SINGLE_MATERIAL,
                single_material_path="Not/Game/Path",
            ),
            "Single material path must start with /Game/.",
        ),
    ),
)
def test_validate_conversion_request_rejects_invalid_material_paths(
    conversion_request: ConversionRequest,
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        validate_conversion_request(conversion_request)
