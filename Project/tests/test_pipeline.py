from __future__ import annotations

import json
import pickle
import xml.etree.ElementTree as ET
from dataclasses import replace
from enum import Enum
from pathlib import Path

import pytest

from xml_to_usda.normalizer import normalize_to_canonical
from xml_to_usda.models import (
    BaseMaterialOverride,
    Bounds,
    Color4,
    CpuProfile,
    ConversionMode,
    ExportMetadata,
    FbxMaterialSlotOverride,
    InstanceBinding,
    Joint,
    MaterialPolicy,
    MaterialSpec,
    Matrix4d,
    MeshData,
    MeshSection,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    PrototypeStrategy,
    RepeatedPartInstance,
    PrototypeResolutionMode,
    SourceObject,
    TreeAsset,
    Quaternion,
    Vector2,
    Vector3,
)
from xml_to_usda import job_control
from xml_to_usda.job_control import apply_process_profile, cpu_worker_count, reserved_cpu_count
from xml_to_usda.normalizer import _vertex_color_material_sections
from xml_to_usda.pipeline import (
    _apply_material_policy,
    convert_file,
    discover_source_materials,
    discover_part_prototypes,
    inspect_source,
    load_canonical_model,
)
from xml_to_usda.ue_schema import DEFAULT_UE_SCHEMA_CONTRACT
from xml_to_usda.usda_writer import render_usda
from xml_to_usda.validator import validate_model
from xml_to_usda.xml_reader import inspect_xml, read_source_xml, render_inspect_report


DATA_DIR = Path(__file__).parent / "data"
SIMPLE_TREE_01 = Path(__file__).resolve().parents[1] / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
LEAFREFS_ON_TRUNK = DATA_DIR / "leafrefs_on_trunk.xml"
LEAFREFS_ON_BRANCH_LEVELS = DATA_DIR / "leafrefs_on_branch_levels.xml"
INVALID_LEAF_BONE = DATA_DIR / "invalid_leaf_bone.xml"


def _write_fbx_json_payload(
    tmp_path: Path,
    *,
    include_vertex_colors: bool = True,
    color_components: list[float] | None = None,
    fbx_material_slots: list[dict[str, object]] | None = None,
    sections: list[dict[str, object]] | None = None,
    file_name: str = "prototype_payload.json",
) -> Path:
    payload = {
        "point_components": [
            0.0, 0.0, 0.0,
            1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0,
            1.0, 0.0, 1.0,
            0.0, 1.0, 1.0,
        ],
        "face_vertex_counts": [3, 3],
        "face_vertex_indices": [0, 1, 2, 3, 4, 5],
        "uv_components": [
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
            0.0, 0.0,
            1.0, 0.0,
            0.0, 1.0,
        ],
    }
    if color_components is not None:
        payload["vertex_color_components"] = color_components
    elif include_vertex_colors:
        payload["vertex_color_components"] = [
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            0.0, 0.0, 0.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
            1.0, 1.0, 1.0, 1.0,
        ]
    if fbx_material_slots is not None:
        payload["fbx_material_slots"] = fbx_material_slots
    if sections is not None:
        payload["sections"] = sections
    payload_path = tmp_path / file_name
    payload_path.write_text(json.dumps(payload), encoding="utf-8")
    return payload_path


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


def _write_shifted_material_sample(tmp_path: Path, material_id_map: dict[int, int]) -> Path:
    tree = ET.parse(SIMPLE_TREE_01)
    root = tree.getroot()

    for material_node in root.findall(".//Materials/Material"):
        raw_id = material_node.attrib.get("ID")
        if raw_id is None or not raw_id.isdigit():
            continue
        mapped_id = material_id_map.get(int(raw_id))
        if mapped_id is not None:
            material_node.set("ID", str(mapped_id))

    for node in root.iter():
        raw_id = node.attrib.get("Material")
        if raw_id is None or not raw_id.lstrip("-").isdigit():
            continue
        mapped_id = material_id_map.get(int(raw_id))
        if mapped_id is not None:
            node.set("Material", str(mapped_id))

    sample_path = tmp_path / "shifted_material_ids.xml"
    tree.write(sample_path, encoding="utf-8", xml_declaration=True)
    return sample_path


def _normalize_usda_emitted_text(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"))


def _normalize_usda_logical_text(text: str) -> str:
    return "\n".join(
        line.strip()
        for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        if line.strip()
    )


def test_cpu_profile_worker_count_math() -> None:
    assert reserved_cpu_count(CpuProfile.BALANCED, cpu_count=8) == 2
    assert cpu_worker_count(CpuProfile.BALANCED, cpu_count=8) == 6
    assert reserved_cpu_count(CpuProfile.MAX_SPEED, cpu_count=8) == 1
    assert cpu_worker_count(CpuProfile.MAX_SPEED, cpu_count=8) == 7
    assert reserved_cpu_count(CpuProfile.QUIET, cpu_count=8) == 4
    assert cpu_worker_count(CpuProfile.QUIET, cpu_count=8) == 4


def test_apply_process_profile_declares_winapi_signatures(monkeypatch) -> None:
    class FakeFunction:
        def __init__(self, return_value=True):
            self.return_value = return_value
            self.argtypes = None
            self.restype = None
            self.calls = []

        def __call__(self, *args):
            self.calls.append(args)
            return self.return_value

    class FakeKernel32:
        def __init__(self):
            self.GetCurrentProcess = FakeFunction(return_value=1234567890123)
            self.SetPriorityClass = FakeFunction()

        def __getattr__(self, name):
            if name == "SetProcessAffinityMask":
                raise AssertionError("Process profile must not set packaged worker CPU affinity.")
            raise AttributeError(name)

    fake_kernel32 = FakeKernel32()
    monkeypatch.setattr(job_control.os, "name", "nt")
    monkeypatch.setattr(job_control.ctypes, "WinDLL", lambda *_args, **_kwargs: fake_kernel32, raising=False)
    monkeypatch.setattr(job_control, "logical_cpu_count", lambda: 40)

    apply_process_profile(CpuProfile.BALANCED)

    assert fake_kernel32.GetCurrentProcess.argtypes == ()
    assert fake_kernel32.GetCurrentProcess.restype == job_control.wintypes.HANDLE
    assert fake_kernel32.SetPriorityClass.argtypes == (job_control.wintypes.HANDLE, job_control.wintypes.DWORD)
    assert fake_kernel32.SetPriorityClass.calls == [(1234567890123, 0x00004000)]


def test_inspect_report_tracks_structure_without_sample_specific_contracts() -> None:
    report = inspect_source(SIMPLE_TREE_01)
    payload = json.loads(render_inspect_report(report))

    assert payload["root_tag"] == "SpeedTreeRaw"
    assert payload["hierarchy_depth"] >= 1
    assert payload["object_class_counts"]["root"] >= 1
    assert payload["object_class_counts"]["mesh_object"] >= 1
    assert payload["object_class_counts"]["leaf_reference_host"] >= 1
    assert "Spine" not in payload["unknown_sections"]
    assert payload["leaf_binding_distribution"]
    assert payload["leaf_mesh_distribution"]
    assert payload["leaf_source_object_distribution"]
    assert payload["material_count"] == 3
    assert payload["base_material_distribution"] == {"0": 46, "1": payload["base_mesh_face_count"] - 46}
    assert payload["prototype_material_distribution"]["0"] > 0
    assert payload["base_geometry_mode"] == "merged"
    assert payload["base_mesh_part_count"] >= 2
    assert payload["base_mesh_point_count"] > 0
    assert payload["base_mesh_face_count"] > 0
    assert payload["prototype_structure"] == "inline_skeletal_part"
    assert payload["binding_mode"] == "single_joint"
    assert payload["binding_element_size"] == 1
    assert set(payload["support_primvars"]) == {
        "boneCapture_pCaptPath",
        "hierarchicalDepth",
        "localtransform",
        "logicalDepth",
        "ueJointNames",
    }
    assert len(payload["orientation_sample"]) == 3


def test_discover_part_prototypes_matches_canonical_prototype_identity_for_gui_loading() -> None:
    discovered = discover_part_prototypes(str(SIMPLE_TREE_01))
    _, model, _ = load_canonical_model(str(SIMPLE_TREE_01))
    instance_counts_by_key: dict[str, int] = {}
    for part in model.assembly_parts:
        instance_counts_by_key[part.prototype_key] = instance_counts_by_key.get(part.prototype_key, 0) + 1

    assert [
        (prototype.source_key, prototype.source_name, prototype.source_mesh_id, prototype.instance_count)
        for prototype in discovered
    ] == [
        (prototype.source_key, prototype.source_name, prototype.source_mesh_id, instance_counts_by_key[prototype.source_key])
        for prototype in model.prototypes
    ]


def test_canonical_model_extracts_base_tree_and_assembly_parts() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    assert len(model.materials) == 3
    assert model.source_objects
    assert model.skeleton
    assert model.base_tree_parts
    assert model.branch_segments
    assert model.assembly_parts
    assert model.mesh_library
    assert model.prototypes
    assert model.skeletal_support_primvars is not None
    assert model.dynamic_wind is None
    assert model.binding_mode == "single_joint"
    assert model.binding_element_size == 1
    assert model.base_mesh.skel_joint_indices
    assert model.base_mesh.skel_joint_weights
    assert model.base_mesh.uv_coords
    assert (model.skeleton[0].bind_translate.x, model.skeleton[0].bind_translate.y, model.skeleton[0].bind_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert (model.skeleton[0].rest_translate.x, model.skeleton[0].rest_translate.y, model.skeleton[0].rest_translate.z) == pytest.approx((0.0, 0.0, 0.0))
    assert model.skeleton[1].rest_translate != pytest.approx(model.skeleton[1].bind_translate)
    assert abs(model.skeleton[1].bind_translate.y) > 0
    assert len(model.base_mesh.skel_joint_indices) == len(model.base_mesh.points)
    assert len(model.base_mesh.skel_joint_weights) == len(model.base_mesh.points)
    assert len(model.base_mesh.uv_coords) == len(model.base_mesh.face_vertex_indices)
    assert {material.source_id for material in model.materials} == {0, 1, 2}
    assert {section.material_id for section in model.base_mesh.sections} == {0, 1}
    assert all(
        prototype.mesh is not None and {section.material_id for section in prototype.mesh.sections} == {0}
        for prototype in model.prototypes
    )
    assert all(part.binding.joint_tokens for part in model.assembly_parts)
    assert all(len(part.binding.joint_tokens) == len(part.binding.weights) for part in model.assembly_parts)
    assert all(token.startswith("bone_") or token == "root" for part in model.assembly_parts for token in part.binding.joint_tokens)
    assert {prototype.source_key for prototype in model.prototypes} == {part.prototype_key for part in model.assembly_parts}


def test_base_tree_mesh_merges_trunk_and_branch_geometry_in_stage_space() -> None:
    document = read_source_xml(SIMPLE_TREE_01)
    report = inspect_xml(document)
    model = normalize_to_canonical(document, report)

    assert model.base_mesh is not None
    primary_source_object = next(
        source_object
        for source_object in model.source_objects
        if source_object.mesh is not None and source_object.parent_id in {"0", None, "-1"}
    )
    assert primary_source_object.mesh is not None
    assert len(model.base_mesh.points) > len(primary_source_object.mesh.points)
    assert len(model.base_mesh.face_vertex_counts) > len(primary_source_object.mesh.face_vertex_counts)
    assert model.base_tree_parts[0].point_offset == 0
    assert model.base_tree_parts[1].point_offset > model.base_tree_parts[0].point_offset
    translated_point = model.base_mesh.points[model.base_tree_parts[1].point_offset]
    assert translated_point != primary_source_object.mesh.points[0]
    assert translated_point.y > primary_source_object.mesh.points[0].y


def test_core_value_types_remain_pickleable() -> None:
    payload = (
        Vector2(1.0, 2.0),
        Vector3(3.0, 4.0, 5.0),
        Color4(0.25, 0.5, 0.75, 1.0),
        Quaternion(1.0, 0.0, 0.0, 0.0),
    )

    assert pickle.loads(pickle.dumps(payload)) == payload


def test_model_dataclasses_remain_pickleable() -> None:
    mesh = MeshData(
        name="TestMesh",
        points=(Vector3(0.0, 0.0, 0.0),),
        face_vertex_counts=(1,),
        face_vertex_indices=(0,),
    )
    bounds = Bounds(minimum=Vector3(0.0, 0.0, 0.0), maximum=Vector3(1.0, 1.0, 1.0))
    payload = (
        Joint(name="joint_0", source_id=0),
        mesh,
        SourceObject(
            object_id="0",
            parent_id=None,
            name="Object_0",
            abs_translate=Vector3(0.0, 0.0, 0.0),
            rel_translate=Vector3(0.0, 0.0, 0.0),
            bounds=bounds,
            mesh=mesh,
        ),
        RepeatedPartInstance(
            name="Part_0",
            prototype_key="Mesh_0",
            position=Vector3(0.0, 0.0, 0.0),
            orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
            scale=Vector3(1.0, 1.0, 1.0),
            binding=InstanceBinding(joint_tokens=("Tree_point_0",), weights=(1.0,)),
            source_object_id="0",
            source_mesh_id=0,
        ),
    )

    assert pickle.loads(pickle.dumps(payload)) == payload


