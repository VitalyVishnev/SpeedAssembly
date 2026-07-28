from __future__ import annotations

import pickle
import sys
from array import array
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from xml_to_usda.canonical_loader import load_canonical_model
from xml_to_usda.models import (
    ConversionRequest,
    ExportMetadata,
    GeometryBuffer,
    InstanceBinding,
    MeshData,
    Prototype,
    PrototypeIdentity,
    Quaternion,
    RepeatedPartInstance,
    TreeAsset,
    Vector3,
)
from xml_to_usda.proxy_mesh_service import (
    ProxyMeshError,
    ProxyMeshJobResult,
    ProxyMeshSettings,
    ProxyMeshSourceRequest,
    _base_proxy_geometry_buffer,
    derive_proxy_usda_output_path,
    export_proxy_usda_from_source_request,
    export_proxy_usda,
    generate_proxy_mesh_from_source_request,
    generate_proxy_mesh,
    render_proxy_usda,
)
from xml_to_usda.proxy_source_projection import (
    ProxySourceProjection,
    _proxy_projection_cache_path,
    _read_proxy_projection_cache,
    load_proxy_source_projection,
    projection_to_tree_asset,
)


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)
BIG_SPRUCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "BigSpruce"
    / "SkeletalAssemblyTest_Spruce_Big_low.xml"
)
LEAFREFS_ON_BRANCH_LEVELS = Path(__file__).parent / "data" / "leafrefs_on_branch_levels.xml"


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


def test_proxy_generation_rejects_density_resolution_above_service_cap() -> None:
    empty_model = TreeAsset(
        metadata=ExportMetadata(source_path="tree.xml", source_version=None),
        materials=(),
        source_objects=(),
        base_mesh=None,
        skeleton=(),
        assembly_parts=(),
    )

    with pytest.raises(ProxyMeshError, match="must be between 1 and 256"):
        generate_proxy_mesh(empty_model, ProxyMeshSettings(density_resolution=257))


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


def _quad_grid_mesh(name: str, width: int, height: int) -> MeshData:
    points: list[Vector3] = []
    for y in range(height + 1):
        for x in range(width + 1):
            points.append(Vector3(float(x), 0.0, float(y)))
    face_counts: list[int] = []
    face_indices: list[int] = []
    row_width = width + 1
    for y in range(height):
        for x in range(width):
            lower_left = y * row_width + x
            lower_right = lower_left + 1
            upper_left = lower_left + row_width
            upper_right = upper_left + 1
            face_counts.append(4)
            face_indices.extend((lower_left, lower_right, upper_right, upper_left))
    return MeshData(
        name=name,
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
    )


def _branchy_base_mesh_with_tiny_terminal_parts() -> MeshData:
    points: list[Vector3] = []
    face_counts: list[int] = []
    face_indices: list[int] = []

    def add_face(face_points: tuple[Vector3, ...]) -> None:
        point_offset = len(points)
        points.extend(face_points)
        face_counts.append(len(face_points))
        face_indices.extend(range(point_offset, point_offset + len(face_points)))

    add_face(
        (
            Vector3(-2.0, 0.0, -1.0),
            Vector3(2.0, 0.0, -1.0),
            Vector3(2.0, 12.0, -1.0),
            Vector3(-2.0, 12.0, -1.0),
        ),
    )
    add_face(
        (
            Vector3(0.0, 8.0, -0.5),
            Vector3(8.0, 11.0, -0.5),
            Vector3(8.0, 12.0, -0.5),
            Vector3(0.0, 9.0, -0.5),
        ),
    )
    for index in range(80):
        x = 20.0 + index * 0.1
        add_face(
            (
                Vector3(x, 16.0, 0.0),
                Vector3(x + 0.02, 16.0, 0.0),
                Vector3(x, 16.02, 0.0),
            ),
        )

    return MeshData(
        name="BranchyBase",
        points=tuple(points),
        face_vertex_counts=tuple(face_counts),
        face_vertex_indices=tuple(face_indices),
    )


def _split_base_mesh_with_nearby_seam() -> MeshData:
    return MeshData(
        name="SplitBase",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(1.0005, 0.0, 0.0),
            Vector3(0.0, 1.0005, 0.0),
            Vector3(1.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 3, 5, 4),
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


def test_proxy_job_result_is_stable_worker_envelope() -> None:
    result = ProxyMeshJobResult(error_message="preview failed")
    restored = pickle.loads(pickle.dumps(result))

    assert restored.proxy is None
    assert restored.export is None
    assert restored.cancelled is False
    assert restored.error_message == "preview failed"


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


def test_proxy_generation_rejects_invalid_topology_before_qem(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "fast_simplification",
        SimpleNamespace(simplify=lambda *_args, **_kwargs: pytest.fail("QEM should not receive invalid topology")),
    )
    broken_base = MeshData(
        name="BrokenBase",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(1.0, 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 99),
    )
    broken = replace(_model(repeated_count=0), base_mesh=broken_base, prototypes=())

    with pytest.raises(ProxyMeshError, match="references point 99 outside the mesh"):
        generate_proxy_mesh(broken, ProxyMeshSettings(final_polycount=1))


def test_proxy_generation_rejects_non_finite_points_before_qem(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "fast_simplification",
        SimpleNamespace(simplify=lambda *_args, **_kwargs: pytest.fail("QEM should not receive non-finite points")),
    )
    broken_base = MeshData(
        name="NanBase",
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(1.0, 0.0, 0.0),
            Vector3(0.0, 1.0, 0.0),
            Vector3(float("nan"), 1.0, 0.0),
        ),
        face_vertex_counts=(3, 3),
        face_vertex_indices=(0, 1, 2, 0, 2, 3),
    )
    broken = replace(_model(repeated_count=0), base_mesh=broken_base, prototypes=())

    with pytest.raises(ProxyMeshError, match="contains non-finite point coordinates"):
        generate_proxy_mesh(broken, ProxyMeshSettings(final_polycount=1))


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


def test_base_mesh_prefilter_passes_percent_prune_setting_before_qem(monkeypatch: pytest.MonkeyPatch) -> None:
    model = replace(_model(repeated_count=1), base_mesh=_branchy_base_mesh_with_tiny_terminal_parts(), skeleton=())
    calls: dict[str, object] = {}

    def fake_select_large_connected_face_indices(
        mesh: MeshData,
        *,
        aggression: float,
        candidate_face_indices: tuple[int, ...] | None = None,
    ) -> tuple[int, ...]:
        calls["mesh"] = mesh
        calls["aggression"] = aggression
        calls["candidate_face_indices"] = candidate_face_indices
        return (0, 1)

    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_service.select_large_connected_face_indices",
        fake_select_large_connected_face_indices,
    )

    result = generate_proxy_mesh(
        model,
        ProxyMeshSettings(
            final_polycount=20,
            density_resolution=12,
            base_mesh_priority=0.5,
            branch_prune_aggression=0.01,
        ),
    )

    assert result.included_base_mesh is True
    assert calls["mesh"] is model.base_mesh
    assert calls["aggression"] == pytest.approx(0.01)
    assert calls["candidate_face_indices"] is None


def test_base_mesh_fuse_welds_nearby_seams_after_component_pruning(monkeypatch: pytest.MonkeyPatch) -> None:
    model = replace(_model(repeated_count=1), base_mesh=_split_base_mesh_with_nearby_seam(), skeleton=())
    calls: dict[str, MeshData] = {}

    def capture_pruned_mesh(
        mesh: MeshData,
        *,
        aggression: float,
        candidate_face_indices: tuple[int, ...] | None = None,
    ) -> None:
        calls["mesh"] = mesh
        return None

    monkeypatch.setattr(
        "xml_to_usda.proxy_mesh_service.select_large_connected_face_indices",
        capture_pruned_mesh,
    )

    fused = _base_proxy_geometry_buffer(
        model,
        settings=ProxyMeshSettings(fuse_base_mesh_vertices=True),
        has_foliage=True,
    )

    assert calls["mesh"] is model.base_mesh
    assert fused.point_count == 4
    assert tuple(fused.face_vertex_counts) == (3, 3)
    assert set(fused.face_vertex_indices[:3]) & set(fused.face_vertex_indices[3:]) == {1, 2}


def test_proxy_generation_rejects_invalid_branch_prune_aggression() -> None:
    with pytest.raises(ProxyMeshError, match="branch prune aggression"):
        generate_proxy_mesh(_model(repeated_count=1), ProxyMeshSettings(branch_prune_aggression=1.5))


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


def test_proxy_simplification_keeps_connected_surface_instead_of_sampling_triangle_cloud() -> None:
    source = _quad_grid_mesh("ConnectedBase", 18, 18)
    base_only = replace(_model(repeated_count=0), base_mesh=source, prototypes=())

    result = generate_proxy_mesh(base_only, ProxyMeshSettings(final_polycount=40))

    assert result.mesh.face_count <= 40
    assert result.mesh.point_count < len(source.points)
    assert _unused_point_count(result.mesh) == 0
    assert _triangle_component_count(result.mesh) == 1


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


def test_proxy_request_generation_uses_proxy_source_projection(monkeypatch) -> None:
    calls: dict[str, object] = {}

    def fake_load_proxy_source_projection(input_path):
        calls["input_path"] = input_path
        return ProxySourceProjection(
            source_path=input_path,
            base_mesh=_triangle_mesh("Base"),
            prototypes=_model(repeated_count=1).prototypes,
            repeated_parts=_model(repeated_count=1).repeated_parts,
        )

    monkeypatch.setattr("xml_to_usda.proxy_mesh_service.load_proxy_source_projection", fake_load_proxy_source_projection)
    request = ConversionRequest(input_paths=("tree.xml",), output_path="tree.usda")

    source_request = ProxyMeshSourceRequest.from_conversion_request(request)
    result = generate_proxy_mesh_from_source_request(source_request, ProxyMeshSettings(final_polycount=5000))

    assert result.mesh.face_count > 0
    assert calls["input_path"] == "tree.xml"


def test_proxy_request_export_uses_proxy_source_projection(monkeypatch, tmp_path) -> None:
    calls: dict[str, object] = {}

    def fake_load_proxy_source_projection(input_path):
        calls["input_path"] = input_path
        return ProxySourceProjection(
            source_path=input_path,
            base_mesh=_triangle_mesh("Base"),
            prototypes=_model(repeated_count=1).prototypes,
            repeated_parts=_model(repeated_count=1).repeated_parts,
        )

    monkeypatch.setattr("xml_to_usda.proxy_mesh_service.load_proxy_source_projection", fake_load_proxy_source_projection)
    request = ConversionRequest(input_paths=("tree.xml",), output_path=str(tmp_path / "tree.usda"))

    source_request = ProxyMeshSourceRequest.from_conversion_request(request)
    result = export_proxy_usda_from_source_request(source_request, ProxyMeshSettings(final_polycount=5000))

    assert result.output_path == str(tmp_path / "tree_proxy.usda")
    assert calls["input_path"] == "tree.xml"


@pytest.mark.parametrize("source_path", (SIMPLE_TREE_01, BIG_SPRUCE, LEAFREFS_ON_BRANCH_LEVELS))
def test_proxy_source_projection_matches_canonical_proxy_inputs(source_path: Path) -> None:
    settings = ProxyMeshSettings(final_polycount=5000, density_resolution=64, branch_prune_aggression=0.98)
    _report, canonical_model, diagnostics = load_canonical_model(str(source_path), source_cache_enabled=False)
    assert not [issue for issue in diagnostics if issue.severity == "error"]

    projection_model = projection_to_tree_asset(load_proxy_source_projection(str(source_path)))

    canonical = generate_proxy_mesh(canonical_model, settings)
    projected = generate_proxy_mesh(projection_model, settings)

    assert _mesh_signature(projected.mesh) == _mesh_signature(canonical.mesh)
    assert projected.source_instance_count == canonical.source_instance_count


def test_proxy_source_projection_reuses_typed_cache(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda import proxy_source_projection

    cache_root = tmp_path / "cache" / "proxy_source_projections"
    monkeypatch.setattr(proxy_source_projection, "_proxy_projection_cache_root", lambda: cache_root)

    first = load_proxy_source_projection(str(BIG_SPRUCE))
    cache_files = list(cache_root.glob("*.npz"))
    assert len(cache_files) == 1
    assert cache_files[0].stat().st_size > 0

    def fail_read_source_xml(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("source XML should not be reread when the Proxy Source Projection cache is warm")

    monkeypatch.setattr(proxy_source_projection, "read_source_xml", fail_read_source_xml)

    second = load_proxy_source_projection(str(BIG_SPRUCE))

    settings = ProxyMeshSettings(final_polycount=5000, density_resolution=64, branch_prune_aggression=0.98)
    assert _mesh_signature(generate_proxy_mesh(projection_to_tree_asset(second), settings).mesh) == _mesh_signature(
        generate_proxy_mesh(projection_to_tree_asset(first), settings).mesh
    )


def test_proxy_source_projection_cache_ignores_legacy_pickle_without_unpickling(monkeypatch, tmp_path: Path) -> None:
    from xml_to_usda import proxy_source_projection

    cache_root = tmp_path / "cache" / "proxy_source_projections"
    cache_root.mkdir(parents=True)
    monkeypatch.setattr(proxy_source_projection, "_proxy_projection_cache_root", lambda: cache_root)
    cache_path = _proxy_projection_cache_path(str(BIG_SPRUCE))
    called: list[str] = []

    class _Exploit:
        def __reduce__(self):
            return (called.append, ("executed",))

    cache_path.write_bytes(pickle.dumps(_Exploit()))

    assert _read_proxy_projection_cache(cache_path) is None
    assert not cache_path.exists()
    assert called == []


def test_proxy_source_request_rejects_batch_conversion_request() -> None:
    with pytest.raises(ProxyMeshError, match="exactly one input XML"):
        ProxyMeshSourceRequest.from_conversion_request(ConversionRequest(input_paths=("a.xml", "b.xml")))


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


def _unused_point_count(mesh: GeometryBuffer) -> int:
    used = {int(index) for index in mesh.face_vertex_indices}
    return mesh.point_count - len(used)


def _triangle_component_count(mesh: GeometryBuffer) -> int:
    triangles: list[tuple[int, int, int]] = []
    offset = 0
    for count in mesh.face_vertex_counts:
        face = tuple(int(mesh.face_vertex_indices[offset + index]) for index in range(count))
        offset += count
        if count == 3:
            triangles.append(face)
            continue
        for index in range(1, count - 1):
            triangles.append((face[0], face[index], face[index + 1]))
    if not triangles:
        return 0
    by_vertex: dict[int, list[int]] = {}
    for triangle_index, triangle in enumerate(triangles):
        for vertex_index in triangle:
            by_vertex.setdefault(vertex_index, []).append(triangle_index)
    seen: set[int] = set()
    components = 0
    for triangle_index in range(len(triangles)):
        if triangle_index in seen:
            continue
        components += 1
        stack = [triangle_index]
        seen.add(triangle_index)
        while stack:
            current = stack.pop()
            for vertex_index in triangles[current]:
                for neighbor in by_vertex[vertex_index]:
                    if neighbor not in seen:
                        seen.add(neighbor)
                        stack.append(neighbor)
    return components
