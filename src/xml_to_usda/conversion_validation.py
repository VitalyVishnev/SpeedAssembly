from __future__ import annotations

from .asset_paths import is_valid_unreal_asset_path, normalize_unreal_asset_path
from .models import ConversionRequest, MaterialPolicy, PrototypeSourceConfig, UdimMode


def validate_conversion_request(request: ConversionRequest) -> None:
    if not request.input_paths:
        raise ValueError("ConversionRequest requires at least one input path.")
    if request.output_path and len(request.input_paths) != 1:
        raise ValueError("Explicit output_path is only valid for single-file conversion.")
    for setting in request.udim_material_settings:
        _validate_udim_target(setting.mode, setting.udim_id, material_id=setting.material_id)
    for config in request.prototype_source_configs:
        _validate_prototype_udim_settings(config)

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


def _validate_prototype_udim_settings(config: PrototypeSourceConfig) -> None:
    _validate_udim_target(config.single_material_udim_mode, config.single_material_udim_id)
    _validate_udim_target(config.black_material_udim_mode, config.black_material_udim_id)
    _validate_udim_target(config.white_material_udim_mode, config.white_material_udim_id)
    for override in config.fbx_material_slot_overrides:
        _validate_udim_target(override.udim_mode, override.udim_id)


def _validate_udim_target(mode_value, udim_id: int, *, material_id: int | None = None) -> None:
    mode = UdimMode.parse(mode_value)
    if mode == UdimMode.OFF:
        return
    if material_id is not None and material_id <= 0:
        raise ValueError("UDIM material id must be a positive integer.")
    if udim_id < 1001:
        raise ValueError("UDIM id must be greater than or equal to 1001.")
