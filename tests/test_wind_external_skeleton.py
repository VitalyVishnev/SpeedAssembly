from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from xml_to_usda.fbx_adapter import FbxSkeletalPreview
from xml_to_usda.dynamic_wind import render_dynamic_wind_payload
from xml_to_usda.models import DynamicWindData, DynamicWindJointAssignment, DynamicWindSimulationGroup, Joint, Matrix4d, MeshData, ValidationIssue, Vector3
from xml_to_usda.wind_external_skeleton import (
    ExternalSkeletonPreviewRequest,
    external_vertical_bone_names,
    external_skeleton_backend_available,
    list_external_usd_skeletons,
    load_external_skeleton_preview,
    prepare_external_dynamic_wind_export,
    transform_external_skeleton_scene,
)
from xml_to_usda.wind_preview_service import WindPreviewError


def test_external_fbx_preview_includes_skinned_mesh_and_diagnostics(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "tree.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                _joint("root", None, 0.0),
                _joint("branch", "root", 1.0),
            ),
            mesh=_skinned_triangle(),
            diagnostics=(ValidationIssue("warning", "test_rig", "Normalize weights."),),
        ),
    )

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))

    assert preview.source_model.base_mesh is None
    assert len(preview.viewport_scene.mesh_batches) == 1
    assert len(preview.viewport_scene.draw_calls) == 1
    assert preview.diagnostics[0].code == "test_rig"
    assert (preview.display_source_unit, preview.display_source_up_axis) == ("cm", "Z")
    assert [segment.child_token for segment in preview.viewport_scene.bone_segments] == ["branch"]
    assert [assignment.simulation_group_index for assignment in preview.dynamic_wind.joint_assignments] == [0, 0]


def test_external_skeleton_display_transform_is_viewport_only(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "tree.fbx"
    fbx_path.write_bytes(b"stub")
    skeleton = (
        Joint("root", parent=None, bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        Joint("branch", parent="root", bind_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0))),
    )
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(skeleton, _skinned_triangle(), ()),
    )

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))
    transformed = transform_external_skeleton_scene(
        preview.viewport_scene,
        source_unit="cm",
        preview_unit="m",
        source_up_axis="Y",
        preview_up_axis="Z",
    )

    assert transformed.bone_segments[0].end == Vector3(0.0, 0.0, 0.02)
    assert preview.viewport_scene.bone_segments[0].end == Vector3(0.0, 2.0, 0.0)
    assert preview.source_model.skeleton == skeleton
    assert transformed.draw_calls[0].scale == Vector3(0.01, 0.01, 0.01)
    assert transformed.bounds.max_point.z == pytest.approx(0.02)


def test_external_vertical_bones_use_bind_pose_forward_axis() -> None:
    skeleton = (
        Joint("root", parent=None, bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0))),
        _joint_with_forward("vertical", "root", Vector3(0.0, 1.0, 0.0), Vector3(0.0, 2.0, 0.0)),
        _joint_with_forward("lateral", "root", Vector3(1.0, 0.0, 0.0), Vector3(1.0, 1.0, 0.0)),
        _joint_with_forward("z_vertical", "root", Vector3(0.0, 0.0, 1.0), Vector3(0.0, 0.0, 3.0)),
    )

    assert external_vertical_bone_names(skeleton, "Y") == ("vertical",)
    assert external_vertical_bone_names(skeleton, "Z") == ("z_vertical",)


def test_external_skeleton_preview_rejects_duplicate_joint_names(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "tree.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                _joint("root", None, 0.0),
                _joint("root", None, 1.0),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )

    with pytest.raises(WindPreviewError, match="external_skeleton_duplicate_joint_name"):
        load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))


def test_external_fbx_wind_export_uses_unreal_ref_skeleton_names_without_mutating_source(
    monkeypatch,
    tmp_path: Path,
) -> None:
    fbx_path = tmp_path / "character.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                _joint("Root", None, 0.0),
                _joint("Bone.001", "Root", 1.0),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))
    exported = prepare_external_dynamic_wind_export(preview, preview.dynamic_wind)
    payload = render_dynamic_wind_payload(exported)

    assert [joint.name for joint in preview.source_model.skeleton] == ["Root", "Bone_001"]
    assert [assignment.joint_name for assignment in preview.dynamic_wind.joint_assignments] == ["Root", "Bone_001"]
    assert [joint["JointName"] for joint in payload["Joints"]] == ["Root", "Bone_001"]


def test_external_fbx_preview_uses_unreal_name_collision_suffix(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "collision.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                _joint("Root", None, 0.0),
                _joint("Bone.001", "Root", 1.0),
                _joint("Bone_001", "Root", 2.0),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))

    assert [joint.name for joint in preview.source_model.skeleton] == ["Root", "Bone_001", "Bone_0011"]


def test_external_export_rejects_unmatched_or_forked_ref_skeleton_groups(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "fork.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeletal_preview",
        lambda _path: FbxSkeletalPreview(
            skeleton=(
                _joint("Root", None, 0.0),
                _joint("Left", "Root", 1.0),
                _joint("Right", "Root", 2.0),
            ),
            mesh=None,
            diagnostics=(),
        ),
    )
    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))
    group = DynamicWindSimulationGroup(group_index=0, branch_order=0)
    forked = DynamicWindData(
        joint_assignments=tuple(
            DynamicWindJointAssignment(joint_name=joint.name, simulation_group_index=0, branch_order=0)
            for joint in preview.source_model.skeleton
        ),
        simulation_groups=(group,),
    )

    with pytest.raises(WindPreviewError, match="dynamic_wind_same_group_fork"):
        prepare_external_dynamic_wind_export(preview, forked)

    unmatched = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="Missing", simulation_group_index=0, branch_order=0),),
        simulation_groups=(group,),
    )
    with pytest.raises(WindPreviewError, match="dynamic_wind_unknown_joint"):
        prepare_external_dynamic_wind_export(preview, unmatched)


def test_text_usd_external_skeleton_backend_does_not_require_pxr() -> None:
    available, reason = external_skeleton_backend_available(".usda")

    assert available is True
    assert reason == ""


def test_usdc_external_skeleton_backend_still_requires_pxr() -> None:
    available, reason = external_skeleton_backend_available(".usdc")

    if not available:
        assert "pxr" in reason


def test_external_usd_skeleton_preview_reads_usdskel_without_mesh(monkeypatch, tmp_path: Path) -> None:
    usd_path = tmp_path / "tree.usda"
    usd_path.write_text("#usda 1.0", encoding="utf-8")
    fake_skeleton_data = _FakeUsdSkeletonData(
        joints=("Root", "Root/Branch", "Root/Branch/Tip"),
        bind_transforms=(
            _FakeUsdMatrix(0.0, 0.0, 0.0),
            _FakeUsdMatrix(0.0, 2.0, 0.0),
            _FakeUsdMatrix(0.0, 5.0, 0.0),
        ),
    )
    fake_usd = types.SimpleNamespace(Stage=types.SimpleNamespace(Open=lambda _path: _FakeUsdStage(fake_skeleton_data)))
    fake_usdskel = types.SimpleNamespace(Skeleton=_FakeUsdSkeleton)
    fake_pxr = types.ModuleType("pxr")
    fake_pxr.Usd = fake_usd
    fake_pxr.UsdSkel = fake_usdskel
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path), group_count=2))

    assert preview.source_model.base_mesh is None
    assert preview.viewport_scene.mesh_batches == ()
    assert [(joint.name, joint.parent, joint.bind_translate.y) for joint in preview.source_model.skeleton] == [
        ("Root", None, 0.0),
        ("Branch", "Root", 2.0),
        ("Tip", "Branch", 5.0),
    ]
    assert [segment.child_token for segment in preview.viewport_scene.bone_segments] == ["Branch", "Tip"]


@pytest.mark.parametrize(
    ("bind_transforms", "error_code"),
    [
        ((), "external_skeleton_missing_joint_transforms"),
        ((object(),), "external_skeleton_invalid_joint_transform"),
    ],
)
def test_external_usd_skeleton_rejects_unusable_joint_transforms(
    monkeypatch,
    tmp_path: Path,
    bind_transforms,
    error_code: str,
) -> None:
    usd_path = tmp_path / "invalid-transforms.usda"
    usd_path.write_text("#usda 1.0", encoding="utf-8")
    fake_skeleton_data = _FakeUsdSkeletonData(joints=("Root",), bind_transforms=bind_transforms)
    fake_usd = types.SimpleNamespace(Stage=types.SimpleNamespace(Open=lambda _path: _FakeUsdStage(fake_skeleton_data)))
    fake_usdskel = types.SimpleNamespace(Skeleton=_FakeUsdSkeleton)
    fake_pxr = types.ModuleType("pxr")
    fake_pxr.Usd = fake_usd
    fake_pxr.UsdSkel = fake_usdskel
    monkeypatch.setitem(sys.modules, "pxr", fake_pxr)

    with pytest.raises(WindPreviewError, match=error_code):
        load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path)))


def test_external_text_usda_skeleton_choices_do_not_autopick_largest_without_pxr(monkeypatch, tmp_path: Path) -> None:
    usd_path = tmp_path / "tree.usda"
    usd_path.write_text(
        """#usda 1.0
def Xform "Tree"
{
    def Skeleton "MainSkeleton"
    {
        uniform matrix4d[] bindTransforms = [
            ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) ),
            ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (1, 2, 3, 1) ),
            ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (4, 5, 6, 1) )
        ]
        uniform token[] joints = ["Root", "Root/Branch", "Root/Branch/Tip"]
    }
    def Skeleton "PartSkeleton"
    {
        uniform matrix4d[] bindTransforms = [( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (9, 9, 9, 1) )]
        uniform token[] joints = ["Twig"]
    }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "pxr", None)

    choices = list_external_usd_skeletons(str(usd_path))

    assert [(choice.index, choice.name, choice.joint_count) for choice in choices.choices] == [
        (0, "MainSkeleton", 3),
        (1, "PartSkeleton", 1),
    ]
    with pytest.raises(WindPreviewError, match="external_skeleton_multiple_skeletons"):
        load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path), group_count=2))

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path), group_count=2, skeleton_index=0))
    assert [(joint.name, joint.parent, joint.bind_translate.x, joint.bind_translate.y, joint.bind_translate.z) for joint in preview.source_model.skeleton] == [
        ("Root", None, 0.0, 0.0, 0.0),
        ("Branch", "Root", 1.0, 2.0, 3.0),
        ("Tip", "Branch", 4.0, 5.0, 6.0),
    ]
    assert preview.source_model.base_mesh is None


def test_external_text_usda_skeleton_preview_loads_selected_skeleton(monkeypatch, tmp_path: Path) -> None:
    usd_path = tmp_path / "ambiguous.usda"
    usd_path.write_text(
        """#usda 1.0
def Skeleton "SkeletonA"
{
    uniform token[] joints = ["A", "A/B"]
}
def Skeleton "SkeletonB"
{
    uniform matrix4d[] bindTransforms = [
        ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) ),
        ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 3, 0, 1) )
    ]
    uniform token[] joints = ["C", "C/D"]
}
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "pxr", None)

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path), group_count=2, skeleton_index=1))

    assert [joint.name for joint in preview.source_model.skeleton] == ["C", "D"]


def test_external_text_usda_keeps_full_bind_pose_and_mirrors_synthetic_root(monkeypatch, tmp_path: Path) -> None:
    usd_path = tmp_path / "multi-root.usda"
    usd_path.write_text(
        """#usda 1.0
def Skeleton "Skeleton"
{
    uniform matrix4d[] bindTransforms = [
        ( (0, 1, 0, 0), (1, 0, 0, 0), (0, 0, -1, 0), (1, 2, 3, 1) ),
        ( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (4, 5, 6, 1) )
    ]
    uniform token[] joints = ["A", "B"]
}
""",
        encoding="utf-8",
    )
    monkeypatch.setitem(sys.modules, "pxr", None)

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(usd_path)))

    root, first, second = preview.source_model.skeleton
    assert (root.name, root.parent, root.bind_transform) == ("Root", None, Matrix4d.identity())
    assert (first.name, first.parent, first.bind_transform.rows[0], first.bind_translate) == (
        "A", "Root", (0.0, 1.0, 0.0, 0.0), Vector3(1.0, 2.0, 3.0)
    )
    assert (second.name, second.parent, second.bind_translate) == ("B", "Root", Vector3(4.0, 5.0, 6.0))


def _joint(name: str, parent: str | None, y: float) -> Joint:
    return Joint(
        name=name,
        parent=parent,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
    )


def _joint_with_forward(name: str, parent: str, forward: Vector3, translate: Vector3) -> Joint:
    if forward == Vector3(0.0, 1.0, 0.0):
        rows = ((0.0, 1.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0), (0.0, 0.0, -1.0, 0.0))
    elif forward == Vector3(0.0, 0.0, 1.0):
        rows = ((0.0, 0.0, 1.0, 0.0), (0.0, 1.0, 0.0, 0.0), (-1.0, 0.0, 0.0, 0.0))
    else:
        rows = ((1.0, 0.0, 0.0, 0.0), (0.0, 1.0, 0.0, 0.0), (0.0, 0.0, 1.0, 0.0))
    return Joint(name=name, parent=parent, bind_transform=Matrix4d(rows=(*rows, (translate.x, translate.y, translate.z, 1.0))))


def _skinned_triangle() -> MeshData:
    return MeshData(
        name="external",
        points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 2.0, 0.0)),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
        skel_joint_indices=(0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0),
        skel_joint_weights=(1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0),
        skel_element_size=4,
    )


class _FakeUsdMatrix:
    def __init__(self, x: float, y: float, z: float) -> None:
        self._translation = (x, y, z)

    def ExtractTranslation(self):
        return self._translation


class _FakeUsdAttr:
    def __init__(self, value) -> None:
        self._value = value

    def Get(self):
        return self._value


class _FakeUsdSkeletonData:
    def __init__(self, *, joints, bind_transforms) -> None:
        self.joints = joints
        self.bind_transforms = bind_transforms


class _FakeUsdSkeleton:
    def __init__(self, prim) -> None:
        self._data = prim.skeleton_data

    def GetJointsAttr(self):
        return _FakeUsdAttr(self._data.joints)

    def GetBindTransformsAttr(self):
        return _FakeUsdAttr(self._data.bind_transforms)

    def GetRestTransformsAttr(self):
        return _FakeUsdAttr(())


class _FakeUsdPrim:
    def __init__(self, skeleton_data) -> None:
        self.skeleton_data = skeleton_data

    def IsA(self, schema_type) -> bool:
        return schema_type is _FakeUsdSkeleton


class _FakeUsdStage:
    def __init__(self, skeleton_data) -> None:
        self._skeleton_data = skeleton_data

    def Traverse(self):
        return (_FakeUsdPrim(self._skeleton_data),)
