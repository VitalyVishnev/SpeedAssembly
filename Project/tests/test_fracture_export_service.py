from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from usda_test_inventory import UsdaInventory

import xml_to_usda.fracture_export_service as fracture_export_service
from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_export_service import (
    FractureCapMaterialSetting,
    FractureExportRequest,
    _cap_material_id,
    _piece_resolved_model,
    export_fracture_usda,
    export_fracture_usda_from_export_request,
)
from xml_to_usda.fracture_service import FractureError, FracturePiece, FractureSettings as _FractureSettings
from xml_to_usda.models import (
    BaseMaterialOverride,
    ConversionMode,
    ConversionRequest,
    CpuProfile,
    ExportMetadata,
    InstanceBinding,
    Joint,
    Matrix4d,
    MaterialSpec,
    MeshData,
    MeshSection,
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
    Vector2,
    Vector3,
)


def FractureSettings(*args, **kwargs):
    """Keep synthetic export fixtures on the legacy face-ownership path."""
    kwargs.setdefault("detailed_cuts_enabled", False)
    return _FractureSettings(*args, **kwargs)
from xml_to_usda.usda_writer import write_resolved_usda_document


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


def _strip_mesh(
    name: str,
    joint_indices: tuple[int, ...],
    *,
    face_ys: tuple[float, ...] | None = None,
) -> MeshData:
    points: list[Vector3] = []
    face_vertex_counts: list[int] = []
    face_vertex_indices: list[int] = []
    skel_joint_indices: list[int] = []
    for face_index, joint_index in enumerate(joint_indices):
        first_point = len(points)
        x = float(face_index)
        y = 0.0 if face_ys is None else face_ys[face_index]
        points.extend(
            (
                Vector3(x, y, 0.0),
                Vector3(x + 0.4, y, 0.0),
                Vector3(x, y + 0.4, 0.0),
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


def _repeated_part(name: str, joint_token: str, *, position_y: float) -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key="Mesh_1",
        position=Vector3(0.0, position_y, 0.0),
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
        base_mesh=_strip_mesh(
            "Base",
            (0, 1, 2, 3, 4),
            face_ys=(0.0, 0.8, 2.0, 1.2, 1.6),
        ),
        skeleton=(
            _joint("root", 0, None, 0.0, 0),
            _joint("bone_001", 1, "root", 1.0, 0),
            _joint("bone_002", 2, "bone_001", 2.0, 0),
            _joint("bone_003", 3, "bone_001", 1.4, 1),
            _joint("bone_004", 4, "bone_003", 1.8, 2),
        ),
        assembly_parts=(
            _repeated_part("TopLeaves", "bone_002", position_y=2.0),
            _repeated_part("BranchLeaves", "bone_004", position_y=1.8),
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


def _cap_test_resolved_tree() -> ResolvedAssemblyModel:
    resolved = _resolved_tree()
    base_mesh = MeshData(
        name="Base",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
        uv_coords=(
            Vector2(0.0, 0.0),
            Vector2(1.0, 0.0),
            Vector2(1.0, 1.0),
            Vector2(0.0, 0.0),
            Vector2(1.0, 1.0),
            Vector2(0.0, 1.0),
        ),
        sections=(MeshSection(material_id=7, face_indices=(0, 1)),),
        skel_joint_indices=(0, 0, 0, 0),
        skel_joint_weights=(1.0, 1.0, 1.0, 1.0),
        skel_element_size=1,
    )
    tree = replace(
        resolved.authoring_model,
        materials=(MaterialSpec(source_id=7, name="Bark", ue_asset_path="/Game/M_Bark.M_Bark"),),
        base_mesh=base_mesh,
        assembly_parts=(),
        prototypes=(),
    )
    return replace(resolved, authoring_model=tree)


def _single_face_piece() -> FracturePiece:
    return FracturePiece(
        index=0,
        name="Oak_fracture_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root",),
        base_face_indices=(0,),
        repeated_part_indices=(),
        repeated_part_names=(),
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
    assert tuple(piece.base_face_indices for piece in result.plan.pieces) == ((0, 1, 2), (3,), (4,))
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

    assert "LeafCluster" in Path(result.outputs[0].output_path).read_text(encoding="utf-8")
    assert "LeafCluster" not in Path(result.outputs[1].output_path).read_text(encoding="utf-8")
    assert "LeafCluster" in Path(result.outputs[2].output_path).read_text(encoding="utf-8")


def test_fracture_cap_material_override_authors_cap_section_and_material_binding(tmp_path: Path) -> None:
    resolved = _cap_test_resolved_tree()
    cap_material_id = _cap_material_id(resolved.authoring_model)

    piece_resolved = _piece_resolved_model(
        resolved,
        _single_face_piece(),
        generate_caps=True,
        cap_material_setting=FractureCapMaterialSetting(
            enabled=True,
            ue_asset_path="/Game/Fracture/M_Cap.M_Cap",
        ),
        cap_material_id=cap_material_id,
    )

    base_mesh = piece_resolved.authoring_model.base_mesh
    assert base_mesh is not None
    assert tuple(section.material_id for section in base_mesh.sections) == (7, cap_material_id)
    assert piece_resolved.authoring_model.materials[-1].ue_asset_path == "/Game/Fracture/M_Cap.M_Cap"

    document = write_resolved_usda_document(piece_resolved, output_path=tmp_path / "Oak_fracture_00.usda")
    text = Path(tmp_path / "Oak_fracture_00.usda").read_text(encoding="utf-8")
    inventory = UsdaInventory.from_text(text)

    assert document.text is None or "/Game/Fracture/M_Cap.M_Cap" in document.text
    assert "/Game/Fracture/M_Cap.M_Cap" in text
    assert inventory.has_prim("/Oak_fracture_00/AssemblyPartsInstancer/Prototypes/Oak_fracture_00_BaseMesh/SM_Oak_fracture_00_BaseMesh/Material_7_7", "GeomSubset")
    assert inventory.has_prim(
        f"/Oak_fracture_00/AssemblyPartsInstancer/Prototypes/Oak_fracture_00_BaseMesh/SM_Oak_fracture_00_BaseMesh/Material_{cap_material_id}_{cap_material_id}",
        "GeomSubset",
    )


def test_fracture_caps_merge_matching_material_subsets_for_valid_usd(tmp_path: Path) -> None:
    piece_resolved = _piece_resolved_model(
        _cap_test_resolved_tree(),
        _single_face_piece(),
        generate_caps=True,
    )

    write_resolved_usda_document(piece_resolved, output_path=tmp_path / "Oak_fracture_00.usda")
    text = Path(tmp_path / "Oak_fracture_00.usda").read_text(encoding="utf-8")

    assert text.count('def GeomSubset "Material_7_7"') <= 1
    assert "rel material:binding = </Oak_fracture_00/Materials/Material_7_7>" in text
    assert 'defaultPrim = "Oak_fracture_00"' in text


def test_fracture_cap_material_udim_applies_only_to_cap_faces() -> None:
    resolved = _cap_test_resolved_tree()
    cap_material_id = _cap_material_id(resolved.authoring_model)

    piece_resolved = _piece_resolved_model(
        resolved,
        _single_face_piece(),
        generate_caps=True,
        cap_material_setting=FractureCapMaterialSetting(
            enabled=True,
            ue_asset_path="/Game/Fracture/M_Cap.M_Cap",
            udim_mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
            udim_id=1003,
        ),
        cap_material_id=cap_material_id,
    )

    base_mesh = piece_resolved.authoring_model.base_mesh
    assert base_mesh is not None
    assert piece_resolved.udim_material_settings[-1] == UdimMaterialSetting(
        material_id=cap_material_id,
        mode=UdimMode.WRITE_SECONDARY_UV_OFFSET,
        udim_id=1003,
    )
    assert base_mesh.secondary_uv_coords[:3] == (Vector2(0.5, 0.5),) * 3
    assert base_mesh.secondary_uv_coords[3:] == (Vector2(2.5, 0.5),) * 3


def test_fracture_cap_material_override_rejects_disabled_caps(tmp_path: Path) -> None:
    request = FractureExportRequest(
        input_path="tree.xml",
        output_path=str(tmp_path / "Oak.usda"),
        cap_material_setting=FractureCapMaterialSetting(
            enabled=True,
            ue_asset_path="/Game/Fracture/M_Cap.M_Cap",
        ),
    )

    with pytest.raises(FractureError, match="requires Generate Caps"):
        export_fracture_usda_from_export_request(request, FractureSettings(generate_caps=False))


@pytest.mark.parametrize("path", ("", "Not/Game/Path"))
def test_fracture_cap_material_override_rejects_missing_or_invalid_material_path(tmp_path: Path, path: str) -> None:
    request = FractureExportRequest(
        input_path="tree.xml",
        output_path=str(tmp_path / "Oak.usda"),
        cap_material_setting=FractureCapMaterialSetting(enabled=True, ue_asset_path=path),
    )

    with pytest.raises(FractureError, match="Caps material"):
        export_fracture_usda_from_export_request(request, FractureSettings(generate_caps=True))


def test_fracture_export_from_conversion_request_resolves_current_operator_intent(monkeypatch, tmp_path: Path) -> None:
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

    export_request = FractureExportRequest.from_conversion_request(request)

    assert export_request.input_path == "tree.xml"
    assert export_request.conversion_mode == ConversionMode.STATIC_ASSEMBLY
    assert export_request.prototype_source_configs == request.prototype_source_configs
    assert export_request.udim_material_settings == request.udim_material_settings

    result = export_fracture_usda_from_export_request(
        export_request,
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
    assert len(result.outputs) == 3


def test_fracture_export_collision_consumes_supplied_clipped_mesh(monkeypatch) -> None:
    resolved = _resolved_tree()
    piece = FracturePiece(
        index=0,
        name="Oak_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root",),
        base_face_indices=(0, 1, 2),
        repeated_part_indices=(),
        repeated_part_names=(),
    )
    clipped_mesh = _strip_mesh("Clipped", (0,))
    observed = {}

    def capture_collision(model, collision_piece, _settings, *, render_mesh_name):
        observed["mesh"] = model.base_mesh
        observed["indices"] = collision_piece.base_face_indices
        observed["name"] = render_mesh_name
        return ()

    monkeypatch.setattr(fracture_export_service, "build_fracture_collision_meshes", capture_collision)

    _piece_resolved_model(
        resolved,
        piece,
        fractured_base_mesh=clipped_mesh,
        collision_settings=FractureCollisionSettings(enabled=True, mode=FractureCollisionMode.CONVEX),
    )

    assert observed["mesh"] is clipped_mesh
    assert observed["indices"] == (0,)


def test_fracture_piece_model_authors_sphere_collision_as_base_mesh_sibling() -> None:
    resolved = _resolved_tree()
    piece = FracturePiece(
        index=0,
        name="Oak_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root", "bone_001", "bone_002"),
        base_face_indices=(0, 1, 2),
        repeated_part_indices=(),
        repeated_part_names=(),
    )

    piece_resolved = _piece_resolved_model(
        resolved,
        piece,
        collision_settings=FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.SPHERE,
            sphere_radius_scale=0.75,
        ),
    )
    document = write_resolved_usda_document(piece_resolved, output_path=None)

    assert 'def Mesh "SM_Oak_Piece_00_BaseMesh"' in document.text
    assert 'def Mesh "USP_SM_Oak_Piece_00_BaseMesh_00"' in document.text
    assert 'uniform token purpose = "guide"' in document.text
    assert "xformOp:transform" not in document.text
    assert "PhysicsCollisionAPI" not in document.text
    assert 'def Mesh "UCX_Oak_Piece_00_00"' not in document.text


def test_fracture_piece_model_authors_capsule_collision_as_baked_ucp_mesh() -> None:
    resolved = _resolved_tree()
    piece = FracturePiece(
        index=0,
        name="Oak_Piece_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root", "bone_001", "bone_002"),
        base_face_indices=(0, 1, 2),
        repeated_part_indices=(),
        repeated_part_names=(),
    )

    piece_resolved = _piece_resolved_model(
        resolved,
        piece,
        collision_settings=FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CAPSULE,
            capsule_simplify=100,
        ),
    )
    document = write_resolved_usda_document(piece_resolved, output_path=None)

    assert 'def Mesh "UCP_SM_Oak_Piece_00_BaseMesh_00"' in document.text
    assert 'uniform token purpose = "guide"' in document.text
    assert "xformOp:transform" not in document.text
    assert "2.02812" in document.text
    assert "PhysicsCollisionAPI" not in document.text
    assert 'def Mesh "UCX_Oak_Piece_00_00"' not in document.text


def test_fracture_piece_model_authors_convex_collision_as_plain_ucx_mesh() -> None:
    piece_resolved = _piece_resolved_model(
        _resolved_tree(),
        _single_face_piece(),
        collision_settings=FractureCollisionSettings(
            enabled=True,
            mode=FractureCollisionMode.CONVEX,
            convex_max_vertices=8,
        ),
    )

    document = write_resolved_usda_document(piece_resolved, output_path=None)

    assert 'def Mesh "UCX_SM_Oak_fracture_00_BaseMesh_00"' in document.text
    assert 'uniform token purpose = "guide"' in document.text
    assert "PhysicsMeshCollisionAPI" not in document.text
    assert "physics:approximation" not in document.text
