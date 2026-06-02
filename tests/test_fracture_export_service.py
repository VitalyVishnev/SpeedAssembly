from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from usda_test_inventory import UsdaInventory

from xml_to_usda.fracture_export_service import export_fracture_usda
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.models import (
    BaseMaterialOverride,
    ConversionMode,
    ConversionRequest,
    CpuProfile,
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MeshData,
    PrototypeSourceConfig,
    PrototypeSourceMode,
    Prototype,
    PrototypeIdentity,
    PrototypeStrategy,
    Quaternion,
    RepeatedPartInstance,
    ResolvedAssemblyModel,
    TreeAsset,
    UdimMaterialSetting,
    UdimMode,
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


def _resolved_tree() -> ResolvedAssemblyModel:
    metadata = ExportMetadata(
        source_path="tree.xml",
        source_version=None,
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
    )
    tree = TreeAsset(
        metadata=metadata,
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
                mesh=_strip_mesh("LeafCluster", (0,)),
                source_key="Mesh_1",
                source_mesh_id=1,
                source_name="LeafCluster",
            ),
        ),
        prototype_strategy=PrototypeStrategy.INLINE_STATIC_PART,
    )
    return ResolvedAssemblyModel(
        source_model=tree,
        authoring_model=tree,
        conversion_mode=ConversionMode.STATIC_ASSEMBLY,
        output_stem="Oak",
    )


def test_fracture_export_writes_flat_static_assembly_siblings_that_reassemble_at_root_transform(tmp_path: Path) -> None:
    output_path = tmp_path / "Oak.usda"

    result = export_fracture_usda(
        _resolved_tree(),
        output_path,
        FractureSettings(target_piece_count=3),
    )

    assert tuple(Path(output.output_path).name for output in result.outputs) == (
        "Oak_fracture_00.usda",
        "Oak_fracture_01.usda",
        "Oak_fracture_02.usda",
    )
    assert tuple(piece.base_face_indices for piece in result.plan.pieces) == ((0,), (1, 2), (3, 4))
    assert result.outputs[0].piece.is_root_piece is True

    for output in result.outputs:
        text = Path(output.output_path).read_text(encoding="utf-8")
        inventory = UsdaInventory.from_text(text)
        root_path = f"/{output.piece.name}"

        assert inventory.has_prim(root_path, "Xform")
        assert inventory.has_api_schema(root_path, "NaniteAssemblyRootAPI")
        assert inventory.has_prim(f"{root_path}/AssemblyPartsInstancer", "PointInstancer")
        assert not inventory.contains(root_path, "rel unreal:naniteAssembly:skeleton")
        assert not inventory.contains(root_path, "primvars:skel:")

    assert "LeafCluster" not in Path(result.outputs[0].output_path).read_text(encoding="utf-8")
    assert "LeafCluster" in Path(result.outputs[1].output_path).read_text(encoding="utf-8")
    assert "LeafCluster" in Path(result.outputs[2].output_path).read_text(encoding="utf-8")


def test_fracture_export_from_conversion_request_resolves_current_operator_intent(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda.fracture_export_service import export_fracture_usda_from_conversion_request

    observed: dict[str, object] = {}

    def fake_load_resolved_assembly_model(input_path, output_mode, **kwargs):
        observed["input_path"] = input_path
        observed["output_mode"] = output_mode
        observed.update(kwargs)
        return object(), _resolved_tree()

    monkeypatch.setattr(
        "xml_to_usda.fracture_export_service.load_resolved_assembly_model",
        fake_load_resolved_assembly_model,
    )
    request = ConversionRequest(
        input_paths=("tree.xml",),
        output_path=str(tmp_path / "Oak.usda"),
        cpu_profile=CpuProfile.QUIET,
        use_explicit_material_contract=True,
        base_material_overrides=(
            BaseMaterialOverride(source_id=1, ue_asset_path="/Game/M.M"),
        ),
        udim_material_settings=(
            UdimMaterialSetting(material_id=1, mode=UdimMode.SHIFT_PRIMARY_UV, udim_id=1002),
        ),
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_1",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path="replacement.fbx",
            ),
        ),
        conversion_mode=ConversionMode.SKELETAL_ASSEMBLY,
    )

    result = export_fracture_usda_from_conversion_request(
        request,
        FractureSettings(target_piece_count=2),
    )

    assert observed["input_path"] == "tree.xml"
    assert observed["conversion_mode"] == ConversionMode.STATIC_ASSEMBLY
    assert observed["output_stem"] == "Oak"
    assert observed["cpu_profile"] == CpuProfile.QUIET
    assert observed["use_explicit_material_contract"] is True
    assert observed["base_material_overrides"] == request.base_material_overrides
    assert observed["udim_material_settings"] == request.udim_material_settings
    assert observed["prototype_source_configs"] == request.prototype_source_configs
    assert len(result.outputs) == 2
