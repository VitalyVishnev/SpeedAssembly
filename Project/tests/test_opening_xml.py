from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from xml_to_usda import discovery_service as service, opening_xml
from xml_to_usda.opening_xml import _read_native_opening as read_opening_xml
from xml_to_usda.source_limits import SourceLimits
from xml_to_usda.xml_reader import read_source_xml


PROJECT = Path(__file__).resolve().parents[1]
SIMPLE = PROJECT / 'samples/speedtree/simple_tree/variants/SimpleTree_01.xml'


@pytest.mark.parametrize('inspect', [opening_xml.inspect_source_opening, opening_xml.read_authored_wind_skeleton])
@pytest.mark.parametrize('failure', ['missing_frozen', 'version', 'rejected_source'])
def test_opening_views_do_not_hide_native_failures_with_canonical_fallback(inspect, failure, monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError('A broken native reader or rejected source must not silently select Python')
    def missing(_name):
        raise ModuleNotFoundError('missing native reader', name='xml_to_usda._xml_reader')
    def rejected(*_args):
        raise ValueError('rejected source')
    monkeypatch.setattr(opening_xml, 'read_source_xml', forbidden)
    monkeypatch.setattr(opening_xml, 'iterparse_source_xml', forbidden)
    if failure == 'missing_frozen':
        monkeypatch.setattr(opening_xml.sys, 'frozen', True, raising=False)
        monkeypatch.setattr(opening_xml.importlib, 'import_module', missing)
        error, message = RuntimeError, 'missing'
    else:
        native = SimpleNamespace(API_VERSION=0 if failure == 'version' else 1, read_opening=rejected)
        monkeypatch.setattr(opening_xml.importlib, 'import_module', lambda _name: native)
        error, message = (RuntimeError, 'mismatch') if failure == 'version' else (ValueError, 'rejected source')
    with pytest.raises(error, match=message):
        inspect(str(SIMPLE))


@pytest.mark.parametrize('path', [SIMPLE, *sorted((PROJECT / 'tests/data').glob('*.xml'))])
def test_native_opening_preserves_rows_normalized_warnings_and_structural_classification(path, monkeypatch):
    pytest.importorskip('xml_to_usda._xml_reader')
    actual = service.discover_source_rows(service.SourceDiscoveryRequest(str(path)))
    ground = service.discover_source_rows(service.SourceDiscoveryRequest(str(path), is_ground_cover=True))
    if ground.wind_data is not None:
        assert ground.wind_data.is_ground_cover
        assert all(not group.is_trunk_group for group in ground.wind_data.simulation_groups)
    monkeypatch.setattr(opening_xml, '_read_native_opening', lambda *_args, **_kwargs: None)
    expected = service.discover_source_rows(service.SourceDiscoveryRequest(str(path)))
    assert replace(actual, wind_data=None) == expected
    if actual.wind_data is not None:
        from xml_to_usda import wind_pipeline
        assert actual.wind_data == wind_pipeline.inspect_wind_data(str(path))


@pytest.mark.parametrize(('xml', 'limits'), [
    ('<Tree/>', SourceLimits(max_xml_bytes=3)),
    ('<Tree><a><b/></a></Tree>', SourceLimits(max_xml_depth=2)),
    ('<Tree><X>1 2 3</X></Tree>', SourceLimits(max_packed_field_values=2)),
    ('<Tree><X>1,2</X><Y>3 4</Y></Tree>', SourceLimits(max_total_packed_values=3)),
    ('<Tree><LeafReferences><X>1 2</X></LeafReferences></Tree>', SourceLimits(max_repeated_part_instances=1)),
    ('<Tree><TriangleIndices>0 1 2</TriangleIndices></Tree>', SourceLimits(max_mesh_face_vertex_entries=2)),
    ('<Tree><X>1<!-- comment --> 2<![CDATA[ 3]]></X></Tree>', SourceLimits(max_packed_field_values=2)),
    ('<Tree><LeafReferences><X>1<!-- comment --> 2</X></LeafReferences></Tree>', SourceLimits(max_repeated_part_instances=1)),
])
def test_native_reader_enforces_every_budget_before_discarding_geometry(xml, limits, tmp_path):
    pytest.importorskip('xml_to_usda._xml_reader')
    path = tmp_path / 'budget.xml'
    path.write_text(xml, encoding='utf-8')
    with pytest.raises(ValueError, match='source budget'):
        read_source_xml(path, limits=limits)
    with pytest.raises(ValueError, match='source budget'):
        read_opening_xml(str(path), limits=limits)


@pytest.mark.parametrize('xml', [
    '<!DOCTYPE Tree><Tree/>', '<!DOCTYPE Tree [<!ENTITY x "x">]><Tree/>',
    '<Tree><x></Tree>', '<Tree/> <Other/>', '<Tree a="1" a="2"/>',
    '<Tree>&unknown;</Tree>', '<Tree>\x01</Tree>', '<Tree><!-- bad -- comment --></Tree>',
])
def test_native_reader_rejects_unsafe_or_malformed_xml(xml, tmp_path):
    pytest.importorskip('xml_to_usda._xml_reader')
    path = tmp_path / 'bad.xml'
    path.write_text(xml, encoding='utf-8')
    with pytest.raises(ValueError):
        read_opening_xml(str(path))


def test_native_projection_preserves_metadata_bone_children_and_escaped_names(tmp_path, monkeypatch):
    pytest.importorskip('xml_to_usda._xml_reader')
    path = tmp_path / 'metadata.xml'
    path.write_text('''<Tree><Metadata up_axis="Z"/><Ignored upAxis="Y" units="m"/>
    <Bones><Bone ID="0" Generator="Group_0"><StartX>0</StartX><StartY>0</StartY>
    <StartZ>0</StartZ><EndX>0</EndX><EndY>1</EndY><EndZ>0</EndZ></Bone></Bones>
    <Materials><Material ID="1" Name="A&amp;B &quot;test&quot;"/></Materials>
    <Objects><Object ID="1"><Points><X>0 1 0</X><Y>0 0 1</Y><Z>0 0 0</Z></Points>
    <Triangles Material="1"><PointIndices>0 1 2</PointIndices></Triangles></Object></Objects></Tree>''', encoding='utf-8')
    opening = read_opening_xml(str(path))
    assert opening.projected
    assert opening.document.tree.findtext('.//Points/X') is None
    actual = service.discover_source_rows(service.SourceDiscoveryRequest(str(path)))
    monkeypatch.setattr(opening_xml, '_read_native_opening', lambda *_args, **_kwargs: None)
    expected = service.discover_source_rows(service.SourceDiscoveryRequest(str(path)))
    assert replace(actual, wind_data=None) == expected


@pytest.mark.parametrize('xml', [
    b'<?xml version="1.0" encoding="iso-8859-1"?><Tree name="caf\xe9"/>',
    '<Tree xmlns="urn:test"><Bone ID="0"/></Tree>'.encode(),
    '<Tree xml:lang="ru"><Bone ID="0"/></Tree>'.encode(),
    '<?xml version="1.0" encoding="utf-16"?><Tree/>'.encode('utf-16'),
    '<Tree><Bone ID="0"><Bone ID="1"/></Bone></Tree>'.encode(),
    '<Tree><LeafReferences><Bone ID="0"/></LeafReferences></Tree>'.encode(),
])
def test_legacy_encodings_and_namespaces_keep_canonical_reader_semantics(xml, tmp_path):
    pytest.importorskip('xml_to_usda._xml_reader')
    path = tmp_path / 'compatible.xml'
    path.write_bytes(xml)
    assert read_opening_xml(str(path)) is None
    assert read_source_xml(path).tree.getroot() is not None
