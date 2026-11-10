import json
from pathlib import Path

import pytest

from xml_to_usda.conversion_orchestrator import convert_request
from xml_to_usda.models import ConversionMode, ConversionRequest


pytest.importorskip("xml_to_usda._pve_growth")

TREE_XML = """<SpeedTreeRaw units="m" upAxis="Z">
    <Objects>
        <Object ID="1" AbsX="0" AbsY="0" AbsZ="0">
            <Spine Count="2"><X>0 0</X><Y>0 0</Y><Z>0 4</Z><Radius>1 0.5</Radius></Spine>
        </Object>
        <Object ID="2" ParentID="1" AbsX="1" AbsY="0" AbsZ="2">
            <Spine Count="2"><X>0 1</X><Y>0 0</Y><Z>0 1</Z><Radius>0.2 0.1</Radius></Spine>
        </Object>
    </Objects>
    <Bones>
        <Bone ID="1" StartX="0" StartY="0" StartZ="0" EndX="0" EndY="0" EndZ="4" Radius="0.9"/>
        <Bone ID="3" ParentID="1" StartX="1" StartY="0" StartZ="2" EndX="2" EndY="0" EndZ="3" Radius="0.3"/>
        <Bone ID="2" ParentID="1" StartX="0" StartY="0" StartZ="4" EndX="0" EndY="0" EndZ="5" Radius="0.6"/>
    </Bones>
</SpeedTreeRaw>"""


def test_pve_preserves_branch_start_radii_and_shared_junction(tmp_path: Path):
    source, output = tmp_path / "tree.xml", tmp_path / "tree.json"
    source.write_text(TREE_XML, encoding="utf-8")
    request = ConversionRequest((str(source),), str(output), conversion_mode=ConversionMode.PVE_GROWTH)
    (result,) = convert_request(request)
    assert [issue.severity for issue in result.diagnostics] == ["info"]
    original = output.read_bytes()
    convert_request(request)
    assert output.read_bytes() == original

    data = json.loads(original)
    positions = data["points"]["positions"]
    radii = [row[0] for row in data["points"]["attributes"]["budLateralMeristem"]["values"]]
    trunk, branch = data["primitives"]["points"]
    junction, connector, start, tip = branch
    assert junction in trunk
    assert positions[junction] == [0, 2, 0]
    assert positions[start] == [1, 2, 0]
    assert positions[tip] == [2, 3, 0]
    assert positions[connector][1] < positions[start][1]
    assert [radii[i] for i in (trunk[0], junction, start, tip)] == [1, 0.75, 0.2, 0.1]
    assert data["primitives"]["attributes"]["branchParentNumber"]["values"] == [0, 1]
    assert all(any(row[-3:]) for row in data["points"]["attributes"]["budDirection"]["values"])


def test_pve_falls_back_whole_tree_and_reports_the_bad_spine(tmp_path: Path):
    source, output = tmp_path / "tree.xml", tmp_path / "tree.json"
    bad_spine = TREE_XML.replace("<Radius>0.2 0.1</Radius>", "<Radius>0.2</Radius>")
    source.write_text(bad_spine, encoding="utf-8")
    request = ConversionRequest((str(source),), str(output), conversion_mode=ConversionMode.PVE_GROWTH)
    (result,) = convert_request(request)
    warning, _ = result.diagnostics
    assert warning.severity == "warning"
    assert "Object 2" in warning.message and "Exported from Bones" in warning.message
    data = json.loads(output.read_bytes())
    radii = data["points"]["attributes"]["budLateralMeristem"]["values"]
    assert radii[0][0] == 0.9
    trunk, branch = data["primitives"]["points"]
    positions = data["points"]["positions"]
    assert branch[0] in trunk
    assert positions[trunk[-1]] == [0, 5, 0]
    assert positions[branch[-1]] == [2, 3, 0]

    original = output.read_bytes()
    source.write_text(bad_spine.replace('Radius="0.9"', 'Radius="-1"'), encoding="utf-8")
    with pytest.raises(ValueError, match="Object 2.*Bones unavailable.*bone 1"):
        convert_request(request)
    assert output.read_bytes() == original
