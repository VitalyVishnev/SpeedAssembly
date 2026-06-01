from __future__ import annotations

from array import array
from dataclasses import replace

import pytest

from xml_to_usda.models import (
    ConversionRequest,
    ExportMetadata,
    FbxMaterialMode,
    GeometryBuffer,
    InstanceBinding,
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
from xml_to_usda.proxy_mesh_service import (
    ProxyMeshError,
    ProxyMeshSettings,
    derive_proxy_usda_output_path,
    export_proxy_usda_from_request,
    export_proxy_usda,
    generate_proxy_mesh_from_request,
    generate_proxy_mesh,
    render_proxy_usda,
)


def _triangle_mesh(name: str) -> MeshData:
    return MeshData(
        name=name,
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
    )


def _buffer_mesh(name: str) -> GeometryBuffer:
    return GeometryBuffer(
        name=name,
        point_components=array("f", [0.0, 0.0, 0.0, 0.5, 0.0, 0.0, 0.0, 0.5, 0.0]),
        face_vertex_counts=array("i", [3]),
        face_vertex_indices=array("i", [0, 1, 2]),
    )


def _strip_mesh(name: str, triangle_count: int) -> MeshData:
    points: list[Vector3] = []
    face_indices: list[int] = []
    for index in range(triangle_count):
        base = len(points)
        x = float(index)
        points.extend(
            (
                Vector3(x, -2.0, 0.0),
                Vector3(x + 0.8, -2.0, 0.0),
                Vector3(x, -1.2, 0.0),
            )
        )
        face_indices.extend((base, base + 1, base + 2))
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=(3,) * triangle_count,
        face_vertex_indices=tuple(face_indices),
    )


def _model(*, repeated_count: int = 2, prototype_payload: MeshData | GeometryBuffer | None = None) -> TreeAsset:
    if prototype_payload is None:
        prototype_payload = _triangle_mesh("LeafCluster")
    prototype_mesh = prototype_payload if isinstance(prototype_payload, MeshData) else None
    prototype_buffer = prototype_payload if isinstance(prototype_payload, GeometryBuffer) else None
    return TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=_triangle_mesh("Base"),
        skeleton=(),
        assembly_parts=tuple(
            RepeatedPartInstance(
                name=f"Leaf_{index}",
                prototype_key="Mesh_7",
                position=Vector3(float(index * 2), 0.0, 0.0),
                orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
                scale=Vector3(1.0, 1.0, 1.0),
                binding=InstanceBinding(joint_tokens=(), weights=()),
                source_object_id=None,
                source_mesh_id=7,
            )
            for index in range(repeated_count)
        ),
        prototypes=(
            Prototype(
                identity=PrototypeIdentity(source_key="Mesh_7", prim_name="LeafCluster"),
                mesh=prototype_mesh,
                source_key="Mesh_7",
                source_mesh_id=7,
                source_name="LeafCluster",
                geometry_payload=prototype_buffer,
            ),
        ),
    )


def test_proxy_output_path_is_sibling_of_main_usda_or_input_fallback(tmp_path) -> None:
    input_path = tmp_path / "src" / "oak.xml"
    output_path = tmp_path / "exports" / "HeroTree.usda"

    assert derive_proxy_usda_output_path(str(input_path), str(output_path)) == output_path.with_name("HeroTree_proxy.usda")
    assert derive_proxy_usda_output_path(str(input_path), "") == input_path.with_name("oak_proxy.usda")


def test_density_field_proxy_is_default_and_includes_all_repeated_parts() -> None:
    result = generate_proxy_mesh(_model(repeated_count=3), ProxyMeshSettings(final_polycount=5000))

    assert result.method == "density_field"
    assert result.source_instance_count == 3
    assert result.mesh.name == "ProxyMesh"
    assert result.mesh.face_count <= 5000
    assert result.mesh.point_count > 0


def test_proxy_generation_uses_resolved_geometry_buffer_payloads() -> None:
    result = generate_proxy_mesh(
        _model(repeated_count=1, prototype_payload=_buffer_mesh("ResolvedBranch")),
        ProxyMeshSettings(final_polycount=5000),
    )

    assert result.source_instance_count == 1
    assert result.method == "density_field"
    assert result.mesh.face_count <= 5000
    assert result.mesh.point_count > 0


def test_density_field_keeps_base_mesh_as_direct_geometry() -> None:
    base_only = replace(_model(repeated_count=0), prototypes=())

    result = generate_proxy_mesh(base_only, ProxyMeshSettings(final_polycount=5000))

    assert result.included_base_mesh is True
    assert result.source_instance_count == 0
    assert result.mesh.face_count == 1
    assert tuple(round(float(value), 6) for value in result.mesh.point_components) == (
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
    )


def test_density_field_extracts_shared_foliage_surface_for_qem() -> None:
    foliage_only = replace(_model(repeated_count=1), base_mesh=None)

    result = generate_proxy_mesh(foliage_only, ProxyMeshSettings(final_polycount=5000, density_resolution=12))

    assert result.included_base_mesh is False
    assert result.mesh.face_count > 0
    assert result.mesh.point_count < result.mesh.face_count


def test_proxy_generation_fails_loudly_when_source_facts_are_missing() -> None:
    broken = replace(_model(repeated_count=1), prototypes=())

    with pytest.raises(ProxyMeshError, match="Missing resolved prototype"):
        generate_proxy_mesh(broken, ProxyMeshSettings(final_polycount=5000))


def test_proxy_generation_fails_loudly_when_repeated_part_orientation_is_malformed() -> None:
    model = _model(repeated_count=1)
    broken_part = replace(model.repeated_parts[0], orientation=Quaternion(1.0, float, 0.0, 0.0))
    broken = replace(model, assembly_parts=(broken_part,))

    with pytest.raises(ProxyMeshError, match="malformed orientation quaternion"):
        generate_proxy_mesh(broken, ProxyMeshSettings(final_polycount=5000, density_resolution=128))


def test_base_mesh_priority_controls_base_simplification_budget() -> None:
    model = replace(_model(repeated_count=1), base_mesh=_strip_mesh("BaseStrip", 24))

    low_priority = generate_proxy_mesh(
        model,
        ProxyMeshSettings(final_polycount=30, density_resolution=12, base_mesh_priority=0.05),
    )
    high_priority = generate_proxy_mesh(
        model,
        ProxyMeshSettings(final_polycount=30, density_resolution=12, base_mesh_priority=0.95),
    )

    assert _mesh_signature(low_priority.mesh) != _mesh_signature(high_priority.mesh)


def test_proxy_generation_rejects_invalid_base_mesh_priority() -> None:
    with pytest.raises(ProxyMeshError, match="base mesh priority"):
        generate_proxy_mesh(_model(repeated_count=1), ProxyMeshSettings(base_mesh_priority=1.5))


def test_proxy_generation_saturates_when_budget_is_below_reachable_mesh_minimum() -> None:
    result = generate_proxy_mesh(_model(repeated_count=2), ProxyMeshSettings(final_polycount=1))

    assert result.mesh.face_count >= 1
    assert result.mesh.point_count > 0


def test_proxy_generation_saturates_when_budget_is_above_extracted_surface() -> None:
    result = generate_proxy_mesh(_model(repeated_count=2), ProxyMeshSettings(final_polycount=500_000))

    assert result.mesh.face_count > 0
    assert result.mesh.face_count < 500_000


def test_density_field_simplifies_extracted_surface_with_qem() -> None:
    result = generate_proxy_mesh(
        _model(repeated_count=6),
        ProxyMeshSettings(final_polycount=36, density_resolution=18),
    )

    assert result.method == "density_field"
    assert result.mesh.face_count <= 36
    assert set(result.mesh.face_vertex_counts) == {3}


def test_proxy_generation_is_deterministic_for_same_input_and_settings() -> None:
    settings = ProxyMeshSettings(final_polycount=48, density_resolution=18, bounds_inflation=1.15)
    first = generate_proxy_mesh(_model(repeated_count=6), settings)
    second = generate_proxy_mesh(_model(repeated_count=6), settings)

    assert _mesh_signature(first.mesh) == _mesh_signature(second.mesh)


def test_proxy_export_writes_the_same_generated_mesh_it_returns(tmp_path) -> None:
    settings = ProxyMeshSettings(final_polycount=48, density_resolution=18, bounds_inflation=1.15)
    result = export_proxy_usda(
        _model(repeated_count=6),
        input_path=str(tmp_path / "tree.xml"),
        output_path=str(tmp_path / "exports" / "HeroTree.usda"),
        settings=settings,
    )

    expected_usda = render_proxy_usda(result.proxy, root_name="HeroTree_proxy")
    assert result.output_path == str(tmp_path / "exports" / "HeroTree_proxy.usda")
    assert result.usda_text == expected_usda
    assert (tmp_path / "exports" / "HeroTree_proxy.usda").read_text(encoding="utf-8") == expected_usda


def test_proxy_request_generation_ignores_operator_fbx_replacement(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_load_canonical_model(input_path, output_mode, **kwargs):
        calls["input_path"] = input_path
        calls["kwargs"] = kwargs
        return object(), _model(repeated_count=1), ()

    monkeypatch.setattr("xml_to_usda.proxy_mesh_service.load_canonical_model", fake_load_canonical_model)
    request = ConversionRequest(
        input_paths=("tree.xml",),
        output_path="tree.usda",
        use_explicit_material_contract=True,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_7",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path="heavy_replacement.fbx",
                fbx_material_mode=FbxMaterialMode.VERTEX_COLOR_SPLIT,
            ),
        ),
    )

    result = generate_proxy_mesh_from_request(request, ProxyMeshSettings(final_polycount=5000))

    assert result.mesh.face_count > 0
    assert calls["input_path"] == "tree.xml"
    assert "prototype_source_configs" not in calls["kwargs"]
    assert "use_explicit_material_contract" not in calls["kwargs"]


def test_proxy_request_export_ignores_operator_fbx_replacement(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_load_canonical_model(input_path, output_mode, **kwargs):
        calls["kwargs"] = kwargs
        return object(), _model(repeated_count=1), ()

    monkeypatch.setattr("xml_to_usda.proxy_mesh_service.load_canonical_model", fake_load_canonical_model)
    request = ConversionRequest(
        input_paths=("tree.xml",),
        output_path=str(tmp_path / "tree.usda"),
        use_explicit_material_contract=True,
        prototype_source_configs=(
            PrototypeSourceConfig(
                source_key="Mesh_7",
                mode=PrototypeSourceMode.FBX_FILE,
                fbx_path="heavy_replacement.fbx",
            ),
        ),
    )

    result = export_proxy_usda_from_request(request, ProxyMeshSettings(final_polycount=5000))

    assert result.output_path == str(tmp_path / "tree_proxy.usda")
    assert "prototype_source_configs" not in calls["kwargs"]
    assert "use_explicit_material_contract" not in calls["kwargs"]


def test_instance_bounds_method_remains_explicit_debug_baseline() -> None:
    result = generate_proxy_mesh(
        _model(repeated_count=1),
        ProxyMeshSettings(method="instance_bounds", final_polycount=5000),
    )

    assert result.method == "instance_bounds"
    assert result.mesh.face_count == 12


def test_proxy_usda_is_single_geometry_mesh_without_assembly_contract() -> None:
    result = generate_proxy_mesh(_model(repeated_count=1), ProxyMeshSettings(final_polycount=5000))
    usda = render_proxy_usda(result, root_name="Tree_proxy")

    assert 'def Mesh "ProxyMesh"' in usda
    assert "PointInstancer" not in usda
    assert "SkelRoot" not in usda
    assert "NaniteAssembly" not in usda
    assert "material:binding" not in usda
    assert "int[] faceVertexCounts" in usda


def _mesh_signature(mesh: GeometryBuffer) -> tuple[tuple[float, ...], tuple[int, ...], tuple[int, ...]]:
    return (
        tuple(round(float(value), 7) for value in mesh.point_components),
        tuple(int(value) for value in mesh.face_vertex_counts),
        tuple(int(value) for value in mesh.face_vertex_indices),
    )
