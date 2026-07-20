from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from xml_to_usda.models import Joint, Matrix4d, Vector3
from xml_to_usda.wind_external_skeleton import (
    ExternalSkeletonPreviewRequest,
    external_skeleton_backend_available,
    list_external_usd_skeletons,
    load_external_skeleton_preview,
)
from xml_to_usda.wind_preview_service import WindPreviewError


def test_external_fbx_skeleton_preview_is_skeleton_only(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "tree.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeleton",
        lambda _path: (
            _joint("root", None, 0.0),
            _joint("branch", "root", 1.0),
        ),
    )

    preview = load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))

    assert preview.source_model.base_mesh is None
    assert preview.viewport_scene.mesh_batches == ()
    assert preview.viewport_scene.draw_calls == ()
    assert [segment.child_token for segment in preview.viewport_scene.bone_segments] == ["branch"]
    assert [assignment.simulation_group_index for assignment in preview.dynamic_wind.joint_assignments] == [0, 0]


def test_external_skeleton_preview_rejects_duplicate_joint_names(monkeypatch, tmp_path: Path) -> None:
    fbx_path = tmp_path / "tree.fbx"
    fbx_path.write_bytes(b"stub")
    monkeypatch.setattr(
        "xml_to_usda.wind_external_skeleton.load_fbx_skeleton",
        lambda _path: (
            _joint("root", None, 0.0),
            _joint("root", None, 1.0),
        ),
    )

    with pytest.raises(WindPreviewError, match="external_skeleton_duplicate_joint_name"):
        load_external_skeleton_preview(ExternalSkeletonPreviewRequest(str(fbx_path)))


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
        ("Root/Branch", "Root", 2.0),
        ("Root/Branch/Tip", "Root/Branch", 5.0),
    ]
    assert [segment.child_token for segment in preview.viewport_scene.bone_segments] == ["Root/Branch", "Root/Branch/Tip"]


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
        ("Root/Branch", "Root", 1.0, 2.0, 3.0),
        ("Root/Branch/Tip", "Root/Branch", 4.0, 5.0, 6.0),
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

    assert [joint.name for joint in preview.source_model.skeleton] == ["C", "C/D"]


def _joint(name: str, parent: str | None, y: float) -> Joint:
    return Joint(
        name=name,
        parent=parent,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, y, 0.0)),
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
