"""Main and Advanced exchange the same group intent despite index changes."""

from dataclasses import replace
import json

from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.models import Joint
from xml_to_usda.wind_group_stack import flatten_wind_group_stack
from xml_to_usda.wind_operator_state import (
    WindGroupState, restore_wind_data, source_revision, update_wind_session, wind_session_notice,
)
from xml_to_usda.wind_profiles import FORCE_BASED, ForceWindSettings


def test_settings_follow_joint_membership_through_exchange_and_restart(tmp_path):
    source = tmp_path / "tree.xml"
    source.write_text("<Tree/>", encoding="utf-8")
    skeleton = (Joint("root", generator_level=0), Joint("tip", parent="root", generator_level=1))
    base = build_dynamic_wind_data(skeleton)
    flattened = flatten_wind_group_stack(base)
    # The main panel's indices differ from Advanced's stack indices.
    incoming = replace(base, simulation_groups=(
        replace(base.simulation_groups[1], group_index=0, influence=.37, force=ForceWindSettings(tip_max_bend_angle=135)),
        replace(base.simulation_groups[0], group_index=1)), joint_assignments=tuple(
            replace(a, simulation_group_index=1-a.simulation_group_index) for a in base.joint_assignments))
    state = WindGroupState()
    state.apply(incoming, flattened)
    data = state.resolve(flattened, base, profile=FORCE_BASED)
    assert data.simulation_groups[1].influence == .37
    assert data.simulation_groups[1].force.tip_max_bend_angle == 135
    assert data.simulation_groups[0].force.is_trunk_group
    state.set_value("base:1", "min_influence", .17)
    data = state.resolve(flattened, base, profile=FORCE_BASED)
    session = json.loads(json.dumps({"schema_version": 4, "input_path": str(source),
        "source_mode": "source_xml", "source_revision": source_revision(str(source)),
        "fingerprint": [[j.name, j.parent] for j in skeleton], **state.snapshot(data)}))
    restored = WindGroupState()
    restored.restore(session)
    assert restored.resolve(flattened, base, profile=FORCE_BASED) == data
    latest = replace(data, simulation_groups=(data.simulation_groups[0], replace(data.simulation_groups[1], influence=.63)))
    session = update_wind_session(session, str(source), latest)
    assert restore_wind_data(session, str(source), base) == latest
    # Same joint names cannot make a changed source revision safe to restore.
    source.write_text("<Tree changed='yes'/>", encoding="utf-8")
    assert "source changed" in wind_session_notice(session, str(source), base)
    assert restore_wind_data(session, str(source), base) is base
