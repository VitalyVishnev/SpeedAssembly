from __future__ import annotations

from .models import ConversionRequest, ConversionTelemetry, MaterialPolicy, PrototypeSourceMode


def format_conversion_results(
    results,
    request: ConversionRequest,
) -> str:
    lines: list[str] = [
        f"CPU profile: {request.cpu_profile.value}",
        f"Cleanup policy: {request.cleanup_policy.value}",
    ]
    if request.use_explicit_material_contract:
        lines.append("Material contract: explicit_base_and_part_materials")
        if request.base_material_overrides:
            lines.append("Base XML material overrides:")
            for override in request.base_material_overrides:
                lines.append(
                    f"  - {override.source_name or f'Material_{override.source_id}'} "
                    f"(ID {override.source_id}): {override.ue_asset_path or '<none>'}"
                )
            lines.append("")
    else:
        lines.append(f"Material policy: {request.material_policy.value}")
    if (
        not request.use_explicit_material_contract
        and request.material_policy == MaterialPolicy.SINGLE_MATERIAL
        and request.single_material_path
    ):
        lines.append(f"Single material path: {request.single_material_path}")
        lines.append("")
    elif not request.use_explicit_material_contract and (request.bark_material_path or request.leaves_material_path):
        lines.append("Material overrides:")
        lines.append(f"  - bark: {request.bark_material_path or '<none>'}")
        lines.append(f"  - leaves: {request.leaves_material_path or '<none>'}")
        lines.append("")
    if request.prototype_source_configs:
        lines.append("Prototype source overrides:")
        for config in request.prototype_source_configs:
            source_label = config.source_name or config.source_key
            if config.mode == PrototypeSourceMode.UNREAL_ASSET:
                lines.append(f"  - {source_label}: unreal_asset -> {config.asset_path or '<missing>'}")
            elif config.mode == PrototypeSourceMode.FBX_FILE:
                lines.append(
                    f"  - {source_label}: fbx_file[{config.fbx_material_mode.value}] -> {config.fbx_path or '<missing>'}"
                )
            else:
                lines.append(f"  - {source_label}: xml_mesh[{config.fbx_material_mode.value}]")
            if request.use_explicit_material_contract and config.mode != PrototypeSourceMode.UNREAL_ASSET:
                lines.append(f"      single: {config.single_material_path or '<none>'}")
                lines.append(f"      black: {config.black_material_path or '<none>'}")
                lines.append(f"      white: {config.white_material_path or '<none>'}")
                if config.fbx_material_slot_overrides:
                    lines.append("      slots:")
                    for override in config.fbx_material_slot_overrides:
                        lines.append(
                            f"        - {override.slot_name}: {override.ue_asset_path or '<none>'}"
                        )
        lines.append("")
    for result in results:
        lines.append(f"Input: {result.input_path}")
        lines.append(f"Output: {result.output_path or '<not written>'}")
        if result.diagnostics:
            lines.append("Diagnostics:")
            for issue in result.diagnostics:
                lines.append(f"  - [{issue.severity}] {issue.code}: {issue.message}")
        else:
            lines.append("Diagnostics: none")
        stats = getattr(result.usda_document, "stats", None) if result.usda_document is not None else None
        streamed = bool(getattr(stats, "streamed", False)) if type(stats).__name__ == "ExportStats" else False
        if streamed:
            lines.append(
                "Streaming export: "
                f"{stats.bytes_written} bytes in "
                f"{stats.duration_seconds:.2f}s"
            )
        if result.runtime_job_dir:
            lines.append(f"Preserved job temp dir: {result.runtime_job_dir}")
        lines.append("Status: success" if result.usda_document is not None else "Status: failed")
        lines.append("")
    return "\n".join(lines).strip()


def format_wind_group_summary(dynamic_wind) -> str:
    lines = [
        f"Wind groups detected: {len(dynamic_wind.simulation_groups)}",
        f"Joints classified: {len(dynamic_wind.joint_assignments)}",
        "",
    ]
    for group in dynamic_wind.simulation_groups:
        joint_count = sum(
            1 for assignment in dynamic_wind.joint_assignments if assignment.simulation_group_index == group.group_index
        )
        label = "Trunk" if group.is_trunk_group else f"Generator level {group.branch_order}"
        mode = "Dual" if group.use_dual_influence else "Single"
        lines.append(
            f"Group {group.group_index}: {label}, branch_order={group.branch_order}, joints={joint_count}, mode={mode}"
        )
    return "\n".join(lines)


def format_wind_json_result(result) -> str:
    lines = [
        f"Input: {result.input_path}",
        f"Output: {result.output_path}",
        f"Wind groups: {len(result.dynamic_wind.simulation_groups)}",
        f"Joints: {len(result.dynamic_wind.joint_assignments)}",
        f"Gust Attenuation: {result.dynamic_wind.gust_attenuation:.2f}",
        f"Ground Cover: {result.dynamic_wind.is_ground_cover}",
        "",
    ]
    for group in result.dynamic_wind.simulation_groups:
        mode = "dual" if group.use_dual_influence else "single"
        influence_info = (
            f"min={group.min_influence:.2f}, max={group.max_influence:.2f}"
            if group.use_dual_influence
            else f"influence={group.influence:.2f}"
        )
        shift_top = group.shift_top if group.use_dual_influence else 0.0
        lines.append(
            f"Group {group.group_index}: mode={mode}, level={group.branch_order}, {influence_info}, shiftTop={shift_top:.2f}, trunk={group.is_trunk_group}"
        )
    return "\n".join(lines)


def format_telemetry_status(telemetry: ConversionTelemetry) -> str:
    detail = telemetry.message or telemetry.phase.value.replace("_", " ").title()
    progress = ""
    if telemetry.total_units > 0:
        progress = f" ({telemetry.completed_units}/{telemetry.total_units})"
    if telemetry.output_bytes_written > 0:
        progress += f" [{telemetry.output_bytes_written} bytes]"
    if telemetry.elapsed_seconds > 0:
        progress += f" {telemetry.elapsed_seconds:.1f}s"
    return f"{detail}{progress}"
