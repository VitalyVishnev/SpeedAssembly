"""Wind editing rules shared by the main and Advanced Qt adapters.

Group settings follow stack source keys inside Advanced and joint membership
when exchanged with the main panel. UI shell state stays with the dialog.
"""

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from .models import DynamicWindData, DynamicWindJointAssignment, DynamicWindSimulationGroup
from .settings_service import WindGroupSettingRecord
from .wind_group_stack import WindFlattenResult
from .wind_profiles import LEGACY, parse_force_settings, wind_profile


_BOOLEAN_FIELDS = frozenset({"is_trunk_group", "use_dual_influence"})
_NUMERIC_FIELDS = frozenset({"influence", "min_influence", "max_influence", "shift_top"})
_SETTING_FIELDS = _BOOLEAN_FIELDS | _NUMERIC_FIELDS | {"force"}


def wind_group_records(groups: tuple[DynamicWindSimulationGroup, ...]) -> dict[str, WindGroupSettingRecord]:
    return {str(group.group_index): _record(group) for group in groups}


def _record(group: DynamicWindSimulationGroup) -> WindGroupSettingRecord:
    return WindGroupSettingRecord(**{name: getattr(group, name) for name in _SETTING_FIELDS})


def wind_data_from_settings(payload: dict) -> DynamicWindData:
    """Restore editing intent; structural sections are recomputed on export."""
    assignments = tuple(
        DynamicWindJointAssignment(
            joint_name=assignment["joint_name"],
            simulation_group_index=assignment["simulation_group_index"],
            branch_order=assignment["branch_order"],
        )
        for assignment in payload["joint_assignments"]
    )
    groups = tuple(
        DynamicWindSimulationGroup(
            **{name: value for name, value in group.items() if name != "force"},
            force=parse_force_settings(group.get("force")),
        )
        for group in payload["simulation_groups"]
    )
    return DynamicWindData(
        joint_assignments=assignments,
        simulation_groups=groups,
        profile=wind_profile(payload.get("profile", LEGACY)),
        is_ground_cover=payload.get("is_ground_cover", False),
        gust_attenuation=payload.get("gust_attenuation", 0.0),
    )


def source_revision(input_path: str) -> list[int] | None:
    try:
        stat = Path(input_path).stat()
    except OSError:
        return None
    return [stat.st_size, stat.st_mtime_ns]


def wind_session_notice(session: dict, input_path: str, data: DynamicWindData) -> str:
    """Use the same source acceptance rule for both editing adapters."""
    if not session:
        return ""
    prefix = "Previous Wind Preview session reset: "
    if session.get("schema_version") not in {1, 2, 3, 4}:
        return prefix + "unsupported session version."
    if Path(str(session.get("input_path", ""))).resolve() != Path(input_path).resolve():
        return prefix + "source changed."
    saved_revision = session.get("source_revision")
    # Old display-only sessions predate source revisions. They carry no final
    # assignment for the main panel to reuse.
    if session.get("export_data") and saved_revision is None:
        return prefix + "source changed."
    if saved_revision is not None and saved_revision != source_revision(input_path):
        return prefix + "source changed."
    fingerprint = session.get("fingerprint")
    if not isinstance(fingerprint, (list, tuple)):
        return prefix + "skeleton changed."
    names = {row[0] for row in fingerprint if isinstance(row, (list, tuple)) and len(row) == 2}
    if len(names) != len(fingerprint) or names != {a.joint_name for a in data.joint_assignments}:
        return prefix + "skeleton changed."
    return ""


def restore_wind_data(session: dict, input_path: str, data: DynamicWindData) -> DynamicWindData:
    if (
        session.get("source_mode") != "source_xml"
        or not session.get("export_data")
        or wind_session_notice(session, input_path, data)
    ):
        return data
    from .dynamic_wind import validate_dynamic_wind_data

    restored = wind_data_from_settings(session["export_data"])
    validate_dynamic_wind_data(restored)
    if {a.joint_name for a in restored.joint_assignments} != {a.joint_name for a in data.joint_assignments}:
        return data
    return replace(restored, warnings=data.warnings)


def update_wind_session(session: dict, input_path: str, data: DynamicWindData | None) -> dict:
    """Main-panel edits must supersede the final assignment saved by Advanced."""
    if data is None or not session or wind_session_notice(session, input_path, data):
        return session
    if session.get("source_mode") != "source_xml":
        return session
    return {**session, "export_data": asdict(data)}


class WindGroupState:
    """Own both profiles' settings across stack edits and panel exchanges."""

    def __init__(self, data: DynamicWindData | None = None) -> None:
        self._settings: dict[str, dict] = {}
        self.is_ground_cover = data.is_ground_cover if data else False
        self.gust_attenuation = data.gust_attenuation if data else 0.0

    def _group(self, source_key: str, fallback: DynamicWindSimulationGroup) -> DynamicWindSimulationGroup:
        return replace(fallback, **self._settings.get(source_key, {}))

    def resolve(self, flattened: WindFlattenResult, base: DynamicWindData, *, profile: str) -> DynamicWindData:
        base_groups = {group.group_index: group for group in base.simulation_groups}
        groups = []
        for group in flattened.groups:
            fallback = flattened.dynamic_wind.simulation_groups[group.final_group_index]
            source = base_groups.get(group.source_group_index)
            if source is not None:
                fallback = replace(source, group_index=fallback.group_index, branch_order=fallback.branch_order)
            groups.append(self._group(group.source_key, fallback))
        return replace(
            flattened.dynamic_wind,
            simulation_groups=tuple(groups),
            profile=profile,
            is_ground_cover=self.is_ground_cover,
            gust_attenuation=self.gust_attenuation,
        )

    def apply(self, data: DynamicWindData, flattened: WindFlattenResult) -> None:
        """Transfer settings only between groups covering exactly the same joints."""
        self.is_ground_cover, self.gust_attenuation = data.is_ground_cover, data.gust_attenuation
        members: dict[int, set[str]] = {}
        for assignment in data.joint_assignments:
            members.setdefault(assignment.simulation_group_index, set()).add(assignment.joint_name)
        by_members = {
            frozenset(members.get(group.group_index, ())): group
            for group in data.simulation_groups
        }
        for group in flattened.groups:
            source = by_members.get(frozenset(group.joint_tokens))
            if source is not None:
                self._settings[group.source_key] = {name: getattr(source, name) for name in _SETTING_FIELDS}

    def set_value(self, source_key: str, name: str, value) -> None:
        if name in _BOOLEAN_FIELDS:
            value = bool(value)
        elif name in _NUMERIC_FIELDS:
            value = max(0.0, min(float(value), 1.0))
        elif name != "force":
            raise ValueError(f"Unknown Wind group setting: {name}")
        self._settings.setdefault(source_key, {})[name] = value

    def snapshot(self, data: DynamicWindData) -> dict:
        return {
            "group_settings": {
                key: {
                    name: values[name]
                    for name in sorted(_BOOLEAN_FIELDS | _NUMERIC_FIELDS)
                    if name in values
                }
                for key, values in sorted(self._settings.items())
            },
            "force_group_settings": {
                key: asdict(values["force"])
                for key, values in sorted(self._settings.items())
                if "force" in values
            },
            "export_data": asdict(data),
        }

    def restore(self, session: dict) -> None:
        legacy = session.get("group_settings", {}) if session.get("schema_version", 0) >= 3 else {}
        forces = session.get("force_group_settings", {})
        if not isinstance(legacy, dict) or not isinstance(forces, dict):
            raise ValueError("Wind group settings must be objects.")
        self._settings.clear()
        for key in legacy.keys() | forces.keys():
            if not isinstance(key, str) or not key:
                continue
            raw = legacy.get(key, {})
            if not isinstance(raw, dict):
                continue
            values = {name: raw[name] for name in _BOOLEAN_FIELDS if isinstance(raw.get(name), bool)}
            for name in _NUMERIC_FIELDS:
                value = raw.get(name)
                if value is None or isinstance(value, bool):
                    continue
                try:
                    values[name] = max(0.0, min(float(value), 1.0))
                except (TypeError, ValueError):
                    continue
            if key in forces:
                values["force"] = parse_force_settings(forces[key])
            self._settings[key] = values
        exported = session.get("export_data", {})
        self.is_ground_cover = exported.get("is_ground_cover", self.is_ground_cover)
        self.gust_attenuation = exported.get("gust_attenuation", self.gust_attenuation)
