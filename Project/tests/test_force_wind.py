"""Both export paths must carry the same UE 5.9 intent without changing Legacy."""

from dataclasses import asdict, replace
import json

from pxr import Usd
import pytest

from xml_to_usda.dynamic_wind import build_dynamic_wind_data, render_dynamic_wind_payload
from xml_to_usda.models import Joint
from xml_to_usda.wind_authoring import prepare_wind_export, wind_usd_fields
from xml_to_usda.wind_operator_state import wind_data_from_settings
from xml_to_usda.wind_profiles import FORCE_BASED, ForceWindSettings
from xml_to_usda.settings_service import GuiSettingsSnapshot, WindGroupSettingRecord, load_gui_settings, save_gui_settings
from xml_to_usda.worker_file_protocol import read_worker_payload, write_worker_payload_atomic


def test_force_json_and_usd_preserve_overrides_units_and_joint_identity(tmp_path):
    skeleton = (Joint("root", generator_level=0), Joint("tip", parent="root", generator_level=1))
    data = build_dynamic_wind_data(skeleton)
    old_payload = render_dynamic_wind_payload(data)
    settings = ForceWindSettings(is_trunk_group=True, wind_response_scale=2.5, modal_frequency_scale=1.75,
                                 base_max_bend_angle=30, tip_max_bend_angle=140)
    groups = (replace(data.simulation_groups[0], force=settings), data.simulation_groups[1])
    data = prepare_wind_export(skeleton, profile=FORCE_BASED, data=replace(data, simulation_groups=groups), root_name="Tree")
    data = replace(data, joint_assignments=(data.joint_assignments[0], replace(data.joint_assignments[1],
        segment_length_m=0.25, radius_samples_m=(0.02, 0.01), sample_distances_m=(0, 0.25))))
    schemas, lines = wind_usd_fields(data, meters_per_unit=0.01)
    stage = Usd.Stage.CreateInMemory()
    assert stage.GetRootLayer().ImportFromString('#usda 1.0\ndef Skeleton "Tree" (prepend apiSchemas = '+json.dumps(schemas)+')\n{\n'+'\n'.join(lines)+'\n}')
    prim = stage.GetPrimAtPath('/Tree')
    payload = render_dynamic_wind_payload(data)
    assert list(prim.GetAttribute('unreal:dynamicWind:jointNames').Get()) == [j['JointName'] for j in payload['Joints']]
    assert list(prim.GetAttribute('unreal:dynamicWind:jointRadiusSamples').Get()) == pytest.approx([2,1])
    assert list(prim.GetAttribute('unreal:dynamicWind:jointSegmentLengths').Get()) == pytest.approx([0,25])
    group = payload['SimulationGroups'][0]
    assert group['bOverrideModalFrequencyScale'] and group['ModalFrequencyScale'] == 1.75
    assert not group['bOverrideBaseFrequencyScale']
    assert not prim.HasAttribute('unreal:dynamicWind:simulationGroup:group_0:baseFrequencyScale')
    assert prim.GetAttribute('unreal:dynamicWind:simulationGroup:group_0:modalFrequencyScale').Get() == 1.75
    assert 'Influence' not in group and 'bIsGroundCover' not in payload
    assert render_dynamic_wind_payload(replace(data, profile='legacy'))['SimulationGroups'] == old_payload['SimulationGroups']
    target = tmp_path/'worker.json'
    write_worker_payload_atomic(target, data)
    assert read_worker_payload(target) == data
    assert wind_data_from_settings(asdict(data)).simulation_groups == data.simulation_groups


def test_profile_settings_survive_switching_and_restart(qtbot, tmp_path):
    from xml_to_usda.qt_ui.panels import WindTabPanel
    data = build_dynamic_wind_data((Joint('root', generator_level=0),))
    panel = WindTabPanel(on_change=lambda: None, on_refresh_requested=lambda: None, on_preview_requested=lambda: None)
    qtbot.addWidget(panel)
    panel.rebuild(data)
    row = panel._rows[0]
    row.min_influence_spin.setValue(0.23)
    row.trunk_checkbox.setChecked(False)
    panel.set_profile(FORCE_BASED)
    assert row.dual_frame.isHidden() and panel.gust_spin.isHidden()
    assert not row.force_editor.isHidden()
    editor = row.force_editor
    assert editor.editors['modal_frequency_scale'].isHidden()
    editor.overrides['modal_frequency_scale'].setChecked(True)
    editor.editors['modal_frequency_scale'].spin.setValue(2)
    assert not editor.editors['modal_frequency_scale'].isHidden()
    panel.set_profile('legacy')
    assert row.min_influence_spin.value() == pytest.approx(.23)
    assert not row.trunk_checkbox.isChecked()
    assert editor.isHidden()
    path = tmp_path/'settings.json'
    snapshot = GuiSettingsSnapshot(wind_profile=FORCE_BASED, wind_group_settings=panel.serialize_settings())
    save_gui_settings(path, snapshot)
    assert load_gui_settings(path) == snapshot
    panel.set_persisted_settings(load_gui_settings(path).wind_group_settings)
    panel.rebuild(data)
    panel.set_profile(FORCE_BASED)
    assert panel._rows[0].force_editor.settings().modal_frequency_scale == 2
    assert panel._rows[0].force_editor.settings().is_trunk_group


def test_incoming_sections_use_parent_wood_and_lateral_child_radius(tmp_path, monkeypatch):
    from xml_to_usda.wind_pipeline import generate_wind_json
    from xml_to_usda import opening_xml
    reads = []
    read_source = opening_xml.read_source_xml
    def read_once(path):
        reads.append(path)
        return read_source(path)
    monkeypatch.setattr(opening_xml, 'read_source_xml', read_once)
    xml = tmp_path/'tree.xml'
    xml.write_text('''<SpeedTreeRaw><Bones>
        <Bone ID="0" ParentID="-1" StartX="0" StartY="0" StartZ="0" EndX="0" EndY="0" EndZ="1" Radius="0.2" Generator="Group_0"/>
        <Bone ID="1" ParentID="0" StartX="0" StartY="0" StartZ="1" EndX="0" EndY="0" EndZ="2" Radius="0.1" Generator="Group_0"/>
        <Bone ID="2" ParentID="0" StartX="0.2" StartY="0" StartZ="0.7" EndX="1" EndY="0" EndZ="1" Radius="0.03" Generator="Group_1"/>
        </Bones></SpeedTreeRaw>''')
    result = generate_wind_json(str(xml), str(tmp_path/'tree.json'), profile=FORCE_BASED)
    assert reads == [str(xml)]  # Joint identity and structural sections share one snapshot.
    assignments = result.dynamic_wind.joint_assignments
    assert assignments[0].radius_samples_m == ()
    assert assignments[1].radius_samples_m[0] / assignments[2].radius_samples_m[0] == pytest.approx(0.2/0.03)
    assert not result.dynamic_wind.warnings
    xml.write_text(xml.read_text().replace('Radius="0.2"','').replace('Radius="0.1"','').replace('Radius="0.03"',''))
    missing = generate_wind_json(str(xml), str(tmp_path/'missing.json'), profile=FORCE_BASED)
    assert reads == [str(xml), str(xml)]
    assert missing.dynamic_wind.warnings
    assert all(not a.radius_samples_m for a in missing.dynamic_wind.joint_assignments)


def test_advanced_editor_preserves_both_profiles_and_final_assignment(qtbot, tmp_path):
    from pathlib import Path
    from xml_to_usda.qt_ui.wind_preview import WindPreviewDialog
    from xml_to_usda.qt_ui.force_wind_editor import ForceWindEditor
    from xml_to_usda.wind_preview_service import WindPreviewRequest, generate_wind_preview_from_request
    from xml_to_usda.qt_ui.dependencies import build_default_dependencies
    from xml_to_usda.qt_ui.persistence import UiShellState
    from xml_to_usda.qt_ui.theme import load_theme
    from xml_to_usda.qt_ui.window import MainWindow

    source = Path(__file__).parents[1]/'samples/speedtree/simple_tree/variants/SimpleTree_01.xml'
    preview = generate_wind_preview_from_request(WindPreviewRequest(str(source)))
    settings_path = tmp_path / 'settings.json'
    window = MainWindow(load_theme(), UiShellState(help_prompt_dismissed=True),
        dependencies=build_default_dependencies(), state_path=tmp_path/'shell.json',
        operator_settings_path=settings_path)
    qtbot.addWidget(window)
    window._persistence_suspended = True
    window.source_input.setText(str(source))
    window._handle_wind_data_loaded(preview.dynamic_wind, used_retry=False)
    dialog = WindPreviewDialog(preview=preview, profile=FORCE_BASED,
        initial_wind_data=window._wind_export_data(), wind_session_changed=window._save_wind_preview_session)
    qtbot.addWidget(dialog)
    window._wind_preview_dialog = dialog
    dialog.show()
    dialog._toggle_group_settings('base:0')
    editor = dialog.findChild(ForceWindEditor)
    editor.overrides['tip_max_bend_angle'].setChecked(True)
    editor.editors['tip_max_bend_angle'].spin.setValue(135)
    dialog.set_profile('legacy')
    dialog._set_group_setting('base:0', 'min_influence', .17)
    dialog.set_profile(FORCE_BASED)
    assert window._wind_export_data() == dialog._current_dynamic_wind()
    window.wind_panel._rows[0].force_editor.editors['wind_response_scale'].spin.setValue(2.5)
    assert dialog._current_dynamic_wind().simulation_groups[0].force.wind_response_scale == 2.5
    window._save_operator_state()
    saved = load_gui_settings(settings_path)
    assert saved.wind_preview_session == json.loads(json.dumps(dialog.wind_session_snapshot()))
    snapshot = dialog.wind_session_snapshot()
    restored = WindPreviewDialog(preview=preview, profile=FORCE_BASED, wind_session_snapshot=snapshot)
    qtbot.addWidget(restored)
    data = restored._current_dynamic_wind()
    assert data.simulation_groups[0].force.tip_max_bend_angle == 135
    assert data.simulation_groups[0].min_influence == .17
    assert wind_data_from_settings(snapshot['export_data']) == data
    assert {a.joint_name for a in data.joint_assignments} == {j.name for j in preview.source_model.skeleton}
