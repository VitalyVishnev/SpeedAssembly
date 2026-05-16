from __future__ import annotations


def test_pipeline_public_facade_exports_stable_symbols() -> None:
    from xml_to_usda import pipeline

    assert callable(pipeline.inspect_source)
    assert callable(pipeline.discover_part_prototypes)
    assert callable(pipeline.discover_source_materials)
    assert callable(pipeline.load_canonical_model)
    assert callable(pipeline.load_source_tree_model)
    assert callable(pipeline.resolve_assembly_model)
    assert callable(pipeline.load_resolved_assembly_model)
    assert callable(pipeline.convert_file)
    assert callable(pipeline.convert_request)
    assert callable(pipeline.inspect_wind_data)
    assert callable(pipeline.generate_wind_json)
    assert callable(pipeline._apply_material_policy)
    assert pipeline.REPO_ROOT.name == "XMLtoUSDAconverter"


def test_usda_writer_public_facade_exports_stable_symbols() -> None:
    from xml_to_usda import usda_writer

    assert callable(usda_writer.render_usda)
    assert callable(usda_writer.write_usda_document)
