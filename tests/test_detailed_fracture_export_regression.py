from __future__ import annotations

from pathlib import Path

from usda_test_inventory import UsdaInventory

import xml_to_usda.fracture_export_service as fracture_export_service
from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.fracture_collision import FractureCollisionMode, FractureCollisionSettings
from xml_to_usda.fracture_export_service import FractureExportRequest, export_fracture_usda_from_export_request
from xml_to_usda.fracture_service import FractureSettings
from xml_to_usda.skeleton_processing import apply_skinning_quality


SIMPLE_TREE_01 = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "speedtree"
    / "simple_tree"
    / "variants"
    / "SimpleTree_01.xml"
)


def test_detailed_boolean_export_preserves_repeated_parts_normals_and_collision(monkeypatch, tmp_path: Path) -> None:
    _, source_model, _ = load_source_tree_model(SIMPLE_TREE_01)
    default_skinning_model = apply_skinning_quality(source_model)
    boolean_meshes = {}
    authored_models = {}
    collision_inputs = []
    convert_boolean = fracture_export_service.fracture_geometry_from_boolean_multi
    build_collision = fracture_export_service.build_fracture_collision_primitives
    write_usda = fracture_export_service.write_resolved_usda_document

    def capture_boolean(result):
        geometry = convert_boolean(result)
        boolean_meshes.update((piece.piece.name, piece.base_mesh) for piece in geometry.pieces)
        return geometry

    def capture_collision(model, piece, settings, *, render_mesh_name):
        collision_inputs.append((piece.name, model.base_mesh, piece.base_face_indices))
        return build_collision(model, piece, settings, render_mesh_name=render_mesh_name)

    def capture_usda(resolved, *args, **kwargs):
        authored_models[resolved.output_stem] = resolved.authoring_model
        return write_usda(resolved, *args, **kwargs)

    monkeypatch.setattr(fracture_export_service, "fracture_geometry_from_boolean_multi", capture_boolean)
    monkeypatch.setattr(fracture_export_service, "build_fracture_collision_primitives", capture_collision)
    monkeypatch.setattr(fracture_export_service, "write_resolved_usda_document", capture_usda)

    result = export_fracture_usda_from_export_request(
        FractureExportRequest(
            input_path=str(SIMPLE_TREE_01),
            output_path=str(tmp_path / "Tree.usda"),
            collision_settings=FractureCollisionSettings(
                enabled=True,
                mode=FractureCollisionMode.CAPSULE,
            ),
        ),
        FractureSettings(
            target_piece_count=0,
            pinned_cut_joint_tokens=("bone_032",),
            detailed_cuts_enabled=True,
            detailed_cut_intensity=20.0,
            detailed_cut_density=8,
        ),
    )

    owned_indices = [index for piece in result.plan.pieces for index in piece.repeated_part_indices]
    assert sorted(owned_indices) == list(range(len(source_model.repeated_parts)))
    assert len(owned_indices) == len(set(owned_indices))
    assert result.plan.pieces[1].repeated_part_indices == (6,)

    collision_by_piece = {name: (mesh, face_indices) for name, mesh, face_indices in collision_inputs}
    assert set(boolean_meshes) == set(authored_models) == set(collision_by_piece)
    for output in result.outputs:
        piece = output.piece
        model = authored_models[piece.name]
        expected_parts = tuple(default_skinning_model.repeated_parts[index] for index in piece.repeated_part_indices)
        expected_keys = {part.prototype_key for part in expected_parts}

        assert model.repeated_parts == expected_parts
        assert {prototype.source_key for prototype in model.prototypes} == expected_keys
        assert model.static_collision_primitives

        base_mesh = model.base_mesh
        assert base_mesh is boolean_meshes[piece.name]
        assert len(base_mesh.normals) == sum(base_mesh.face_vertex_counts)
        collision_mesh, collision_faces = collision_by_piece[piece.name]
        assert collision_mesh is base_mesh
        assert collision_faces == tuple(range(len(base_mesh.face_vertex_counts)))

        text = Path(output.output_path).read_text(encoding="utf-8")
        inventory = UsdaInventory.from_text(text)
        base_path = (
            f"/{piece.name}/AssemblyPartsInstancer/Prototypes/{piece.name}_BaseMesh/"
            f"SM_{piece.name}_BaseMesh"
        )
        assert inventory.has_attribute(base_path, "normals")

    detached_text = Path(result.outputs[1].output_path).read_text(encoding="utf-8")
    assert "Twig_01" in detached_text
    assert "Twig_02" not in detached_text
