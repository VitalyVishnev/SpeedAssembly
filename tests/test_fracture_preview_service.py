from __future__ import annotations

import pickle
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import xml_to_usda.fracture_preview_service as fracture_preview_service
from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_geometry import FractureGeometryPiece, FractureGeometryResult
from xml_to_usda.fracture_preview_service import (
    FracturePreviewSettings,
    FracturePreviewSourceRequest,
    generate_fracture_preview,
    generate_fracture_preview_from_source_request,
)
from xml_to_usda.fracture_service import FractureError, FractureSettings as _FractureSettings, plan_fracture
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


def FractureSettings(*args, **kwargs):
    """Keep synthetic planner fixtures on the legacy face-ownership path."""
    kwargs.setdefault("detailed_cuts_enabled", False)
    return _FractureSettings(*args, **kwargs)


BIG_SPRUCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "BigSpruce"
    / "SkeletalAssemblyTest_Spruce_Big_low.xml"
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


def _repeated_part(name: str, joint_token: str, *, prototype_key: str = "Mesh_1") -> RepeatedPartInstance:
    return RepeatedPartInstance(
        name=name,
        prototype_key=prototype_key,
        position=Vector3(0.0, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(joint_token,), weights=(1.0,)),
        source_object_id=None,
        source_mesh_id=1,
    )


def _prototype(source_key: str, name: str, face_count: int) -> Prototype:
    return Prototype(
        identity=PrototypeIdentity(source_key=source_key, prim_name=name),
        mesh=_strip_mesh(name, tuple(0 for _ in range(face_count))),
        source_key=source_key,
        source_mesh_id=1,
        source_name=name,
    )


def _tree_with_repeated_branch_count(count: int) -> TreeAsset:
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
        assembly_parts=tuple(_repeated_part(f"Branch_{index:03d}", "bone_004") for index in range(count)),
        prototypes=(_prototype("Mesh_1", "BranchCluster", 120),),
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
        prototypes=(_prototype("Mesh_1", "LeafCluster", 3),),
    )


def _tree_with_mixed_repeated_prototypes() -> TreeAsset:
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
            _repeated_part("SmallBranch", "bone_002", prototype_key="Mesh_small"),
            _repeated_part("LargeBranch", "bone_004", prototype_key="Mesh_large"),
        ),
        prototypes=(
            _prototype("Mesh_small", "SmallBranchCluster", 100),
            _prototype("Mesh_large", "LargeBranchCluster", 1000),
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
    assert tuple(instance.piece_index for instance in first.instances) == (0, 2)
    assert tuple(first.prototypes) == ("Mesh_1",)
    assert first.prototypes["Mesh_1"].mesh.face_count == 1
    assert first.plan.actual_piece_count == 3
    assert first.viewport_scene is not None
    assert first.viewport_scene.scene_id == "Oak_fracture_preview"
    assert first.viewport_scene.stats.logical_triangles == 5
    assert first.viewport_scene.stats.instance_count == 2


def test_detailed_preview_collision_consumes_final_boolean_piece_meshes(monkeypatch) -> None:
    model = _tree()
    fracture_settings = _FractureSettings(
        target_piece_count=2,
        output_stem="Oak",
        detailed_cuts_enabled=True,
        detailed_cut_intensity=0.0,
        detailed_cut_density=4,
    )
    plan = plan_fracture(model, replace(fracture_settings, detailed_cuts_enabled=False))
    final_meshes = tuple(_strip_mesh(f"Final_{piece.index}", (0,)) for piece in plan.pieces)
    geometry = FractureGeometryResult(
        plan=plan,
        pieces=tuple(
            FractureGeometryPiece(piece=piece, base_mesh=final_meshes[piece.index])
            for piece in plan.pieces
        ),
    )
    collision_inputs = []

    monkeypatch.setattr(fracture_preview_service, "_BOOLEAN_PREVIEW_SESSION_CACHE", None)
    monkeypatch.setattr(fracture_preview_service, "prepare_boolean_fracture_source", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        fracture_preview_service,
        "prepare_boolean_multi_prototype",
        lambda *_args, **_kwargs: SimpleNamespace(build=lambda _settings: object()),
    )
    monkeypatch.setattr(fracture_preview_service, "fracture_geometry_from_boolean_multi", lambda _result: geometry)

    def capture_collision(collision_model, collision_piece, _settings, *, render_mesh_name):
        collision_inputs.append((collision_model.base_mesh, collision_piece.base_face_indices, render_mesh_name))
        return ()

    monkeypatch.setattr(fracture_preview_service, "build_fracture_collision_meshes", capture_collision)

    generate_fracture_preview(
        model,
        FracturePreviewSettings(
            fracture=fracture_settings,
            collision=FractureCollisionSettings(enabled=True, mode=FractureCollisionMode.CONVEX),
        ),
        include_viewport_scene=False,
    )

    assert tuple(mesh for mesh, _indices, _name in collision_inputs) == final_meshes
    assert tuple(indices for _mesh, indices, _name in collision_inputs) == ((0,),) * len(final_meshes)


def test_fracture_preview_can_skip_viewport_scene_for_worker_transport() -> None:
    preview = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
        include_viewport_scene=False,
    )

    assert preview.viewport_scene is None
    assert preview.plan.actual_piece_count == 3
    assert preview.pieces


def test_fracture_preview_rejects_invalid_branch_prune_aggression() -> None:
    with pytest.raises(FractureError, match="branch prune aggression"):
        generate_fracture_preview(_tree(), FracturePreviewSettings(branch_prune_aggression=1.5))


def test_fracture_preview_reuses_base_cap_source_context_for_all_pieces(monkeypatch) -> None:
    import xml_to_usda.fracture_geometry as fracture_geometry

    calls = 0
    original = fracture_geometry._source_edge_faces

    def count_source_edge_faces(mesh, face_ranges=None):
        nonlocal calls
        calls += 1
        return original(mesh, face_ranges)

    monkeypatch.setattr(fracture_geometry, "_source_edge_faces", count_source_edge_faces)

    result = generate_fracture_preview(
        _tree(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak", generate_caps=True),
            max_base_faces_per_piece=2,
            max_prototype_faces=1,
        ),
    )

    assert result.plan.actual_piece_count == 3
    assert calls == 1


def test_fracture_preview_source_request_reuses_typed_source_cache(monkeypatch, tmp_path) -> None:
    from xml_to_usda import fracture_preview_service

    cache_root = tmp_path / "cache" / "fracture_preview_source_models"
    monkeypatch.setattr(fracture_preview_service, "_preview_source_model_cache_root", lambda: cache_root)
    original_load_source_tree_model = fracture_preview_service.load_source_tree_model
    load_count = 0

    def count_source_load(*args, **kwargs):  # type: ignore[no-untyped-def]
        nonlocal load_count
        load_count += 1
        return original_load_source_tree_model(*args, **kwargs)

    monkeypatch.setattr(fracture_preview_service, "load_source_tree_model", count_source_load)

    request = FracturePreviewSourceRequest(input_path=str(BIG_SPRUCE))
    settings = FracturePreviewSettings(
        fracture=FractureSettings(target_piece_count=5, output_stem="Spruce"),
        max_base_faces_per_piece=200,
        max_prototype_faces=100,
    )

    first = generate_fracture_preview_from_source_request(
        request,
        settings,
        include_viewport_scene=False,
    )
    assert len(list(cache_root.glob("*.npz"))) == 1
    assert load_count == 1

    def fail_source_load(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Fracture Preview should reuse the typed source cache")

    monkeypatch.setattr(fracture_preview_service, "load_source_tree_model", fail_source_load)
    second = generate_fracture_preview_from_source_request(
        request,
        settings,
        include_viewport_scene=False,
    )

    assert second.plan == first.plan


def test_fracture_preview_source_cache_ignores_legacy_pickle_without_unpickling(monkeypatch, tmp_path) -> None:
    from xml_to_usda import fracture_preview_service

    cache_root = tmp_path / "cache" / "fracture_preview_source_models"
    cache_root.mkdir(parents=True)
    monkeypatch.setattr(fracture_preview_service, "_preview_source_model_cache_root", lambda: cache_root)
    cache_path = fracture_preview_service._preview_source_model_cache_path(str(BIG_SPRUCE))
    called: list[str] = []

    class _Exploit:
        def __reduce__(self):
            return (called.append, ("executed",))

    cache_path.write_bytes(pickle.dumps(_Exploit()))

    assert fracture_preview_service._read_preview_source_model_cache(str(BIG_SPRUCE)) is None
    assert not cache_path.exists()
    assert called == []


def test_fracture_preview_includes_bone_overlay_segments_and_selected_manual_cuts() -> None:
    source_tree = _tree()
    skeleton = list(source_tree.skeleton)
    skeleton[2] = replace(
        skeleton[2],
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 8.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 1.0, 0.0)),
    )
    result = generate_fracture_preview(
        replace(source_tree, skeleton=tuple(skeleton)),
        FracturePreviewSettings(
            fracture=FractureSettings(
                target_piece_count=3,
                output_stem="Oak",
                pinned_cut_joint_tokens=("bone_003",),
            ),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
    )

    assert tuple((segment.parent_joint_token, segment.child_joint_token) for segment in result.bone_segments) == (
        ("root", "bone_001"),
        ("bone_001", "bone_002"),
        ("bone_001", "bone_003"),
        ("bone_003", "bone_004"),
    )
    assert tuple(segment.child_joint_token for segment in result.bone_segments if segment.is_selected_cut) == ("bone_003",)
    assert tuple(cut.joint_token for cut in result.plan.selected_cut_sites) == ("bone_003",)
    bone_002_segment = next(segment for segment in result.bone_segments if segment.child_joint_token == "bone_002")
    assert (bone_002_segment.parent_position.x, bone_002_segment.parent_position.y, bone_002_segment.parent_position.z) == pytest.approx(
        (0.0, 1.0, 0.0)
    )
    assert (bone_002_segment.child_position.x, bone_002_segment.child_position.y, bone_002_segment.child_position.z) == pytest.approx(
        (0.0, 8.0, 0.0)
    )
    piece_color_by_joint = {
        joint_token: piece.color
        for piece in result.pieces
        for joint_token in piece.piece.joint_tokens
    }
    bone_003_segment = next(segment for segment in result.bone_segments if segment.child_joint_token == "bone_003")
    assert bone_003_segment.color == piece_color_by_joint["bone_001"]


def test_fracture_preview_uses_speedtree_bone_end_segments() -> None:
    from xml_to_usda.fracture_viewport_scene import build_fracture_viewport_scene

    source_tree = _tree()
    tip = Vector3(0.0, 2.6, 0.0)
    skeleton = tuple(
        replace(joint, bind_end_transform=Matrix4d.from_translation(tip)) if joint.name == "bone_004" else joint
        for joint in source_tree.skeleton
    )
    source_tree = replace(
        source_tree,
        skeleton=skeleton,
    )

    result = generate_fracture_preview(
        source_tree,
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            max_base_faces_per_piece=1,
            max_prototype_faces=1,
        ),
        include_viewport_scene=False,
    )
    tip_segment = next(segment for segment in result.bone_segments if segment.child_joint_token == "bone_004")
    scene_tip_segment = next(segment for segment in build_fracture_viewport_scene(result).bone_segments if segment.child_token == "bone_004")

    assert tip_segment.parent_joint_token == "bone_003"
    assert tip_segment.selectable is True
    assert tip_segment.parent_position == source_tree.skeleton[-1].bind_translate
    assert tip_segment.child_position == tip
    assert scene_tip_segment.selectable_id == "bone:bone_003->bone_004"


def test_fracture_preview_distributes_target_polycount_between_base_and_repeated_parts() -> None:
    result = generate_fracture_preview(
        _tree_with_repeated_branch_count(25),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            final_polycount=253,
            base_mesh_priority=0.0,
            max_base_faces_per_piece=1,
            max_prototype_faces=120,
        ),
    )

    assert len(result.instances) == 25
    assert sum(piece.base_mesh.face_count for piece in result.pieces) == 3
    assert result.prototypes["Mesh_1"].mesh.face_count == 10


def test_fracture_preview_simplifies_repeated_prototypes_proportionally_to_source_complexity() -> None:
    result = generate_fracture_preview(
        _tree_with_mixed_repeated_prototypes(),
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            final_polycount=333,
            base_mesh_priority=0.0,
            max_base_faces_per_piece=1,
            max_prototype_faces=1000,
        ),
    )

    assert sum(piece.base_mesh.face_count for piece in result.pieces) == 3
    assert result.prototypes["Mesh_small"].mesh.face_count == 30
    assert result.prototypes["Mesh_large"].mesh.face_count == 300


def test_fracture_preview_repeated_instance_count_reduces_per_prototype_budget() -> None:
    tree = _tree_with_mixed_repeated_prototypes()
    heavy_instance_tree = replace(
        tree,
        assembly_parts=(
            _repeated_part("SmallBranch", "bone_002", prototype_key="Mesh_small"),
        )
        + tuple(
            _repeated_part(f"LargeBranch_{index:02d}", "bone_004", prototype_key="Mesh_large")
            for index in range(10)
        ),
    )

    result = generate_fracture_preview(
        heavy_instance_tree,
        FracturePreviewSettings(
            fracture=FractureSettings(target_piece_count=3, output_stem="Oak"),
            final_polycount=1103,
            base_mesh_priority=0.0,
            max_base_faces_per_piece=1,
            max_prototype_faces=1000,
        ),
    )

    assert sum(piece.base_mesh.face_count for piece in result.pieces) == 3
    assert result.prototypes["Mesh_small"].mesh.face_count == 11
    assert result.prototypes["Mesh_large"].mesh.face_count == 109


def test_fracture_preview_fails_loudly_when_repeated_part_references_missing_prototype() -> None:
    with pytest.raises(FractureError, match="missing prototype Mesh_1"):
        generate_fracture_preview(
            replace(_tree(), prototypes=()),
            FracturePreviewSettings(fracture=FractureSettings(target_piece_count=3, output_stem="Oak")),
        )


def test_fracture_preview_from_conversion_request_uses_source_xml_geometry_not_operator_replacements(
    monkeypatch,
    tmp_path,
) -> None:
    from xml_to_usda import fracture_preview_service

    observed: dict[str, object] = {}
    cache_root = tmp_path / "cache" / "fracture_preview_source_models"
    monkeypatch.setattr(fracture_preview_service, "_preview_source_model_cache_root", lambda: cache_root)

    def fake_load_source_tree_model(input_path, *, source_cache_enabled=True, telemetry_callback=None, cancel_event=None):
        observed["input_path"] = input_path
        observed["source_cache_enabled"] = source_cache_enabled
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

    source_request = FracturePreviewSourceRequest.from_conversion_request(request)

    assert not hasattr(source_request, "prototype_source_configs")
    assert not hasattr(source_request, "udim_material_settings")
    assert not hasattr(source_request, "material_policy")

    result = generate_fracture_preview_from_source_request(
        source_request,
        FracturePreviewSettings(fracture=FractureSettings(target_piece_count=2)),
    )

    assert observed["input_path"] == "tree.xml"
    assert observed["source_cache_enabled"] is False
    assert result.plan.output_stem == "Oak"
    assert tuple(piece.piece.name for piece in result.pieces) == (
        "Oak_fracture_00",
        "Oak_fracture_01",
        "Oak_fracture_02",
    )
