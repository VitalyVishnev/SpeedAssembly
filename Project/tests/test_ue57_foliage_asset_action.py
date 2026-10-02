from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


class _Vector:
    def __init__(self, x: float, y: float, z: float) -> None:
        self.x = x
        self.y = y
        self.z = z

    def __sub__(self, other: "_Vector") -> "_Vector":
        return _Vector(self.x - other.x, self.y - other.y, self.z - other.z)

    def __truediv__(self, scalar: float) -> "_Vector":
        return _Vector(self.x / scalar, self.y / scalar, self.z / scalar)


def test_speedtree_continuation_uses_lowest_reference_skeleton_index(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "unreal", SimpleNamespace())
    path = Path(__file__).parents[1] / "scripts" / "ue57_fix_selected_foliage_bones.py"
    spec = importlib.util.spec_from_file_location("ue57_foliage_asset_action", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    positions = (
        _Vector(0.0, 0.0, 0.0),
        _Vector(0.0, 1.0, 0.0),
        _Vector(10.0, 0.0, 0.0),
    )
    direction = module._continuation_direction(0, positions, (-1, 0, 0), ([2, 1], [], []))

    assert (direction.x, direction.y, direction.z) == pytest.approx((0.0, 1.0, 0.0))
