"""Default dependency bundle for the PySide6 shell.

Layer: UI facade.

The Qt shell should consume existing application and runtime services through a
small injected contract instead of importing pipeline internals directly.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QtUiDependencies:
    prepare_conversion_plan: object
    start_conversion_process: object
    start_proxy_mesh_process: object
    start_fracture_export_process: object
    start_fracture_preview_process: object
    start_part_preview_process: object
    start_wind_preview_process: object
    start_source_discovery_process: object
    close_process_queue: object
    drain_process_queue: object
    convert_request: object
    discover_base_material_rows: object
    discover_part_prototype_rows: object
    discover_missing_bone_generator_groups: object
    discover_scattered_parts: object
    discover_strictly_vertical_joints: object
    inspect_fbx_material_slot_rows: object
    load_gui_settings: object
    save_gui_settings: object
    prepare_wind_inspection_plan: object
    inspect_wind_groups: object
    prepare_wind_preview_request: object
    WindGenerationRequest: object
    generate_wind_json_from_request: object
    derive_wind_json_output_path: object
    generate_proxy_mesh_from_source_request: object
    export_proxy_usda_from_source_request: object
    export_generated_proxy_usda_from_source_request: object
    generate_fracture_preview_from_source_request: object
    export_fracture_usda_from_export_request: object
    format_wind_error: object
    should_retry_wind_error: object
    sys: object


def build_default_dependencies() -> QtUiDependencies:
    """Build the default PySide6-shell dependency bundle."""
    import sys

    from ..conversion_process import (
        close_process_queue,
        drain_process_queue,
        start_conversion_process,
        start_fracture_export_process,
        start_fracture_preview_process,
        start_part_preview_process,
        start_proxy_mesh_process,
        start_wind_preview_process,
        start_source_discovery_process,
    )
    from ..conversion_service import prepare_conversion_plan
    from ..discovery_service import (
        discover_base_material_rows,
        discover_part_prototype_rows,
        discover_scattered_parts,
        discover_strictly_vertical_joints,
        inspect_fbx_material_slot_rows,
    )
    from ..source_analysis import discover_missing_bone_generator_groups
    from ..pipeline import convert_request
    from ..settings_service import load_gui_settings, save_gui_settings
    from ..wind_service import (
        WindGenerationRequest,
        derive_wind_json_output_path,
        format_wind_error,
        generate_wind_json_from_request,
        inspect_wind_groups,
        prepare_wind_inspection_plan,
        should_retry_wind_error,
    )
    from ..wind_preview_service import prepare_wind_preview_request
    from ..proxy_mesh_service import (
        export_generated_proxy_usda_from_source_request,
        export_proxy_usda_from_source_request,
        generate_proxy_mesh_from_source_request,
    )
    from ..fracture_preview_service import generate_fracture_preview_from_source_request
    from ..fracture_export_service import export_fracture_usda_from_export_request

    return QtUiDependencies(
        prepare_conversion_plan=prepare_conversion_plan,
        start_conversion_process=start_conversion_process,
        start_proxy_mesh_process=start_proxy_mesh_process,
        start_fracture_export_process=start_fracture_export_process,
        start_fracture_preview_process=start_fracture_preview_process,
        start_part_preview_process=start_part_preview_process,
        start_wind_preview_process=start_wind_preview_process,
        start_source_discovery_process=start_source_discovery_process,
        close_process_queue=close_process_queue,
        drain_process_queue=drain_process_queue,
        convert_request=convert_request,
        discover_base_material_rows=discover_base_material_rows,
        discover_part_prototype_rows=discover_part_prototype_rows,
        discover_missing_bone_generator_groups=discover_missing_bone_generator_groups,
        discover_scattered_parts=discover_scattered_parts,
        discover_strictly_vertical_joints=discover_strictly_vertical_joints,
        inspect_fbx_material_slot_rows=inspect_fbx_material_slot_rows,
        load_gui_settings=load_gui_settings,
        save_gui_settings=save_gui_settings,
        prepare_wind_inspection_plan=prepare_wind_inspection_plan,
        inspect_wind_groups=inspect_wind_groups,
        prepare_wind_preview_request=prepare_wind_preview_request,
        WindGenerationRequest=WindGenerationRequest,
        generate_wind_json_from_request=generate_wind_json_from_request,
        derive_wind_json_output_path=derive_wind_json_output_path,
        generate_proxy_mesh_from_source_request=generate_proxy_mesh_from_source_request,
        export_proxy_usda_from_source_request=export_proxy_usda_from_source_request,
        export_generated_proxy_usda_from_source_request=export_generated_proxy_usda_from_source_request,
        generate_fracture_preview_from_source_request=generate_fracture_preview_from_source_request,
        export_fracture_usda_from_export_request=export_fracture_usda_from_export_request,
        format_wind_error=format_wind_error,
        should_retry_wind_error=should_retry_wind_error,
        sys=sys,
    )
