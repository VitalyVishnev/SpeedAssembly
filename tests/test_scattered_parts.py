from __future__ import annotations

import math
from dataclasses import replace

import pytest

from xml_to_usda.assembly_resolution import AssemblyResolutionOptions, resolve_assembly_model
from xml_to_usda.models import (
    ConversionMode,
    ExportMetadata,
    InstanceBinding,
    MaterialSpec,
    MeshData,
    MeshSection,
    Prototype,
    PrototypeIdentity,
    PrototypeStrategy,
    Quaternion,
    RepeatedPartInstance,
    ScatteredRigMode,
    SkinningQuality,
    SourceObject,
    TreeAsset,
    Vector3,
)
from xml_to_usda.scattered_parts import analyze_scattered_parts, apply_scattered_parts_rig
from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.usda_writer import render_resolved_usda
from xml_to_usda.wind_viewport_scene import build_wind_viewport_scene


def _clustered_model() -> TreeAsset:
    prototype_mesh = MeshData(
        name="Blade",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0), Vector3(0.1, 0.0, 0.0)),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
        normals=(Vector3(0.0, 0.0, 1.0),) * 3,
        sections=(MeshSection(1, (0,)),),
    )
    objects = (
        SourceObject("0", None, "arbitrary_root", Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 0.0)),
        SourceObject("10", "0", "not_a_zone", Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 0.0)),
        SourceObject("20", "0", "also_not_a_zone", Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 0.0)),
        *(
            SourceObject(str(index), parent, f"host_{index}", Vector3(0.0, 0.0, 0.0), Vector3(0.0, 0.0, 0.0), assembly_part_reference_count=1)
            for index, parent in ((11, "10"), (12, "10"), (21, "20"), (22, "20"))
        ),
    )
    parts = tuple(
        RepeatedPartInstance(
            name=f"part_{index}",
            prototype_key="Mesh_1",
            position=position,
            orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
            scale=Vector3(1.0, 1.0, 1.0),
            binding=InstanceBinding(("root",), (1.0,)),
            source_object_id=source_object_id,
            source_mesh_id=1,
            source_material_id=1,
        )
        for index, (source_object_id, position) in enumerate(
            (
                ("11", Vector3(-1.0, 0.0, 0.0)),
                ("12", Vector3(-0.8, 0.0, 0.0)),
                ("21", Vector3(1.0, 0.0, 0.0)),
                ("22", Vector3(1.2, 0.0, 0.0)),
            )
        )
    )
    return TreeAsset(
        metadata=ExportMetadata("grass.xml", None),
        materials=(MaterialSpec(1, "Grass"),),
        source_objects=objects,
        base_mesh=None,
        skeleton=(),
        assembly_parts=parts,
        prototypes=(Prototype(PrototypeIdentity("Mesh_1", "Blade"), prototype_mesh, "Mesh_1", 1, "Blade"),),
        prototype_strategy=PrototypeStrategy.INLINE_SKELETAL_PART,
    )


def test_scattered_parts_clusters_are_derived_from_hierarchy_not_names() -> None:
    analysis = analyze_scattered_parts(_clustered_model())

    assert analysis.eligible
    assert analysis.clustered
    assert analysis.cluster_count == 2
    assert tuple(cluster.part_indices for cluster in analysis.clusters) == ((0, 1), (2, 3))


@pytest.mark.parametrize(
    ("mode", "joint_count", "base_point_count", "remaining_instance_count"),
    (
        (ScatteredRigMode.WHOLE_MESH_SKINNED, 2, 12, 0),
        (ScatteredRigMode.PER_CLUSTER_RIGID, 3, 6, 2),
        (ScatteredRigMode.PER_CLUSTER_SKINNED, 3, 12, 0),
        (ScatteredRigMode.PER_INSTANCE_RIGID, 5, 3, 3),
    ),
)
def test_scattered_rig_modes_preserve_visible_blades_and_use_fixed_two_weight_width(
    mode: ScatteredRigMode,
    joint_count: int,
    base_point_count: int,
    remaining_instance_count: int,
) -> None:
    model = apply_scattered_parts_rig(_clustered_model(), mode)

    assert len(model.skeleton) == joint_count
    assert model.base_mesh is not None
    assert len(model.base_mesh.points) == base_point_count
    assert len(model.repeated_parts) == remaining_instance_count
    assert model.base_mesh.skel_element_size == 2
    assert all(part.binding.element_size == 2 for part in model.repeated_parts)
    for joint in model.skeleton:
        assert joint.bind_end_translate is not None
        dx = joint.bind_end_translate.x - joint.bind_translate.x
        dy = joint.bind_end_translate.y - joint.bind_translate.y
        dz = joint.bind_end_translate.z - joint.bind_translate.z
        length = (dx * dx + dy * dy + dz * dz) ** 0.5
        assert dy / length == pytest.approx(math.cos(math.radians(1.0)))
        assert (dx * dx + dz * dz) ** 0.5 / length == pytest.approx(
            math.sin(math.radians(1.0))
        )


def test_scattered_rig_uses_stable_varied_azimuths_without_unweighted_tips() -> None:
    source = _clustered_model()
    rigid = apply_scattered_parts_rig(source, ScatteredRigMode.PER_CLUSTER_RIGID)
    repeated = apply_scattered_parts_rig(source, ScatteredRigMode.PER_CLUSTER_RIGID)
    skinned = apply_scattered_parts_rig(source, ScatteredRigMode.PER_CLUSTER_SKINNED)

    assert rigid.skeleton == repeated.skeleton
    rigid_directions = tuple(
        (
            joint.bind_end_translate.x - joint.bind_translate.x,
            joint.bind_end_translate.z - joint.bind_translate.z,
        )
        for joint in rigid.skeleton[1:]
    )
    assert rigid_directions[0] != pytest.approx(rigid_directions[1])

    assert [joint.parent for joint in skinned.skeleton[1:]] == ["root", "root"]
    assert not any(joint.name.endswith("_tip") for joint in skinned.skeleton)
    assert set(skinned.base_mesh.skel_joint_indices) == {0, 1, 2}


def test_scattered_rig_can_derive_bone_directions_from_member_instance_axes() -> None:
    half = math.sqrt(0.5)
    source = _clustered_model()
    oriented = replace(
        source,
        assembly_parts=tuple(
            replace(
                part,
                orientation=(
                    Quaternion(half, 0.0, 0.0, -half)
                    if index < 2
                    else Quaternion(half, half, 0.0, 0.0)
                ),
                scale=Vector3(1.0, 1.0, 1.0) if index < 2 else Vector3(2.0, 2.0, 2.0),
            )
            for index, part in enumerate(source.repeated_parts)
        ),
    )

    resolved = resolve_assembly_model(
        oriented,
        AssemblyResolutionOptions(
            conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
            scattered_rig_mode=ScatteredRigMode.PER_CLUSTER_SKINNED,
            orient_scattered_bones_from_instances=True,
        ),
    ).authoring_model

    root, first, second = resolved.skeleton
    weighted_length = math.sqrt(17.0)
    assert _joint_direction(root) == pytest.approx(
        (1.0 / weighted_length, 0.0, 4.0 / weighted_length)
    )
    assert _joint_direction(first) == pytest.approx((1.0, 0.0, 0.0))
    assert _joint_direction(second) == pytest.approx((0.0, 0.0, 1.0))
    assert resolved.base_mesh is not None
    assert _vector_values(resolved.base_mesh.points[1]) == pytest.approx((0.0, 0.0, 0.0))
    assert _vector_values(resolved.base_mesh.points[2]) == pytest.approx((-1.0, -0.1, 0.0))
    assert _vector_values(resolved.base_mesh.points[7]) == pytest.approx((1.0, 0.0, 2.0))
    assert _vector_values(resolved.base_mesh.points[8]) == pytest.approx((1.2, 0.0, 0.0))
    assert _vector_values(resolved.base_mesh.normals[0]) == pytest.approx((0.0, 0.0, 1.0))
    assert _vector_values(resolved.base_mesh.normals[6]) == pytest.approx((0.0, -1.0, 0.0))

    vertical = apply_scattered_parts_rig(
        source,
        ScatteredRigMode.WHOLE_MESH_SKINNED,
        orient_bones_from_instances=True,
    )
    for joint in vertical.skeleton:
        direction = _joint_direction(joint)
        assert direction[1] == pytest.approx(math.cos(math.radians(1.0)))
        assert math.hypot(direction[0], direction[2]) == pytest.approx(
            math.sin(math.radians(1.0))
        )


def test_scattered_instance_orientation_fails_when_a_cluster_has_no_average_axis() -> None:
    source = _clustered_model()
    parts = list(source.repeated_parts)
    parts[1] = replace(parts[1], orientation=Quaternion(0.0, 1.0, 0.0, 0.0))

    with pytest.raises(ValueError, match="cluster 0 bone orientation.*cancel"):
        apply_scattered_parts_rig(
            replace(source, assembly_parts=tuple(parts)),
            ScatteredRigMode.PER_CLUSTER_RIGID,
            orient_bones_from_instances=True,
        )


def test_static_assembly_ignores_persisted_skinning_quality_for_leaf_only_source() -> None:
    resolved = resolve_assembly_model(
        _clustered_model(),
        AssemblyResolutionOptions(
            conversion_mode=ConversionMode.STATIC_ASSEMBLY,
            skinning_quality=SkinningQuality.FOUR_WEIGHTS,
        ),
    )

    assert resolved.authoring_model.base_mesh is None
    assert resolved.authoring_model.skeleton == ()
    assert len(resolved.authoring_model.repeated_parts) == 4
    assert not [issue for issue in resolved.diagnostics if issue.severity == "error"]


def test_cluster_modes_coerce_to_whole_mesh_when_hosts_are_directly_scattered() -> None:
    source = _clustered_model()
    direct_hosts = tuple(
        replace(item, parent_id="0") if item.assembly_part_reference_count else item
        for item in source.source_objects
    )
    unclustered = replace(source, source_objects=direct_hosts)

    result = apply_scattered_parts_rig(unclustered, ScatteredRigMode.PER_CLUSTER_SKINNED)

    assert analyze_scattered_parts(unclustered).clustered is False
    assert len(result.skeleton) == 2
    assert len(result.repeated_parts) == 0


def test_scattered_rigid_wind_preview_keeps_remaining_blades_instanced() -> None:
    model = apply_scattered_parts_rig(_clustered_model(), ScatteredRigMode.PER_CLUSTER_RIGID)

    scene = build_wind_viewport_scene(model, build_dynamic_wind_data(model.skeleton))

    assert scene.stats.instance_count == 2
    assert scene.stats.logical_triangles == 4
    assert len(scene.bone_segments) == 3


@pytest.mark.parametrize(
    ("mode", "is_nanite_assembly"),
    (
        (ScatteredRigMode.WHOLE_MESH_SKINNED, False),
        (ScatteredRigMode.PER_CLUSTER_RIGID, True),
        (ScatteredRigMode.PER_CLUSTER_SKINNED, False),
        (ScatteredRigMode.PER_INSTANCE_RIGID, True),
    ),
)
def test_skeletal_root_uses_nanite_assembly_contract_only_when_instances_remain(
    mode: ScatteredRigMode,
    is_nanite_assembly: bool,
) -> None:
    resolved = resolve_assembly_model(
        _clustered_model(),
        AssemblyResolutionOptions(
            conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
            scattered_rig_mode=mode,
        ),
    )

    text = render_resolved_usda(resolved).text or ""

    assert 'def SkelRoot "BaseTreeSkelRoot"' in text
    assert ("NaniteAssemblyRootAPI" in text) is is_nanite_assembly
    assert ("unreal:naniteAssembly:meshType" in text) is is_nanite_assembly
    assert ("unreal:naniteAssembly:skeleton" in text) is is_nanite_assembly
    assert ('def PointInstancer "AssemblyPartsInstancer"' in text) is is_nanite_assembly


def _joint_direction(joint) -> tuple[float, float, float]:
    end = joint.bind_end_translate
    assert end is not None
    start = joint.bind_translate
    direction = (end.x - start.x, end.y - start.y, end.z - start.z)
    length = math.sqrt(sum(value * value for value in direction))
    return tuple(value / length for value in direction)


def _vector_values(vector: Vector3) -> tuple[float, float, float]:
    return vector.x, vector.y, vector.z
