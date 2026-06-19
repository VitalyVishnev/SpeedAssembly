from __future__ import annotations

import ast
from array import array
from pathlib import Path

import pytest

from xml_to_usda.fracture_preview_service import (
    FracturePreviewBoneSegment,
    FracturePreviewInstance,
    FracturePreviewPiece,
    FracturePreviewPrototype,
    FracturePreviewResult,
)
from xml_to_usda.fracture_service import (
    FRACTURE_METHOD_MANUAL_FRACTURING,
    FractureCutSite,
    FracturePiece,
    FracturePlan,
)
from xml_to_usda.fracture_viewport_scene import build_fracture_viewport_scene
from xml_to_usda.models import Color4, GeometryBuffer, Quaternion, Vector3
from xml_to_usda.proxy_mesh_service import PROXY_METHOD_DENSITY_FIELD, ProxyMeshResult, ProxyMeshSettings
from xml_to_usda.proxy_viewport_scene import build_proxy_viewport_scene
from xml_to_usda.viewport_scene import ViewportDrawCall, ViewportMeshBatch, geometry_bounds, geometry_triangle_count, transformed_draw_bounds


def test_viewport_scene_modules_do_not_import_qt() -> None:
    for path in (
        Path("src/xml_to_usda/viewport_scene.py"),
        Path("src/xml_to_usda/proxy_viewport_scene.py"),
        Path("src/xml_to_usda/fracture_viewport_scene.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported_roots: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.append(node.module.split(".", 1)[0])
        assert "PySide6" not in imported_roots


def test_geometry_helpers_report_triangle_count_and_bounds() -> None:
    mesh = _mesh(
        "quad",
        points=(0.0, 1.0, 2.0, 2.0, 1.0, 2.0, 2.0, 3.0, 2.0, 0.0, 3.0, 2.0),
        counts=(4,),
        indices=(0, 1, 2, 3),
    )

    assert geometry_triangle_count(mesh) == 2
    bounds = geometry_bounds((mesh,))
    assert bounds.min_point == Vector3(0.0, 1.0, 2.0)
    assert bounds.max_point == Vector3(2.0, 3.0, 2.0)
    assert bounds.center == Vector3(1.0, 2.0, 2.0)


def test_transformed_draw_bounds_apply_draw_call_transform() -> None:
    batch = ViewportMeshBatch(
        batch_id="batch",
        name="batch",
        mesh=_triangle_mesh("batch"),
    )
    bounds = transformed_draw_bounds(
        (batch,),
        (
            ViewportDrawCall(
                draw_id="draw",
                batch_id="batch",
                translate=Vector3(10.0, 0.0, 0.0),
                orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
                scale=Vector3(2.0, 3.0, 1.0),
            ),
        ),
    )

    assert bounds.min_point == Vector3(10.0, 0.0, 0.0)
    assert bounds.max_point == Vector3(12.0, 3.0, 0.0)


def test_transformed_draw_bounds_support_rotated_nonuniform_batches() -> None:
    batch = ViewportMeshBatch(
        batch_id="batch",
        name="batch",
        mesh=_mesh(
            "box",
            points=(
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                1.0,
                0.0,
                1.0,
                0.0,
                1.0,
                1.0,
                1.0,
                1.0,
                1.0,
            ),
            counts=(4, 4, 4, 4, 4, 4),
            indices=(0, 1, 2, 3, 4, 5, 6, 7, 0, 1, 5, 4, 2, 3, 7, 6, 0, 2, 6, 4, 1, 3, 7, 5),
        ),
    )
    bounds = transformed_draw_bounds(
        (batch,),
        (
            ViewportDrawCall(
                draw_id="draw",
                batch_id="batch",
                translate=Vector3(10.0, 20.0, 30.0),
                orientation=Quaternion(0.7071067811865476, 0.0, 0.0, 0.7071067811865476),
                scale=Vector3(2.0, 3.0, 4.0),
            ),
        ),
    )

    assert bounds.min_point.x == pytest.approx(7.0)
    assert bounds.min_point.y == pytest.approx(20.0)
    assert bounds.min_point.z == pytest.approx(30.0)
    assert bounds.max_point == Vector3(10.0, 22.0, 34.0)


def test_proxy_viewport_scene_is_deterministic() -> None:
    proxy = ProxyMeshResult(
        mesh=_triangle_mesh("ProxyMesh"),
        settings=ProxyMeshSettings(),
        method=PROXY_METHOD_DENSITY_FIELD,
        source_instance_count=7,
        included_base_mesh=True,
    )

    first = build_proxy_viewport_scene(proxy)
    second = build_proxy_viewport_scene(proxy)

    assert first == second
    assert first.scene_id == "ProxyMesh:proxy_preview"
    assert [batch.batch_id for batch in first.mesh_batches] == ["proxy:mesh"]
    assert [draw.draw_id for draw in first.draw_calls] == ["proxy:mesh:0"]
    assert first.stats.uploaded_triangles == 1
    assert first.stats.logical_triangles == 1


def test_fracture_viewport_scene_has_stable_ids_stats_and_overlays() -> None:
    preview = _fracture_preview()

    scene = build_fracture_viewport_scene(preview)

    assert [batch.batch_id for batch in scene.mesh_batches] == [
        "fracture:piece:00:base",
        "fracture:piece:01:base",
        "fracture:piece:01:prototype:leaf",
    ]
    assert [draw.draw_id for draw in scene.draw_calls] == [
        "fracture:piece:00:base:draw",
        "fracture:piece:01:base:draw",
        "fracture:instance:leaf_002",
    ]
    assert scene.scene_id == "Tree_fracture_preview"
    assert scene.stats.uploaded_triangles == 3
    assert scene.stats.logical_triangles == 3
    assert scene.stats.instance_count == 1
    assert [segment.segment_id for segment in scene.bone_segments] == ["bone:root->branch"]
    assert scene.bone_segments[0].selected is True
    assert [marker.marker_id for marker in scene.markers] == ["cut:root->branch@0.500"]
    assert scene.markers[0].position == Vector3(0.0, 1.0, 0.0)
    assert scene.labels[0].text == "root->branch@0.500"


def test_fracture_viewport_scene_can_hide_repeated_parts_without_changing_base_batches() -> None:
    preview = _fracture_preview()

    scene = build_fracture_viewport_scene(preview, include_repeated_parts=False)

    assert [batch.batch_id for batch in scene.mesh_batches] == [
        "fracture:piece:00:base",
        "fracture:piece:01:base",
    ]
    assert all(draw.visibility_group == "base_mesh" for draw in scene.draw_calls)
    assert scene.stats.instance_count == 0
    assert scene.stats.uploaded_triangles == 2
    assert scene.stats.logical_triangles == 2


def _fracture_preview() -> FracturePreviewResult:
    root_piece = FracturePiece(
        index=0,
        name="Tree_fracture_00",
        is_root_piece=True,
        cut_joint_token=None,
        joint_tokens=("root",),
        base_face_indices=(0,),
        repeated_part_indices=(),
        repeated_part_names=(),
    )
    branch_piece = FracturePiece(
        index=1,
        name="Tree_fracture_01",
        is_root_piece=False,
        cut_joint_token="root->branch@0.500",
        joint_tokens=("branch",),
        base_face_indices=(1,),
        repeated_part_indices=(0,),
        repeated_part_names=("leaf_002",),
    )
    cut_site = FractureCutSite(
        joint_token="root->branch@0.500",
        kind="manual_segment",
        reason="manual_pinned_segment",
        parent_joint_token="root",
        child_joint_token="branch",
        segment_t=0.5,
    )
    return FracturePreviewResult(
        plan=FracturePlan(
            method=FRACTURE_METHOD_MANUAL_FRACTURING,
            requested_piece_count=2,
            actual_piece_count=2,
            output_stem="Tree",
            main_axis_joint_tokens=("root", "branch"),
            selected_cut_sites=(cut_site,),
            rejected_cut_sites=(),
            pieces=(root_piece, branch_piece),
        ),
        pieces=(
            FracturePreviewPiece(piece=root_piece, color=Color4(1.0, 0.0, 0.0, 1.0), base_mesh=_triangle_mesh("root")),
            FracturePreviewPiece(piece=branch_piece, color=Color4(0.0, 1.0, 0.0, 1.0), base_mesh=_triangle_mesh("branch")),
        ),
        prototypes={
            "leaf": FracturePreviewPrototype(
                source_key="leaf",
                source_name="Leaf",
                mesh=_triangle_mesh("leaf"),
            )
        },
        instances=(
            FracturePreviewInstance(
                name="leaf_002",
                piece_index=1,
                prototype_key="leaf",
                position=Vector3(1.0, 0.0, 0.0),
                orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
                scale=Vector3(1.0, 1.0, 1.0),
                color=Color4(0.0, 1.0, 0.0, 1.0),
            ),
        ),
        diagnostics=(),
        bone_segments=(
            FracturePreviewBoneSegment(
                parent_joint_token="root",
                child_joint_token="branch",
                parent_position=Vector3(0.0, 0.0, 0.0),
                child_position=Vector3(0.0, 2.0, 0.0),
                is_selected_cut=True,
                color=Color4(0.2, 0.8, 1.0, 1.0),
            ),
        ),
    )


def _triangle_mesh(name: str) -> GeometryBuffer:
    return _mesh(
        name,
        points=(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0),
        counts=(3,),
        indices=(0, 1, 2),
    )


def _mesh(name: str, *, points: tuple[float, ...], counts: tuple[int, ...], indices: tuple[int, ...]) -> GeometryBuffer:
    return GeometryBuffer(
        name=name,
        point_components=array("f", points),
        face_vertex_counts=array("i", counts),
        face_vertex_indices=array("i", indices),
    )
