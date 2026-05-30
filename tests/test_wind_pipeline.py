from __future__ import annotations

import json
import pytest

from pathlib import Path

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.models import DynamicWindSimulationGroup, Joint, Matrix4d, MeshData, SourceObject, Vector3
from xml_to_usda.wind_pipeline import generate_wind_json, inspect_wind_data


DATA_DIR = Path(__file__).parent / "data"
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"


def _write_generator_level_sample(tmp_path: Path, generator_labels: tuple[str | None, ...]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bone_lines: list[str] = ["<SpeedTreeRaw>", "  <Bones>"]
    for bone_id, generator_label in enumerate(generator_labels):
        parent_id = bone_id - 1 if bone_id > 0 else -1
        generator_attribute = f' Generator="{generator_label}"' if generator_label is not None else ""
        bone_lines.append(
            f'    <Bone ID="{bone_id}" ParentID="{parent_id}" StartX="0" StartY="0" StartZ="{bone_id}" '
            f'EndX="0" EndY="0" EndZ="{bone_id + 1}"{generator_attribute} />'
        )
    bone_lines.extend(["  </Bones>", "</SpeedTreeRaw>"])
    sample_path = tmp_path / "wind_generator_levels.xml"
    sample_path.write_text("\n".join(bone_lines), encoding="utf-8")
    return sample_path


def test_wind_pipeline_inspects_generator_level_groups(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )

    dynamic_wind = inspect_wind_data(str(input_path))

    assert len(dynamic_wind.simulation_groups) == 3
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert dynamic_wind.simulation_groups[0].use_dual_influence is True
    assert dynamic_wind.simulation_groups[0].min_influence == pytest.approx(0.5)
    assert dynamic_wind.simulation_groups[0].max_influence == pytest.approx(1.0)
    assert dynamic_wind.simulation_groups[0].shift_top == pytest.approx(0.5)
    assert dynamic_wind.simulation_groups[1].min_influence == pytest.approx(0.5)
    assert dynamic_wind.simulation_groups[1].max_influence == pytest.approx(1.0)
    assert dynamic_wind.simulation_groups[1].shift_top == pytest.approx(0.5)


def test_wind_pipeline_clears_trunk_groups_for_ground_cover(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )

    dynamic_wind = inspect_wind_data(str(input_path), is_ground_cover=True)

    assert dynamic_wind.is_ground_cover is True
    assert dynamic_wind.simulation_groups
    assert all(group.is_trunk_group is False for group in dynamic_wind.simulation_groups)


def test_wind_pipeline_rejects_missing_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None))

    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(input_path))


def test_wind_pipeline_rejects_malformed_generator_levels_for_json_generation(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Branches", "Branches"))

    with pytest.raises(ValueError, match="missing_generator_level"):
        generate_wind_json(str(input_path), str(tmp_path / "invalid_DynamicWind.json"))


def test_dynamic_wind_groups_follow_vertical_levels_without_horizontal_bias() -> None:
    skeleton = (
        Joint(
            name="root",
            parent=None,
            generator_label="Group_0 2",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="trunk_1",
            parent="root",
            generator_label="Group_0 2",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_1",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_1_main",
            parent="branch_1",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_2",
            parent="branch_1",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_2_main",
            parent="branch_2",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_3",
            parent="branch_2",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_4",
            parent="branch_3",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
    )
    source_objects = (
        SourceObject(
            object_id="1",
            parent_id=None,
            name="Trunk",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Trunk",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(0, 1),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="2",
            parent_id="1",
            name="Branches_1",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_1",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(2, 3),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="3",
            parent_id="2",
            name="Branches_2",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_2",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(4, 5),
                skel_joint_weights=(1.0, 1.0),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="4",
            parent_id="3",
            name="Branches_3",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_3",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(6,),
                skel_joint_weights=(1.0,),
                skel_element_size=1,
            ),
        ),
        SourceObject(
            object_id="5",
            parent_id="4",
            name="Branches_4",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            mesh=MeshData(
                name="Branches_4",
                points=(Vector3(0.0, 0.0, 0.0),),
                face_vertex_counts=(),
                face_vertex_indices=(),
                skel_joint_indices=(7,),
                skel_joint_weights=(1.0,),
                skel_element_size=1,
            ),
        ),
    )

    dynamic_wind = build_dynamic_wind_data(skeleton, source_objects=source_objects)
    assignments = {assignment.joint_name: assignment.simulation_group_index for assignment in dynamic_wind.joint_assignments}

    assert len(dynamic_wind.simulation_groups) == 3
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert assignments["root"] == 0
    assert assignments["trunk_1"] == 0
    assert assignments["branch_1"] == 0
    assert assignments["branch_1_main"] == 1
    assert assignments["branch_2"] == 1
    assert assignments["branch_2_main"] == 2
    assert assignments["branch_3"] == 2
    assert assignments["branch_4"] == 2


def test_dynamic_wind_grouping_ignores_source_object_depth_hints() -> None:
    skeleton = (
        Joint(
            name="root",
            parent=None,
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_a",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_b",
            parent="root",
            generator_label="Group_0",
            generator_level=0,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_a_tip",
            parent="stem_a",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="stem_b_tip",
            parent="stem_b",
            generator_label="Group_1",
            generator_level=1,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_a_1",
            parent="stem_a_tip",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
        Joint(
            name="branch_a_2",
            parent="stem_a_tip",
            generator_label="Group_2",
            generator_level=2,
            bind_transform=Matrix4d.identity(),
            rest_transform=Matrix4d.identity(),
        ),
    )
    source_object = SourceObject(
        object_id="1",
        parent_id=None,
        name="Trunk",
        abs_translate=Vector3(0.0, 0.0, 0.0),
        rel_translate=Vector3(0.0, 0.0, 0.0),
        mesh=MeshData(
            name="Trunk",
            points=(Vector3(0.0, 0.0, 0.0),),
            face_vertex_counts=(),
            face_vertex_indices=(),
            skel_joint_indices=(5, 5, 6, 6),
            skel_joint_weights=(1.0, 1.0, 1.0, 1.0),
            skel_element_size=1,
        ),
    )

    without_hints = build_dynamic_wind_data(skeleton)
    with_hints = build_dynamic_wind_data(skeleton, source_objects=(source_object,))

    assert with_hints == without_hints
    assignments = {assignment.joint_name: assignment.simulation_group_index for assignment in with_hints.joint_assignments}
    assert assignments["root"] == 0
    assert assignments["stem_a"] == 0
    assert assignments["stem_b"] == 0
    assert assignments["stem_a_tip"] == 1
    assert assignments["stem_b_tip"] == 1
    assert assignments["branch_a_1"] == 2
    assert assignments["branch_a_2"] == 2


def test_dynamic_wind_json_generation_writes_groups_and_respects_slider_values(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    output_path = tmp_path / "generator_levels_DynamicWind.json"
    result = generate_wind_json(
        str(input_path),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(
                group_index=0,
                branch_order=0,
                influence=1.8,
                shift_top=0.15,
                is_trunk_group=True,
                use_dual_influence=False,
            ),
            DynamicWindSimulationGroup(
                group_index=1,
                branch_order=1,
                influence=1.2,
                shift_top=0.05,
                use_dual_influence=False,
            ),
            DynamicWindSimulationGroup(
                group_index=2,
                branch_order=2,
                influence=1.05,
                shift_top=0.01,
                use_dual_influence=False,
            ),
        ),
        gust_attenuation=0.6,
        is_ground_cover=True,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert result.output_path == str(output_path)
    assert payload["Joints"]
    assert payload["SimulationGroups"]
    assert payload["SimulationGroups"][0]["bIsTrunkGroup"] is False
    assert payload["SimulationGroups"][0]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][0]["Influence"] == pytest.approx(1.8)
    assert payload["SimulationGroups"][0]["MinInfluence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["MaxInfluence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["ShiftTop"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][1]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][1]["Influence"] == pytest.approx(1.2)
    assert payload["SimulationGroups"][2]["bUseDualInfluence"] is False
    assert payload["SimulationGroups"][2]["Influence"] == pytest.approx(1.05)
    assert payload["SimulationGroups"][2]["ShiftTop"] == pytest.approx(0.0)
    assert payload["bIsGroundCover"] is True
    assert all(group["bIsTrunkGroup"] is False for group in payload["SimulationGroups"])
    assert payload["GustAttenuation"] == pytest.approx(0.6)


def test_dynamic_wind_json_generation_serializes_dual_influence_groups(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1"),
    )
    output_path = tmp_path / "generator_levels_dual_DynamicWind.json"
    generate_wind_json(
        str(input_path),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(
                group_index=0,
                branch_order=0,
                influence=1.8,
                shift_top=0.15,
                is_trunk_group=True,
                use_dual_influence=True,
                min_influence=0.2,
                max_influence=0.9,
            ),
            DynamicWindSimulationGroup(
                group_index=1,
                branch_order=1,
                influence=1.2,
                shift_top=0.05,
                use_dual_influence=True,
                min_influence=0.15,
                max_influence=0.75,
            ),
        ),
        gust_attenuation=0.6,
        is_ground_cover=False,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["SimulationGroups"][0]["bUseDualInfluence"] is True
    assert payload["SimulationGroups"][0]["Influence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][0]["MinInfluence"] == pytest.approx(0.2)
    assert payload["SimulationGroups"][0]["MaxInfluence"] == pytest.approx(0.9)
    assert payload["SimulationGroups"][1]["bUseDualInfluence"] is True
    assert payload["SimulationGroups"][1]["Influence"] == pytest.approx(0.0)
    assert payload["SimulationGroups"][1]["MinInfluence"] == pytest.approx(0.15)
    assert payload["SimulationGroups"][1]["MaxInfluence"] == pytest.approx(0.75)


def test_inspect_wind_data_uses_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    dynamic_wind = inspect_wind_data(str(input_path))

    assert len(dynamic_wind.simulation_groups) == 3
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]


def test_generate_wind_json_respects_explicit_trunk_group_selection(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    output_path = tmp_path / "explicit_trunk_DynamicWind.json"

    generate_wind_json(
        str(input_path),
        str(output_path),
        group_settings=(
            DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=False),
            DynamicWindSimulationGroup(group_index=1, branch_order=1, is_trunk_group=True),
            DynamicWindSimulationGroup(group_index=2, branch_order=2, is_trunk_group=False),
        ),
        is_ground_cover=False,
    )

    payload = json.loads(output_path.read_text(encoding="utf-8"))

    assert payload["SimulationGroups"][0]["bIsTrunkGroup"] is False
    assert payload["SimulationGroups"][1]["bIsTrunkGroup"] is True
    assert payload["SimulationGroups"][2]["bIsTrunkGroup"] is False


def test_inspect_wind_data_clears_trunk_groups_when_ground_cover_is_enabled(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )
    dynamic_wind = inspect_wind_data(str(input_path), is_ground_cover=True)

    assert dynamic_wind.is_ground_cover is True
    assert dynamic_wind.simulation_groups
    assert all(group.is_trunk_group is False for group in dynamic_wind.simulation_groups)


def test_inspect_wind_data_rejects_missing_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None))

    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(input_path))


def test_generate_wind_json_rejects_malformed_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Branches", "Branches"))

    with pytest.raises(ValueError, match="missing_generator_level"):
        generate_wind_json(str(input_path), str(tmp_path / "invalid_DynamicWind.json"))


def test_inspect_wind_data_accepts_legacy_speedtree_generator_labels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Trunk", "Trunk", "Branches_1", "Branches_2"))

    dynamic_wind = inspect_wind_data(str(input_path))

    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True


def test_inspect_wind_data_infers_missing_upper_generator_levels_from_children(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None, None, "Branches_1", "Branches_2"))

    dynamic_wind = inspect_wind_data(str(input_path))

    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assignments = {assignment.joint_name: assignment.branch_order for assignment in dynamic_wind.joint_assignments}
    assert assignments["root"] == 0
    assert assignments["bone_001"] == 0
    assert assignments["bone_002"] == 0
    assert assignments["bone_003"] == 1
    assert assignments["bone_004"] == 2


def test_legacy_wind_samples_without_generator_labels_fail_strictly() -> None:
    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(LEAFREFS_ON_BRANCH_LEVELS))
