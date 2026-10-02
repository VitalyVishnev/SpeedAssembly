from __future__ import annotations

from pathlib import Path

import pytest

from xml_to_usda.source_limits import SourceLimits
from xml_to_usda.source_analysis import discover_source_materials
from xml_to_usda.xml_reader import read_source_xml


def _write_entity_xml(path: Path) -> Path:
    path.write_text(
        """<?xml version="1.0"?>
<!DOCTYPE SpeedTreeRaw [
  <!ENTITY injected "expanded">
]>
<SpeedTreeRaw><Materials><Material ID="1" Name="&injected;" /></Materials></SpeedTreeRaw>
""",
        encoding="utf-8",
    )
    return path


def test_read_source_xml_rejects_dtd_and_entities(tmp_path: Path) -> None:
    xml_path = _write_entity_xml(tmp_path / "entity.xml")

    with pytest.raises(ValueError, match="DTD or entity declarations"):
        read_source_xml(xml_path)


def test_read_source_xml_uses_explicit_binary_parser_adapter(monkeypatch, tmp_path: Path) -> None:
    import xml_to_usda.xml_reader as xml_reader

    xml_path = tmp_path / "simple.xml"
    xml_path.write_text("<SpeedTreeRaw />", encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_parse(source, **kwargs):
        observed["source_has_read"] = hasattr(source, "read")
        observed["has_parser"] = kwargs.get("parser") is not None
        return xml_reader.ET.ElementTree(xml_reader.ET.Element("SpeedTreeRaw"))

    monkeypatch.setattr(xml_reader.sys, "frozen", True, raising=False)
    monkeypatch.setattr(xml_reader.ET, "parse", fake_parse)

    assert read_source_xml(xml_path).root_tag == "SpeedTreeRaw"
    assert observed["source_has_read"] is True
    assert observed["has_parser"] is True


def test_streamed_source_analysis_rejects_dtd_and_entities(tmp_path: Path) -> None:
    xml_path = _write_entity_xml(tmp_path / "entity.xml")

    with pytest.raises(ValueError, match="DTD or entity declarations"):
        discover_source_materials(str(xml_path))


def test_read_source_xml_rejects_files_over_source_budget(tmp_path: Path) -> None:
    xml_path = tmp_path / "too_large.xml"
    xml_path.write_text("<SpeedTreeRaw />", encoding="utf-8")

    with pytest.raises(ValueError, match="XML file size"):
        read_source_xml(xml_path, limits=SourceLimits(max_xml_bytes=4))


def test_read_source_xml_rejects_packed_numeric_fields_over_source_budget(tmp_path: Path) -> None:
    xml_path = tmp_path / "too_many_values.xml"
    xml_path.write_text("<SpeedTreeRaw><Meshes><Mesh><Vertices><X>1 2 3</X></Vertices></Mesh></Meshes></SpeedTreeRaw>", encoding="utf-8")

    with pytest.raises(ValueError, match="Packed XML field X"):
        read_source_xml(xml_path, limits=SourceLimits(max_packed_field_values=2))
