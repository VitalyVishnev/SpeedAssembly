from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from functools import cached_property

from .models import Bounds, Vector3


_METERS_PER_UNIT = {
    "m": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "cm": 0.01,
    "centimeter": 0.01,
    "centimeters": 0.01,
    "mm": 0.001,
    "millimeter": 0.001,
    "millimeters": 0.001,
}


@dataclass(frozen=True)
class SourceTransform:
    source_units: str
    source_up_axis: str
    target_meters_per_unit: float = 1.0
    target_up_axis: str = "Y"

    @cached_property
    def linear_scale(self) -> float:
        meters_per_source_unit = _METERS_PER_UNIT.get(self.source_units, _METERS_PER_UNIT["cm"])
        return meters_per_source_unit / self.target_meters_per_unit

    def point_to_stage(self, point: Vector3) -> Vector3:
        return self.point_components_to_stage(point.x, point.y, point.z)

    def points_components_to_stage(self, xs, ys, zs) -> list[Vector3]:
        scale = self.linear_scale
        if scale == 1.0:
            if self.source_up_axis == self.target_up_axis:
                return [Vector3(x, y, z) for x, y, z in zip(xs, ys, zs)]
            if self.source_up_axis == "Z" and self.target_up_axis == "Y":
                return [Vector3(x, z, -y) for x, y, z in zip(xs, ys, zs)]
            if self.source_up_axis == "Y" and self.target_up_axis == "Z":
                return [Vector3(x, -z, y) for x, y, z in zip(xs, ys, zs)]
            return [self.point_components_to_stage(x, y, z) for x, y, z in zip(xs, ys, zs)]
        if self.source_up_axis == self.target_up_axis:
            return [Vector3(x * scale, y * scale, z * scale) for x, y, z in zip(xs, ys, zs)]
        if self.source_up_axis == "Z" and self.target_up_axis == "Y":
            return [Vector3(x * scale, z * scale, -y * scale) for x, y, z in zip(xs, ys, zs)]
        if self.source_up_axis == "Y" and self.target_up_axis == "Z":
            return [Vector3(x * scale, -z * scale, y * scale) for x, y, z in zip(xs, ys, zs)]
        return [self.point_components_to_stage(x, y, z) for x, y, z in zip(xs, ys, zs)]

    def point_components_to_stage(self, x: float, y: float, z: float) -> Vector3:
        scale = self.linear_scale
        if scale == 1.0:
            if self.source_up_axis == self.target_up_axis:
                return Vector3(x, y, z)
            if self.source_up_axis == "Z" and self.target_up_axis == "Y":
                return Vector3(x, z, -y)
            if self.source_up_axis == "Y" and self.target_up_axis == "Z":
                return Vector3(x, -z, y)
        if self.source_up_axis == self.target_up_axis:
            return Vector3(x * scale, y * scale, z * scale)
        if self.source_up_axis == "Z" and self.target_up_axis == "Y":
            return Vector3(x * scale, z * scale, -y * scale)
        if self.source_up_axis == "Y" and self.target_up_axis == "Z":
            return Vector3(x * scale, -z * scale, y * scale)
        rotated = self.direction_to_stage(Vector3(x, y, z))
        return Vector3(
            rotated.x * scale,
            rotated.y * scale,
            rotated.z * scale,
        )

    def direction_to_stage(self, direction: Vector3) -> Vector3:
        if self.source_up_axis == self.target_up_axis:
            return direction
        if self.source_up_axis == "Z" and self.target_up_axis == "Y":
            # SpeedTree sample exports are observed as Z-up. The USDA stage is authored as Y-up.
            return Vector3(direction.x, direction.z, -direction.y)
        if self.source_up_axis == "Y" and self.target_up_axis == "Z":
            return Vector3(direction.x, -direction.z, direction.y)
        raise ValueError(
            f"Unsupported source-to-stage axis conversion: {self.source_up_axis} -> {self.target_up_axis}"
        )

    def axis_to_stage(self, axis: Vector3) -> Vector3:
        remapped = self.direction_to_stage(axis)
        length = math.sqrt(remapped.x * remapped.x + remapped.y * remapped.y + remapped.z * remapped.z)
        if length == 0.0:
            return remapped
        return Vector3(remapped.x / length, remapped.y / length, remapped.z / length)

    def bounds_to_stage(self, bounds: Bounds | None) -> Bounds | None:
        if bounds is None:
            return None
        scale = self.linear_scale
        minimum = bounds.minimum
        maximum = bounds.maximum
        if self.source_up_axis == self.target_up_axis:
            return Bounds(
                minimum=Vector3(minimum.x * scale, minimum.y * scale, minimum.z * scale),
                maximum=Vector3(maximum.x * scale, maximum.y * scale, maximum.z * scale),
            )
        if self.source_up_axis == "Z" and self.target_up_axis == "Y":
            return Bounds(
                minimum=Vector3(
                    minimum.x * scale,
                    min(minimum.z, maximum.z) * scale,
                    -max(minimum.y, maximum.y) * scale,
                ),
                maximum=Vector3(
                    maximum.x * scale,
                    max(minimum.z, maximum.z) * scale,
                    -min(minimum.y, maximum.y) * scale,
                ),
            )
        if self.source_up_axis == "Y" and self.target_up_axis == "Z":
            return Bounds(
                minimum=Vector3(
                    minimum.x * scale,
                    -max(minimum.z, maximum.z) * scale,
                    min(minimum.y, maximum.y) * scale,
                ),
                maximum=Vector3(
                    maximum.x * scale,
                    -min(minimum.z, maximum.z) * scale,
                    max(minimum.y, maximum.y) * scale,
                ),
            )
        corners = (
            Vector3(bounds.minimum.x, bounds.minimum.y, bounds.minimum.z),
            Vector3(bounds.minimum.x, bounds.minimum.y, bounds.maximum.z),
            Vector3(bounds.minimum.x, bounds.maximum.y, bounds.minimum.z),
            Vector3(bounds.minimum.x, bounds.maximum.y, bounds.maximum.z),
            Vector3(bounds.maximum.x, bounds.minimum.y, bounds.minimum.z),
            Vector3(bounds.maximum.x, bounds.minimum.y, bounds.maximum.z),
            Vector3(bounds.maximum.x, bounds.maximum.y, bounds.minimum.z),
            Vector3(bounds.maximum.x, bounds.maximum.y, bounds.maximum.z),
        )
        transformed = tuple(self.point_to_stage(corner) for corner in corners)
        return Bounds(
            minimum=Vector3(
                min(point.x for point in transformed),
                min(point.y for point in transformed),
                min(point.z for point in transformed),
            ),
            maximum=Vector3(
                max(point.x for point in transformed),
                max(point.y for point in transformed),
                max(point.z for point in transformed),
            ),
        )


def build_source_transform(
    root: ET.Element,
    units_hint: str | None,
    up_axis_hint: str | None,
    mesh_nodes: tuple[ET.Element, ...] | None = None,
) -> SourceTransform:
    # Supported SpeedTree XML exports are authored in meters. The USDA stage
    # stays in meters as well, so no unit rescale is applied here.
    source_units = "m"
    source_up_axis = _normalize_up_axis(up_axis_hint) or _infer_up_axis_from_mesh_orientation(
        mesh_nodes if mesh_nodes is not None else root.findall(".//Meshes/Mesh")
    ) or "Z"
    return SourceTransform(
        source_units=source_units,
        source_up_axis=source_up_axis,
    )


def _normalize_units(units_hint: str | None) -> str | None:
    if not units_hint:
        return None
    normalized = units_hint.strip().lower()
    return normalized if normalized in _METERS_PER_UNIT else None


def _normalize_up_axis(up_axis_hint: str | None) -> str | None:
    if not up_axis_hint:
        return None
    normalized = up_axis_hint.strip().upper()
    return normalized if normalized in {"Y", "Z"} else None


def _infer_up_axis_from_mesh_orientation(meshes: tuple[ET.Element, ...] | list[ET.Element]) -> str | None:
    for mesh in meshes:
        orient = mesh.attrib.get("Orient", "").upper()
        if orient.endswith("Y"):
            return "Y"
        if orient.endswith("Z"):
            return "Z"
    return None

