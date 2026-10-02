"""Frozen pre-migration FBX contracts for user-supplied real assets.

The assets stay outside the repository for licensing/size reasons. The tests
run automatically when the documented local paths are available and skip in a
clean clone. Goldens capture the geometry/material/skeleton semantics from the
former backend; ufbx may choose a different but deterministic triangulation.
"""

from __future__ import annotations

from array import array
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import xml_to_usda.fbx_adapter as fbx_adapter
from xml_to_usda.fbx_adapter import FbxImportError, _geometry_from_native_payload, inspect_fbx_material_slots, load_fbx_geometry, load_fbx_skeletal_preview, load_fbx_skeleton
from xml_to_usda.models import CpuProfile


_REAL_ASSETS = {
    "Twig_01": Path(r"D:\3D Personal\XMLtoUSD_miscFiles\Twig_01.fbx"),
    "FernLeaf": Path(r"D:\3D Personal\XMLtoUSD_miscFiles\FernLeaf.fbx"),
}
_SKELETON_ASSET = Path(r"D:\Development\Work\Source\Meshes\SM_Black_Alder_Field_Nanite_09_bones.fbx")

_GEOMETRY_GOLDENS = {
    "Twig_01": {
        "counts": (516, 888, 2664, 0),
        "slots": (("Unassigned", 888),),
        "stable_hashes": {
            "point_components": "65b64b337ef64769a5bd76b09492ed8814ac13b38e14c3c35e278e8fb5ec0d7b",
            "face_vertex_counts": "880789ade688840ba720a56b2d35cbd55b9d62f70f70bc1aeb945cc4b8ca9c76",
            "vertex_color_components": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        },
    },
    "FernLeaf": {
        "counts": (888, 942, 2826, 888),
        "slots": (("SmallLeaf_Mat", 942),),
        "stable_hashes": {
            "point_components": "12ae10ff991c75d5292fd0adfa505afe00548d3585c6d6e66631a0f23fd7bf20",
            "face_vertex_counts": "c7aeb1cac1cdf8f067909ec9935f544a7ccc5827c94c6baf5fef0b78bc22bfdf",
            "vertex_color_components": "75bff110f4bcbdbad50de20ca2097dbdaecc29519d9d073347f9456e87d1a0c2",
        },
    },
}


def test_ufbx_bridge_rejects_malformed_native_payload() -> None:
    payload = {
        "point_components": b"not-float-aligned",
        "face_vertex_counts": array("i", (3,)).tobytes(),
        "face_vertex_indices": array("i", (0, 1, 2)).tobytes(),
        "uv_components": b"",
        "vertex_color_components": b"",
        "material_slots": (),
    }

    with pytest.raises(FbxImportError, match="malformed point components"):
        _geometry_from_native_payload(payload, "Broken")


def test_skeletal_preview_reports_skin_and_bone_frame_defects(monkeypatch) -> None:
    identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    child = identity[:12] + (0.0, 1.0, 0.0, 1.0)
    raw = {
        "joints": [
            ("root", -1, identity, identity, (1.0, 1.0, 1.0), 1),
            ("branch", 0, child, child, (1.0, 1.0, 1.0), 1),
        ],
        "point_components": array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)).tobytes(),
        "face_vertex_counts": array("i", (3,)).tobytes(),
        "face_vertex_indices": array("i", (0, 1, 2)).tobytes(),
        "skel_joint_indices": array("i", (0, 0, 0, 0) * 3).tobytes(),
        "skel_joint_weights": array("f", (0.5, 0.0, 0.0, 0.0) * 3).tobytes(),
        "stats": {
            "mesh_count": 1,
            "skin_deformer_count": 1,
            "skin_cluster_count": 1,
            "unweighted_vertex_count": 0,
            "non_normalized_vertex_count": 3,
            "minimum_weight_sum": 0.5,
            "maximum_weight_sum": 0.5,
            "unit_meters": 0.01,
            "up_axis": 2,
        },
    }
    monkeypatch.setattr(fbx_adapter, "_load_ufbx_native", lambda: SimpleNamespace(load_skeletal_preview=lambda _path: raw))

    preview = load_fbx_skeletal_preview("broken.fbx")

    codes = {issue.code for issue in preview.diagnostics}
    assert preview.mesh is not None
    assert {"external_fbx_unnormalized_weights", "external_fbx_misaligned_x_axis", "external_fbx_single_joint_dominance"} <= codes


@pytest.mark.parametrize("name", tuple(_REAL_ASSETS))
def test_ufbx_geometry_matches_frozen_pre_migration_payload(name: str) -> None:
    path = _REAL_ASSETS[name]
    if not path.is_file():
        pytest.skip(f"local FBX equivalence fixture is unavailable: {path}")

    geometry = load_fbx_geometry(str(path), name, cpu_profile=CpuProfile.BALANCED)
    golden = _GEOMETRY_GOLDENS[name]

    assert (
        len(geometry.point_components) // 3,
        len(geometry.face_vertex_counts),
        len(geometry.uv_components) // 2,
        len(geometry.vertex_color_components) // 4,
    ) == golden["counts"]
    assert tuple((slot.name, slot.face_count) for slot in geometry.fbx_material_slots) == golden["slots"]
    assert tuple((slot.name, slot.face_count) for slot in inspect_fbx_material_slots(str(path))) == golden["slots"]
    assert {
        field: hashlib.sha256(getattr(geometry, field).tobytes()).hexdigest()
        for field in golden["stable_hashes"]
    } == golden["stable_hashes"]
    assert all(count == 3 for count in geometry.face_vertex_counts)
    assert len(geometry.face_vertex_indices) == len(geometry.face_vertex_counts) * 3
    assert len(geometry.uv_components) == len(geometry.face_vertex_indices) * 2
    assert all(0 <= index < len(geometry.point_components) // 3 for index in geometry.face_vertex_indices)


def test_ufbx_skeleton_matches_frozen_pre_migration_hierarchy() -> None:
    if not _SKELETON_ASSET.is_file():
        pytest.skip(f"local FBX skeleton fixture is unavailable: {_SKELETON_ASSET}")

    joints = load_fbx_skeleton(str(_SKELETON_ASSET))

    assert len(joints) == 966
    assert (joints[0].name, joints[0].parent) == ("Root", None)
    assert tuple(joints[0].bind_transform.rows[3][:3]) == pytest.approx(
        (-4.605469226837158, -8.769821166992188, -3.609978675842285)
    )
    assert (joints[1].name, joints[1].parent) == ("Bone_1_End", "Root")
    assert tuple(joints[1].bind_transform.rows[3][:3]) == pytest.approx(
        (-66.304931640625, 273.10931396484375, 1.2349026203155518)
    )
