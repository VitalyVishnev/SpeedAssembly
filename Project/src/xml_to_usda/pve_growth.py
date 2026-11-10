"""Read SpeedTree source facts and write a validated UE 5.8 Growth Data file."""

from pathlib import Path
from tempfile import NamedTemporaryFile

from .job_control import throw_if_cancelled
from .models import ConversionResult, ValidationIssue, Vector3
from .source_transform import build_source_transform
from .xml_reader import analyze_xml, read_source_xml


def _point(node, prefix):
    return Vector3(*(float(node.attrib[f"{prefix}{axis}"]) for axis in "XYZ"))


def _parent(node):
    value = int(node.get("ParentID", "-1"))
    return value if value >= 0 else None


def _spines(objects, transform):
    spine_objects = [(obj, spine) for obj in objects if (spine := obj.find("Spine")) is not None]
    if not spine_objects:
        raise ValueError("No Spine curves in the XML.")
    try:
        spine_ids = {int(obj.attrib["ID"]) for obj, _ in spine_objects}
        containers = {
            int(obj.attrib["ID"]) for obj in objects
            if "ID" in obj.attrib and _parent(obj) is None and obj.find("Points") is None
        }
    except (KeyError, ValueError) as exc:
        raise ValueError(f"Invalid object hierarchy: {exc}") from exc
    rows = []
    for obj, spine in spine_objects:
        label = obj.get("ID", "<missing>")
        try:
            parent = _parent(obj)
            if parent is not None and parent not in spine_ids:
                if parent not in containers:
                    raise ValueError(f"parent object {parent} has no Spine")
                parent = None
            columns = [list(map(float, (spine.findtext(key) or "").split())) for key in ("X", "Y", "Z", "Radius")]
            if len(columns[0]) < 2 or len({len(col) for col in columns}) != 1:
                raise ValueError("Spine point and radius counts do not match or have fewer than two samples")
            if int(spine.get("Count", len(columns[0]))) != len(columns[0]):
                raise ValueError("Spine Count does not match its samples")
            origin = _point(obj, "Abs")
            samples = []
            for x, y, z, radius in zip(*columns, strict=True):
                p = transform.point_components_to_stage(x + origin.x, y + origin.y, z + origin.z)
                samples.append((p.x, p.y, p.z, radius * transform.linear_scale))
            rows.append((int(obj.attrib["ID"]), parent, samples))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Object {label}: {exc}") from exc
    return rows


def _bones(bones, transform):
    rows = []
    for bone in bones:
        try:
            start = transform.point_to_stage(_point(bone, "Start"))
            end = transform.point_to_stage(_point(bone, "End"))
            rows.append((
                int(bone.attrib["ID"]), _parent(bone),
                (start.x, start.y, start.z), (end.x, end.y, end.z),
                float(bone.attrib["Radius"]) * transform.linear_scale,
            ))
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Bone {bone.get('ID', '<missing>')}: {exc}") from exc
    if not rows:
        raise ValueError("No bones in the XML.")
    return rows


def export_pve_growth(input_path: str, output_path: Path, cancel_event=None) -> ConversionResult:
    try:
        from . import _pve_growth
    except ImportError as exc:
        raise RuntimeError("PVE Growth Data requires the native pve_growth extension.") from exc

    document = read_source_xml(input_path)
    analysis = analyze_xml(document)
    nodes = analysis.source_nodes
    transform = build_source_transform(
        document.tree.getroot(), analysis.report.units_hint, analysis.report.up_axis_hint, nodes.meshes,
    )
    throw_if_cancelled(cancel_event)
    diagnostics = []
    source = "Spine"
    try:
        payload, branches, points = _pve_growth.from_spines(_spines(nodes.objects, transform))
    except ValueError as spine_error:
        spine_failure = f"Spine unavailable: {str(spine_error).rstrip('.')}."
        throw_if_cancelled(cancel_event)
        try:
            payload, branches, points = _pve_growth.from_bones(_bones(nodes.bones, transform))
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
