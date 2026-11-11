"""Read SpeedTree source facts and write a validated UE 5.8 Growth Data file."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from .job_control import throw_if_cancelled
from .models import ConversionResult, ValidationIssue
from .opening_xml import read_source_structure


def _bone_rows(source):
    bones = source.bones()
    if not bones:
        raise ValueError("No bones in the XML.")
    rows = []
    for bone in bones:
        if bone.radius is None:
            raise ValueError(f"Bone {bone.source_id}: 'Radius'")
        rows.append((bone.source_id, bone.parent_id, bone.start, bone.end, bone.radius))
    return rows


def export_pve_growth(input_path: str, output_path: Path, cancel_event=None) -> ConversionResult:
    try:
        from . import _pve_growth
    except ImportError as exc:
        raise RuntimeError("PVE Growth Data requires the native pve_growth extension.") from exc

    structure = read_source_structure(input_path)
    throw_if_cancelled(cancel_event)
    diagnostics = []
    source = "Spine"
    try:
        payload, branches, points = _pve_growth.from_spines([
            (spine.source_id, spine.parent_id, spine.samples)
            for spine in structure.spines()
        ])
    except ValueError as spine_error:
        spine_failure = f"Spine unavailable: {str(spine_error).rstrip('.')}."
        throw_if_cancelled(cancel_event)
        try:
            payload, branches, points = _pve_growth.from_bones(_bone_rows(structure))
        except ValueError as bone_error:
            raise ValueError(
                f"{spine_failure} Bones unavailable: {str(bone_error).rstrip('.')}."
            ) from bone_error
        source = "Bones"
        diagnostics.append(ValidationIssue(
            "warning", "pve_bones_fallback",
            f"{spine_failure} Exported from Bones.",
        ))

    throw_if_cancelled(cancel_event)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
        temporary_path = Path(stream.name)
    try:
        temporary_path.write_text(payload + "\n", encoding="utf-8", newline="\n")
        throw_if_cancelled(cancel_event)
        temporary_path.replace(output_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    diagnostics.append(ValidationIssue("info", "pve_growth", f"{source}: {branches} branches, {points} points."))
    return ConversionResult(input_path, str(output_path), tuple(diagnostics))
