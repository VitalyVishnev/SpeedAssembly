from __future__ import annotations

from xml_to_usda.fracture_preview_service import FracturePreviewSettings, generate_fracture_preview
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.models import (
    ConversionRequest,
    ExportMetadata,
    FbxMaterialMode,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    Prototype,
    PrototypeIdentity,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)


def _joint(name: str, source_id: int, parent: str | None, y: float, group: int) -> Joint:
    return Joint(
        name=name,
        source_id=source_id,
        parent=parent,
        generator_label=f"Group_{group}",
        generator_level=group,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
    )


def _strip_mesh(name: str, joint_indices: tuple[int, ...]) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for face_index, joint_index in enumerate(joint_indices):
        first_point = len(points)
        x = float(face_index)
        points.extend(
            (
                Vector3(x, 0.0, 0.0),
                Vector3(x + 0.4, 0.0, 0.0),
                Vector3(x, 0.4, 0.0),
            )
        )
        face_vertex_counts.append(3)
        face_vertex_indices.extend((first_point, first_point + 1, first_point + 2))
        skel_joint_indices.extend((joint_index, joint_index, joint_index))
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_vertex_counts),
        face_vertex_indices=tuple(face_vertex_indices),
        skel_joint_indices=tuple(skel_joint_indices),
        skel_joint_weights=(1.0,) * len(skel_joint_indices),
        skel_element_size=1,
    )


def _repeated_part(name: str, joint_token: str) -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key="Mesh_1",
        position=Vector3(0.0, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(joint_token,), weights=(1.0,)),
        source_object_id=None,
        source_mesh_id=1,
    )


def _tree() -> TreeAsset:
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_strip_mesh("Base", (0, 1, 2, 3, 4)),
        skeleton=(
            _joint("root", 0, None, 0.0, 0),
            _joint("bone_001", 1, "root", 1.0, 0),
            _joint("bone_002", 2, "bone_001", 2.0, 0),
            _joint("bone_003", 3, "bone_001", 1.4, 1),
            _joint("bone_004", 4, "bone_003", 1.8, 2),
        ),
        assembly_parts=(
            _repeated_part("TopLeaves", "bone_002"),
            _repeated_part("BranchLeaves", "bone_004"),
        ),
        prototypes=(
            Prototype(
                identity=PrototypeIdentity(source_key="Mesh_1", prim_name="LeafCluster"),
                mesh=_strip_mesh("LeafCluster", (0, 0, 0)),
                source_key="Mesh_1",
                source_mesh_id=1,
                source_name="LeafCluster",
            ),
        ),
    )


def test_fracture_preview_uses_plan_membership_stable_colors_and_simplified_geometry() -> None:
    settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
        max_base_faces_per_piece=1,
        max_prototype_faces=1,
    )

    first = generate_fracture_preview(_tree(), settings)
    second = generate_fracture_preview(_tree(), settings)

    assert tuple(piece.piece.name for piece in first.pieces) == (
        "Oak_fracture_00",
        "Oak_fracture_01",
        "Oak_fracture_02",
    )
    assert tuple(piece.base_mesh.face_count for piece in first.pieces) == (1, 1, 1)
    assert tuple(piece.color for piece in first.pieces) == tuple(piece.color for piece in second.pieces)
    assert tuple(instance.name for instance in first.instances) == ("TopLeaves", "BranchLeaves")
    assert tuple(instance.piece_index for instance in first.instances) == (1, 2)
    assert tuple(first.prototypes) == ("Mesh_1",)
    assert first.prototypes["Mesh_1"].mesh.face_count == 1
    assert first.plan.actual_piece_count == 3


def test_fracture_preview_from_conversion_request_uses_source_xml_geometry_not_operator_replacements(
    monkeypatch,
) -> None:
    from xml_to_usda.fracture_preview_service import generate_fracture_preview_from_conversion_request

    observed: dict[str, object] = {}

    def fake_load_source_tree_model(input_path, *, telemetry_callback=None, cancel_event=None):
        observed["input_path"] = input_path
        observed["telemetry_callback"] = telemetry_callback
        observed["cancel_event"] = cancel_event
        return object(), _tree(), ()

    monkeypatch.setattr("xml_to_usda.fracture_preview_service.load_source_tree_model", fake_load_source_tree_model)
    request = ConversionRequest(
        input_paths=("tree.xml",),
        output_path="Oak.usda",
        use_explicit_material_contract=True,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path="heavy_replacement.fbx",
                fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
            ),
        ),
    )

    result = generate_fracture_preview_from_conversion_request(
        request,
        FracturePreviewSettings(fracture=FractureSettings(target_piece_count=2)),
    )

    assert observed["input_path"] == "tree.xml"
    assert result.plan.output_stem == "Oak"
    assert tuple(piece.piece.name for piece in result.pieces) == ("Oak_fracture_00", "Oak_fracture_01")
