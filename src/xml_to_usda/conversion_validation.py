from __future__ import annotations

from .asset_paths import is_valid_unreal_asset_path, normalize_unreal_asset_path
from .models import ConversionRequest, MaterialPolicy, UdimMode


def validate_conversion_request(request: ConversionRequest) -> None:
    if not request.input_paths:
        raise ValueError("ConversionRequest requires at least one input path.")
    if request.output_path and len(request.input_paths) != 1:
        raise ValueError("Explicit output_path is only valid for single-file conversion.")
    if request.part_mesh_asset_paths and not request.use_existing_part_meshes and not request.prototype_source_configs:
        raise ValueError("part_mesh_asset_paths require use_existing_part_meshes=True.")
    for setting in request.udim_material_settings:
        mode = UdimMode.parse(setting.mode)
        if mode == UdimMode.OFF:
            continue
        if setting.material_id <= 0:
            raise ValueError("UDIM material id must be a positive integer.")
        if setting.udim_id < 1001:
            raise ValueError("UDIM id must be greater than or equal to 1001.")

    checks: list[tuple[str, str | None]]
    if request.material_policy == MaterialPolicy.SINGLE_MATERIAL:
        checks = [("Single", request.single_material_path)]
    else:
        checks = [
            ("Bark", request.bark_material_path),
            ("Leaves", request.leaves_material_path),
        ]
    for label, path in checks:
        if not path:
            continue
        normalized = normalize_unreal_asset_path(path)
        if not is_valid_unreal_asset_path(normalized):
            raise ValueError(f"{label} material path must start with /Game/.")
