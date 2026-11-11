"""Resolve one Wind Data model for JSON and Skeleton USD authoring."""

from dataclasses import replace
import json
import math

from .dynamic_wind import build_dynamic_wind_data, render_dynamic_wind_payload, validate_dynamic_wind_data
from .wind_profiles import FORCE_BASED, LEGACY, wind_profile
from .opening_xml import read_source_structure
from .source_extraction import SourceStructure


def prepare_wind_export(
    skeleton,
    *,
    profile=LEGACY,
    data=None,
    group_settings=(),
    is_ground_cover=False,
    gust_attenuation=0.0,
    input_path=None,
    root_name=None,
    source_structure: SourceStructure | None = None,
):
    profile = wind_profile(profile)
    if data is None:
        data = build_dynamic_wind_data(
            skeleton,
            group_settings=group_settings,
            is_ground_cover=is_ground_cover if profile == LEGACY else False,
            gust_attenuation=gust_attenuation,
        )
    data = replace(data, profile=profile)
    if profile == FORCE_BASED:
        data = replace(data, is_ground_cover=False, gust_attenuation=0.0)
        if input_path or source_structure is not None:
            data = with_wind_structure(data, skeleton, input_path, source_structure=source_structure)
    validate_dynamic_wind_data(data, skeleton=skeleton, require_linear_groups=True)
    roots = [j.name for j in skeleton if j.parent is None]
    if root_name and len(roots) == 1:
        from .naming import make_stable_prim_name
        root_name = make_stable_prim_name(root_name, fallback="Tree")
        data = replace(
            data,
            joint_assignments=tuple(
                replace(a, joint_name=root_name) if a.joint_name == roots[0] else a
                for a in data.joint_assignments
            ),
        )
    return data


def with_wind_structure(data, skeleton, input_path=None, *, source_structure: SourceStructure | None = None):
    structure = source_structure if source_structure is not None else read_source_structure(input_path)
    bones = {bone.source_id: bone for bone in structure.bones(skip_invalid=True)}
    try:
        curves = [(spine.samples, tuple(min(p[i] for p in spine.samples)-1e-4 for i in range(3)),
                   tuple(max(p[i] for p in spine.samples)+1e-4 for i in range(3)))
                  for spine in structure.spines()]
    except ValueError:
        curves = []
    joints = {j.name: j for j in skeleton}
    assignments = []
    missing = 0
    for assignment in data.joint_assignments:
        joint = joints[assignment.joint_name]
        parent = joints.get(joint.parent)
        bone = bones.get(joint.source_id)
        parent_bone = bones.get(parent.source_id) if parent else None
        length, distances, radii = 0.0, (), ()
        if parent and bone and parent_bone:
            start, end = parent_bone.start, bone.start
            length = math.dist(start, end)
            if length > 1e-8:
                # Incoming link follows the parent's wood only while the child's
                # start lies on that physical segment. Lateral connectors use
                # the child's section, as PVE does for branch-root stubs.
                delta = tuple(b-a for a, b in zip(parent_bone.start, parent_bone.end))
                squared = sum(v*v for v in delta)
                t = sum((b-a)*v for a, b, v in zip(start, end, delta))/squared if squared else -1
                projection = tuple(a+t*v for a, v in zip(start, delta))
                continuous = 0 <= t <= 1.00001 and math.dist(projection, end) <= 1e-5
                section = parent_bone if continuous else bone
                samples = _section_samples(section, curves, t if continuous else 1.0)
                if samples and not continuous:
                    samples = ((0.0, samples[0][1]), (1.0, samples[0][1]))
                if samples:
                    radii = tuple(r for _, r in samples)
                    distances = tuple(u*length for u, _ in samples)
                elif section.radius is not None and math.isfinite(section.radius) and section.radius > 0:
                    radii, distances = (section.radius, section.radius), (0.0, length)
        if parent and not radii:
            missing += 1
            length = 0.0
        assignments.append(replace(assignment, segment_length_m=length,
                                   radius_samples_m=radii, sample_distances_m=distances))
    warnings = ()
    if missing:
        warnings = (f"Structural radii unavailable for {missing} non-root joint(s). Unreal will estimate mesh properties and use its fallback frequency model for these joints; motion may differ from the authored structure.",)
    return replace(data, joint_assignments=tuple(assignments), warnings=warnings)


def _section_samples(bone, curves, end_fraction):
    """Use a Spine only when its geometry unambiguously contains the bone."""
    start, end = bone.start, bone.end
    matches = []
    for curve, lower, upper in curves:
        if any(not lower[i] <= point[i] <= upper[i] for point in (start, end) for i in range(3)):
            continue
        positions = [p[:3] for p in curve]
        projected = []
        arcs = [0.0]
        for a, b in zip(positions, positions[1:]):
            arcs.append(arcs[-1]+math.dist(a, b))
        for point in (start, end):
            candidates = []
            for index, (a, b) in enumerate(zip(positions, positions[1:])):
                d = tuple(y-x for x, y in zip(a, b))
                q = sum(v*v for v in d)
                if q <= 1e-16:
                    continue
                u = max(0.0, min(1.0, sum((v-x)*dv for v, x, dv in zip(point, a, d))/q))
                distance = math.dist(point, tuple(x+u*dv for x, dv in zip(a, d)))
                candidates.append((distance, arcs[index]+u*math.sqrt(q), curve[index][3]*(1-u)+curve[index+1][3]*u))
            if not candidates:
                break
            projected.append(min(candidates))
        if len(projected) != 2 or max(p[0] for p in projected) > 1e-4:
            continue
        _, lo, r0 = projected[0]
        _, hi, r1 = projected[1]
        if hi-lo <= 1e-8:
            continue
        samples = [(0.0, r0)] + [((s-lo)/(hi-lo), p[3]) for s, p in zip(arcs, curve) if lo < s < hi] + [(1.0, r1)]
        cap = max(0.0, min(end_fraction, 1.0))
        if cap <= 1e-8:
            continue
        cut = next((a[1]+(b[1]-a[1])*(cap-a[0])/(b[0]-a[0]) for a,b in zip(samples,samples[1:]) if a[0] <= cap <= b[0]), r1)
        samples = [(u/cap, r) for u,r in samples if u < cap] + [(1.0, cut)]
        if all(math.isfinite(r) and r > 0 for _,r in samples):
            matches.append(tuple(samples))
    return matches[0] if len(matches) == 1 else ()


def wind_usd_fields(data, *, meters_per_unit=1.0):
    """Return applied schemas and body lines for the main Skeleton prim."""
    if data is None or data.profile != FORCE_BASED:
        return (), ()
    payload = render_dynamic_wind_payload(data)
    schemas = ("DynamicWindSkeletonAPI_1",) + tuple(
        f"DynamicWindSimulationGroupAPI:group_{i}"
        for i in range(len(payload["SimulationGroups"]))
    )
    prefix = "unreal:dynamicWind:"
    lines = []

    def attr(kind, name, value):
        lines.append(f"{kind} {prefix}{name} = {json.dumps(value, ensure_ascii=True)}")

    joints = payload["Joints"]
    attr("token[]", "jointNames", [j["JointName"] for j in joints])
    attr("token[]", "jointSimulationGroupNames", [f'group_{j["SimulationGroupIndex"]}' for j in joints])
    attr("float[]", "jointSegmentLengths", [j["AuthoredSegmentLengthM"]/meters_per_unit for j in joints])
    attr("int[]", "jointSampleCounts", [len(j["AuthoredRadiusSamplesM"]) for j in joints])
    attr("float[]", "jointRadiusSamples", [r/meters_per_unit for j in joints for r in j["AuthoredRadiusSamplesM"]])
    attr("float[]", "jointSampleDistances", [r/meters_per_unit for j in joints for r in j["AuthoredSampleDistancesM"]])
    for index, group in enumerate(payload["SimulationGroups"]):
        for name, value in group.items():
            if name.startswith("bOverride"):
                continue
            usd_name = "isTrunk" if name == "bIsTrunkGroup" else name[0].lower()+name[1:]
            attr("bool" if isinstance(value, bool) else "float", f"simulationGroup:group_{index}:{usd_name}", value)
    return schemas, tuple(lines)
