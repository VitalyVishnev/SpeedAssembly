from __future__ import annotations

import pytest

from xml_to_usda.conversion_validation import validate_conversion_request
from xml_to_usda.models import ConversionRequest, MaterialPolicy, UdimMaterialSetting, UdimMode


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


@pytest.mark.parametrize(
    ("setting", "message"),
    (
        (
            UdimMaterialSetting(material_id=0, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1001),
            "UDIM material id must be a positive integer.",
        ),
        (
            UdimMaterialSetting(material_id=1, mode=UdimMode.WRITE_SECONDARY_UV_OFFSET, udim_id=1000),
            "UDIM id must be greater than or equal to 1001.",
        ),
    ),
)
def test_validate_conversion_request_rejects_invalid_udim_settings(
    setting: UdimMaterialSetting,
    message: str,
) -> None:
    request = ConversionRequest(input_paths=("a.xml",), udim_material_settings=(setting,))

    with pytest.raises(ValueError, match=message):
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
