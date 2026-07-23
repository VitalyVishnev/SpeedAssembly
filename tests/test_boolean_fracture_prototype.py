from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import numpy as np
import pytest

import xml_to_usda.boolean_fracture_prototype as prototype_module
from xml_to_usda.boolean_fracture_prototype import (
    SYNTHETIC_CYLINDER_CUT_TOKEN,
    BooleanCutPrototypeSettings,
    BooleanMultiPrototypeSettings,
    build_boolean_cut_prototype,
    build_synthetic_boolean_cylinder_model,
    boolean_multi_settings_from_fracture,
    prepare_boolean_fracture_source,
    prepare_boolean_cut_prototype,
    prepare_boolean_multi_prototype,
)
from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.fracture_service import FractureSettings, plan_fracture
from xml_to_usda.models import Joint, Matrix4d, Vector3


def _build(*, intensity: float = 0.35, chip_scale: float = 0.65, density: int = 12):
    return build_boolean_cut_prototype(
        build_synthetic_boolean_cylinder_model(),
        BooleanCutPrototypeSettings(
            SYNTHETIC_CYLINDER_CUT_TOKEN,
            intensity=intensity,
            chip_scale=chip_scale,
            remesh_density=density,
        ),
    )


def _referenced_points(mesh):
    return tuple(mesh.points[index] for index in sorted(set(mesh.face_vertex_indices)))


def test_uint32_triangle_connectivity_uses_plain_integer_edge_keys() -> None:
    components = prototype_module._triangle_components(
        np.asarray(((0, 1, 2), (2, 1, 3), (4, 5, 6)), dtype=np.uint32)
    )

    assert tuple(component.tolist() for component in components) == ([0, 1], [2])


def test_open_cylinder_closes_two_loops_and_boolean_preserves_only_original_open_ends() -> None:
    result = _build(intensity=0.0)
    stages = dict(result.diagnostics.stages)

    assert result.diagnostics.closure_face_count == 44
    assert stages["Original Shell"].boundary_count == 2
    assert stages["Closed Solid"].boundary_count == 0
    assert stages["Parent Stub"].boundary_count == 1
    assert stages["Detached Branch"].boundary_count == 1
    assert result.diagnostics.cap_vertex_count == 24
    assert math.isclose(
        stages["Parent Stub"].volume + stages["Detached Branch"].volume,
        stages["Closed Solid"].volume,
        rel_tol=1e-5,
        abs_tol=1e-9,
    )


def test_synthetic_manual_cut_has_a_separate_connector_but_cuts_the_physical_bone_midpoint() -> None:
    model = build_synthetic_boolean_cylinder_model()
    root, child = model.skeleton

    assert root.bind_translate != child.bind_translate
    assert child.bind_end_translate is not None
    result = build_boolean_cut_prototype(
        model,
        BooleanCutPrototypeSettings(SYNTHETIC_CYLINDER_CUT_TOKEN, intensity=0.0, remesh_density=12),
    )
    assert result.diagnostics.cut_origin.x == 0.0
    assert result.diagnostics.cut_origin.y == 0.0
    assert result.diagnostics.cut_origin.z == 0.0


def test_zero_intensity_is_flat_and_noise_is_one_sided_toward_child() -> None:
    flat = _build(intensity=0.0)
    noisy = _build(intensity=0.8)

    assert {round(point.y, 8) for point in _referenced_points(flat.cutter_surface)} == {0.0}
    noisy_heights = [point.y for point in _referenced_points(noisy.cutter_surface)]
    assert min(noisy_heights) >= 0.0
    assert max(noisy_heights) > 0.0


def test_density_only_changes_tessellation_and_chip_scale_changes_shape() -> None:
    coarse = _build(density=8)
    dense = _build(density=20)
    broad = _build(chip_scale=1.3, density=12)
    baseline = _build(chip_scale=0.65, density=12)

    assert coarse.diagnostics.cutter_triangle_count < dense.diagnostics.cutter_triangle_count
    assert len(broad.cutter_surface.face_vertex_counts) == len(baseline.cutter_surface.face_vertex_counts)
    assert tuple((point.x, point.y, point.z) for point in broad.cutter_surface.points) != tuple(
        (point.x, point.y, point.z) for point in baseline.cutter_surface.points
    )


def test_same_input_and_settings_are_deterministic() -> None:
    first = _build()
    second = _build()

    for first_mesh, second_mesh in (
        (first.closed_solid, second.closed_solid),
        (first.cutter_surface, second.cutter_surface),
        (first.parent_result, second.parent_result),
        (first.child_result, second.child_result),
    ):
        assert first_mesh.points == second_mesh.points
        assert first_mesh.face_vertex_indices == second_mesh.face_vertex_indices
        assert first_mesh.vertex_colors == second_mesh.vertex_colors


def test_requested_amplitude_is_scaled_uniformly_before_the_terminal_joint() -> None:
    result = _build(intensity=20.0, density=15)

    assert result.diagnostics.requested_amplitude == pytest.approx(2.45)
    assert result.diagnostics.effective_amplitude == pytest.approx(result.diagnostics.amplitude_limit_distance)
    assert result.diagnostics.effective_amplitude < result.diagnostics.requested_amplitude
    assert result.diagnostics.amplitude_limit_reason == "terminal"
    assert result.diagnostics.amplitude_limit_joint_token == "bone_001"


def test_bend_angle_stops_at_the_current_physical_bone() -> None:
    model = build_synthetic_boolean_cylinder_model()
    root, source_bone = model.skeleton
    source_bone = replace(source_bone, bind_end_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)))
    bent_bone = Joint(
        name="bone_002",
        source_id=2,
        parent=source_bone.name,
        bind_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
        rest_transform=Matrix4d.from_translation(Vector3(0.0, 0.0, 0.0)),
        bind_end_transform=Matrix4d.from_translation(Vector3(2.0, 2.0, 0.0)),
    )
    model = replace(model, skeleton=(root, source_bone, bent_bone))

    stopped = build_boolean_cut_prototype(
        model,
        BooleanCutPrototypeSettings(SYNTHETIC_CYLINDER_CUT_TOKEN, intensity=20.0, max_bend_angle_degrees=30.0),
    )
    continued = build_boolean_cut_prototype(
        model,
        BooleanCutPrototypeSettings(SYNTHETIC_CYLINDER_CUT_TOKEN, intensity=20.0, max_bend_angle_degrees=60.0),
    )

    assert stopped.diagnostics.amplitude_limit_reason == "bend"
    assert stopped.diagnostics.amplitude_limit_joint_token == "bone_002"
    assert stopped.diagnostics.amplitude_limit_distance < continued.diagnostics.amplitude_limit_distance
    assert continued.diagnostics.amplitude_limit_reason == "terminal"


def test_boolean_results_transfer_source_attributes_and_fill_caps() -> None:
    result = _build(intensity=4.0, density=12)

    for mesh in (result.parent_result, result.child_result):
        assert len(mesh.normals) == len(mesh.face_vertex_indices)
        assert all(
            math.isclose(normal.x * normal.x + normal.y * normal.y + normal.z * normal.z, 1.0, rel_tol=1e-6)
            for normal in mesh.normals
        )
        assert len(mesh.uv_coords) == len(mesh.face_vertex_indices)
        assert len(mesh.secondary_uv_coords) == len(mesh.face_vertex_indices)
        assert len(mesh.vertex_colors) == len(mesh.face_vertex_indices)
        assert len(mesh.skel_joint_indices) == len(mesh.points) * mesh.skel_element_size
        assert len(mesh.skel_joint_weights) == len(mesh.points) * mesh.skel_element_size
        assert all(math.isclose(weight, 1.0) for weight in mesh.skel_joint_weights)
        assert sorted(face for section in mesh.sections for face in section.face_indices) == list(
            range(len(mesh.face_vertex_counts))
        )


def test_boolean_multi_generates_normals_when_untouched_source_chunks_have_none() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    assert model.base_mesh is not None
    model = replace(model, base_mesh=replace(model.base_mesh, normals=()))
    settings = BooleanMultiPrototypeSettings(auto_branch_count=3, intensity=0.0, remesh_density=4)

    result = prepare_boolean_multi_prototype(model, settings).build(settings)
    geometry = prototype_module.fracture_geometry_from_boolean_multi(result)

    assert all(len(piece.base_mesh.normals) == len(piece.base_mesh.face_vertex_indices) for piece in geometry.pieces)


def test_prepared_session_regeneration_does_not_replan(monkeypatch) -> None:
    model = build_synthetic_boolean_cylinder_model()
    session = prepare_boolean_cut_prototype(model, SYNTHETIC_CYLINDER_CUT_TOKEN)

    def fail_replan(*_args, **_kwargs):
        raise AssertionError("interactive regeneration must reuse the prepared fracture plan")

    monkeypatch.setattr(prototype_module, "plan_fracture", fail_replan)
    result = session.build(
        BooleanCutPrototypeSettings(SYNTHETIC_CYLINDER_CUT_TOKEN, intensity=20.0, remesh_density=8)
    )

    assert result.stage_timings[0] == ("reuse_prepared_cut", 0.0)


def test_multi_prototype_assembles_independent_real_tree_cuts() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    settings = BooleanMultiPrototypeSettings(auto_branch_count=3, intensity=0.0, remesh_density=4)

    result = prepare_boolean_multi_prototype(model, settings).build(settings)

    assert len(result.cuts) == 3
    assert len(result.pieces) == 4
    assert len({cut.diagnostics.selected_component_index for cut in result.cuts}) == 3
    assert all(piece.meshes for piece in result.pieces)


def test_detailed_cuts_use_the_fracture_auto_branch_cut_offset() -> None:
    settings = boolean_multi_settings_from_fracture(
        FractureSettings(target_piece_count=2, auto_branch_cut_offset=0.62)
    )

    assert settings.auto_branch_cut_offset == 0.62


def test_big_spruce_cut_selects_the_dominant_bone_shell_when_a_child_twig_crosses_the_plane() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/BigSpruce/SkeletalAssemblyTest_Spruce_Big_low.xml"
    model = load_source_tree_model(source)[1]
    context = prepare_boolean_fracture_source(model)
    plan = plan_fracture(
        model,
        FractureSettings(
            target_piece_count=37,
            force_stump_piece=True,
            separate_stems=True,
            branch_height_bias=-0.05,
        ),
        analysis_cache=context.analysis_cache,
    )

    session = prepare_boolean_cut_prototype(
        model,
        "bone_033",
        source_context=context,
        fracture_plan=plan,
    )

    component = context.components[session.selected_component_index]
    owner_by_face = context.analysis_cache.base_face_owner_by_index
    anchored = sum(
        owner_by_face[int(context.source_face_indices[triangle])] == "bone_033"
        for triangle in component
    )
    assert anchored > len(component) / 2


def test_prepared_multi_session_does_not_retain_native_manifold_objects() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    settings = BooleanMultiPrototypeSettings(auto_branch_count=3, intensity=0.0, remesh_density=4)

    session = prepare_boolean_multi_prototype(model, settings)
    session.build(settings)

    for cut_session in session._cut_sessions:
        assert all(
            type(getattr(cut_session._prepared, field_name)).__module__ != "manifold3d"
            for field_name in cut_session._prepared.__dataclass_fields__
        )


def test_multi_prototype_keeps_one_boolean_stump_per_disconnected_stem() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "samples/speedtree/simple_tree/variants/SimpleTree_02_three_trunks.xml"
    )
    model = load_source_tree_model(source)[1]
    settings = BooleanMultiPrototypeSettings(
        auto_branch_count=0,
        intensity=0.0,
        remesh_density=4,
        force_stump_piece=True,
        separate_stems=True,
    )

    result = prepare_boolean_multi_prototype(model, settings).build(settings)

    assert len(result.plan.pieces) == 6
    assert len(result.cuts) == 3
    assert {cut.reason for cut in result.cut_sites} == {"stump_piece"}
    assert len({cut.diagnostics.selected_component_index for cut in result.cuts}) == 3


def test_multi_replan_reuses_unchanged_cut_sessions_and_results() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    branch_settings = BooleanMultiPrototypeSettings(auto_branch_count=3, intensity=0.0, remesh_density=4)
    branch_session = prepare_boolean_multi_prototype(model, branch_settings)
    branch_result = branch_session.build(branch_settings)
    expanded_settings = replace(branch_settings, auto_branch_count=4)

    expanded_session = prepare_boolean_multi_prototype(
        model,
        expanded_settings,
        previous_session=branch_session,
    )
    expanded_result = expanded_session.build(expanded_settings)

    old_sessions = dict(zip(branch_session._cut_sites, branch_session._cut_sessions))
    old_results = dict(zip(branch_result.cut_sites, branch_result.cuts))
    for cut_site, session, result in zip(
        expanded_session._cut_sites,
        expanded_session._cut_sessions,
        expanded_result.cuts,
    ):
        if cut_site in old_sessions:
            assert session is old_sessions[cut_site]
            assert result is old_results[cut_site]


def test_multi_prototype_sequences_stump_and_branch_cuts_on_one_shell() -> None:
    source = Path(__file__).resolve().parents[1] / "samples/speedtree/simple_tree/variants/SimpleTree_01.xml"
    model = load_source_tree_model(source)[1]
    settings = BooleanMultiPrototypeSettings(
        auto_branch_count=3,
        intensity=0.0,
        remesh_density=4,
        force_stump_piece=True,
    )

    session = prepare_boolean_multi_prototype(model, settings)
    result = session.build(settings)

    assert session._cut_sessions[0].selected_component_index == session._cut_sessions[1].selected_component_index
    assert len(result.cuts) == 4
    assert len(result.pieces) == 5
    assert all(piece.meshes for piece in result.pieces)
    for cut in result.cuts[:2]:
        assert cut.diagnostics.cap_vertex_count > 0
        for mesh in (cut.parent_result, cut.child_result):
            assert len(mesh.uv_coords) == len(mesh.face_vertex_indices)
            assert len(mesh.skel_joint_indices) == len(mesh.points) * mesh.skel_element_size
