from __future__ import annotations

from array import array
from dataclasses import replace
import os
from types import MethodType, SimpleNamespace

import pytest


pytest.importorskip("PySide6")
pytest.importorskip("pytestqt")
pytestmark = pytest.mark.qt

from xml_to_usda.models import GeometryBuffer, Joint, Matrix4d, MeshData, Vector3
from xml_to_usda.proxy_collision import ProxyCollisionMode, ProxyCollisionSource
from xml_to_usda.proxy_mesh_service import (
    PROXY_METHOD_DENSITY_FIELD,
    ProxyMeshResult,
    ProxyMeshSettings,
    ProxyMeshSourceRequest,
    ProxyMeshJobResult,
    proxy_source_signature,
)
from xml_to_usda.proxy_viewport_scene import build_proxy_viewport_scene
from xml_to_usda.qt_ui.proxy_preview import ProxyPreviewDialog
from xml_to_usda.qt_ui.background_jobs import QtBackgroundJobsController, _ProxyPreviewWork
from xml_to_usda.qt_ui.window import MainWindow


def test_proxy_preview_exposes_persisted_collision_contract(qtbot, tmp_path) -> None:
    generated: list[tuple[str, ProxyMeshSettings]] = []
    default_output = tmp_path / "tree_proxy.usda"
    dialog = ProxyPreviewDialog(
        settings=ProxyMeshSettings(),
        output_path=str(default_output),
        on_generate_proxy=lambda path, settings: generated.append((path, settings)),
    )
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "method_combo")
    assert dialog.density_resolution_spin.maximum() == 512
    assert dialog.settings().method == PROXY_METHOD_DENSITY_FIELD
    assert dialog.output_path_edit.text() == str(default_output)
    explicit_output = tmp_path / "custom.usda"
    dialog.output_path_edit.setText(str(explicit_output))
    dialog.generate_proxy_button.click()
    assert generated == [(str(explicit_output), dialog.settings())]
    assert dialog.collision_check.isChecked()
    assert dialog.collision_type_combo.currentData() == ProxyCollisionMode.BOX.value
    assert dialog.collision_height_spin.value() == pytest.approx(0.5)
    assert dialog.collision_width_spin.value() == pytest.approx(1.0)
    assert not dialog.collision_per_stem_check.isChecked()

    dialog.collision_type_combo.setCurrentIndex(dialog.collision_type_combo.findData(ProxyCollisionMode.CAPSULE.value))
    dialog.collision_height_spin.setValue(0.75)
    dialog.collision_width_spin.setValue(1.5)
    dialog.collision_per_stem_check.setChecked(True)

    collision = dialog.settings().collision
    assert collision.mode == ProxyCollisionMode.CAPSULE
    assert collision.height_multiplier == pytest.approx(0.75)
    assert collision.width_multiplier == pytest.approx(1.5)
    assert collision.one_per_stem is True


def test_proxy_preview_switches_viewport_silhouette_mode(qtbot) -> None:
    proxy = ProxyMeshResult(
        mesh=GeometryBuffer(
            name="ProxyMesh",
            point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
            face_vertex_counts=array("i", (3,)),
            face_vertex_indices=array("i", (0, 1, 2)),
        ),
        settings=ProxyMeshSettings(),
        method=PROXY_METHOD_DENSITY_FIELD,
        source_instance_count=0,
        included_base_mesh=True,
    )
    dialog = ProxyPreviewDialog(
        settings=proxy.settings,
        initial_proxy=proxy,
        source_scene=build_proxy_viewport_scene(proxy),
    )
    qtbot.addWidget(dialog)

    assert dialog.viewport.mode_switch.height() <= 26
    assert dialog.viewport.shaded_button.height() >= dialog.viewport.shaded_button.fontMetrics().height() + 2
    assert dialog.viewport.mode_switch.pos().x() == 8
    assert dialog.viewport.mode_switch.pos().y() == 8
    assert dialog.viewport.silhouette_button.isEnabled()
    dialog.viewport.silhouette_button.click()
    assert dialog.viewport.silhouette_diff is True
    dialog.viewport.shaded_button.click()
    assert dialog.viewport.silhouette_diff is False
def test_proxy_cache_reuses_collision_but_reloads_overwritten_xml(tmp_path) -> None:
    starts = []
    handled = []
    background = SimpleNamespace(
        proxy_preview_running=False,
        cancel_proxy_mesh_preview=lambda: None,
        start_proxy_mesh_preview=lambda request, settings, **kwargs: starts.append((request, settings, kwargs)),
    )
    proxy = ProxyMeshResult(
        mesh=GeometryBuffer(
            name="ProxyMesh",
            point_components=array("f", (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0)),
            face_vertex_counts=array("i", (3,)),
            face_vertex_indices=array("i", (0, 1, 2)),
        ),
        settings=ProxyMeshSettings(),
        method=PROXY_METHOD_DENSITY_FIELD,
        source_instance_count=0,
        included_base_mesh=True,
        collision_meshes=(
            MeshData(
                name="UBX_ProxyMesh_00",
                points=(Vector3(0.0, 0.0, 0.0), Vector3(1.0, 0.0, 0.0), Vector3(0.0, 1.0, 0.0)),
                face_vertex_counts=(3,),
                face_vertex_indices=(0, 1, 2),
            ),
        ),
        collision_source=ProxyCollisionSource(
            skeleton=(
                Joint(
                    name="root",
                    generator_level=0,
                    bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
                    bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 2.0, 0.0)),
                ),
            ),
            stem_axes=(("root",),),
            points=(
                Vector3(-0.5, 0.0, -0.5),
                Vector3(0.5, 0.0, 0.5),
                Vector3(-0.5, 1.0, -0.5),
                Vector3(0.5, 1.0, 0.5),
            ),
            point_joint_indices=(0, 0, 0, 0),
        ),
    )
    fake = SimpleNamespace(
        _proxy_mesh_settings=proxy.settings,
        geometry_panel=SimpleNamespace(apply_proxy_settings=lambda _settings: None),
        _proxy_mesh_preview_result=None,
        _proxy_mesh_preview_input_path="",
        _proxy_mesh_preview_signature=None,
        _proxy_source_preview_scene=build_proxy_viewport_scene(proxy),
        _proxy_source_preview_input_path="",
        _proxy_source_preview_signature=None,
        _proxy_preview_dialog=SimpleNamespace(
            current_proxy=proxy,
            isVisible=lambda: True,
            set_source_scene=lambda scene: cleared_scenes.append(scene),
        ),
        _schedule_operator_state_save=lambda: None,
        _trace=lambda *_args, **_kwargs: None,
        _background_jobs=background,
        _handle_proxy_preview_result=lambda result: handled.append(result),
    )
    for name in ("_proxy_preview_result_for_input", "_proxy_source_scene_for_input", "_cache_proxy_preview_result"):
        setattr(fake, name, MethodType(getattr(MainWindow, name), fake))
    cleared_scenes = []
    xml_path = tmp_path / "tree.xml"
    xml_path.write_text("old source", encoding="utf-8")
    input_path = str(xml_path)
    request = ProxyMeshSourceRequest(input_path=input_path)
    old_signature = proxy_source_signature(input_path)
    fake._cache_proxy_preview_result(input_path, proxy)
    fake._proxy_source_preview_input_path = input_path
    fake._proxy_source_preview_signature = old_signature

    disabled = replace(proxy.settings, collision=replace(proxy.settings.collision, enabled=False))
    MainWindow._handle_proxy_preview_settings_changed(fake, input_path, request, disabled)
    fake._cache_proxy_preview_result(input_path, handled[-1])
    MainWindow._handle_proxy_preview_settings_changed(fake, input_path, request, proxy.settings)

    assert starts == []
    assert handled[-1].mesh is proxy.mesh
    assert handled[-1].collision_meshes is proxy.collision_meshes

    capsule = replace(
        proxy.settings,
        collision=replace(proxy.settings.collision, mode=ProxyCollisionMode.CAPSULE),
    )
    MainWindow._handle_proxy_preview_settings_changed(fake, input_path, request, capsule)
    assert starts == []
    assert handled[-1].mesh is proxy.mesh
    assert [mesh.name for mesh in handled[-1].collision_meshes] == ["UCP_ProxyMesh_00"]

    # Re-export at the same path must not compare fresh low-poly with old high-poly,
    # reuse old collision, or export the stale mesh still visible in the dialog.
    xml_path.write_text("new source", encoding="utf-8")
    os.utime(xml_path, ns=(old_signature[2], old_signature[2] + 10_000_000))
    assert proxy_source_signature(input_path)[1] == old_signature[1]
    assert fake._proxy_preview_result_for_input(input_path) is None

    errors = []
    controller = SimpleNamespace(
        _proxy_preview_job=SimpleNamespace(
            error_traceback=None,
            request=request,
            settings=_ProxyPreviewWork(proxy.settings, source_signature=old_signature),
        ),
        _trace_worker=lambda *_args, **_kwargs: None,
        _handle_proxy_preview_error=errors.append,
    )
    QtBackgroundJobsController._handle_proxy_preview_job_result(controller, ProxyMeshJobResult(proxy=proxy))
    assert errors == ["Source XML changed during Proxy Preview generation. Regenerate the preview."]
    assert fake._proxy_source_scene_for_input(input_path) is None
    assert MainWindow._current_preview_proxy_for_export(fake, input_path, proxy.settings) is None
    MainWindow._handle_proxy_preview_settings_changed(fake, input_path, request, proxy.settings)
    assert starts == [(request, proxy.settings, {"include_source_scene": True})]
    assert cleared_scenes == [None]
    fake._cache_proxy_preview_result(input_path, proxy, source_signature=old_signature)
    assert fake._proxy_preview_result_for_input(input_path) is None
