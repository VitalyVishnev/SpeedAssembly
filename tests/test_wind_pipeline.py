from __future__ import annotations

import pytest

from pathlib import Path

from xml_to_usda.wind_pipeline import generate_wind_json, inspect_wind_data


def _write_generator_level_sample(tmp_path: Path, generator_labels: tuple[str | None, ...]) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    bone_lines: list[str] = ["<SpeedTreeRaw>", "  <Bones>"]
    for bone_id, generator_label in enumerate(generator_labels):
        parent_id = bone_id - 1 if bone_id > 0 else -1
        generator_attribute = f' Generator="{generator_label}"' if generator_label is not None else ""
        bone_lines.append(
            f'    <Bone ID="{bone_id}" ParentID="{parent_id}" StartX="0" StartY="0" StartZ="{bone_id}" '
            f'EndX="0" EndY="0" EndZ="{bone_id + 1}"{generator_attribute} />'
        )
    bone_lines.extend(["  </Bones>", "</SpeedTreeRaw>"])
    sample_path = tmp_path / "wind_generator_levels.xml"
    sample_path.write_text("\n".join(bone_lines), encoding="utf-8")
    return sample_path


def test_wind_pipeline_inspects_generator_level_groups(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )

    dynamic_wind = inspect_wind_data(str(input_path))

    assert len(dynamic_wind.simulation_groups) == 3
    assert [group.branch_order for group in dynamic_wind.simulation_groups] == [0, 1, 2]
    assert dynamic_wind.simulation_groups[0].is_trunk_group is True


def test_wind_pipeline_clears_trunk_groups_for_ground_cover(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(
        tmp_path,
        ("Group_0 2", "Group_0", "Group_1", "Group_1", "Group_2"),
    )

    dynamic_wind = inspect_wind_data(str(input_path), is_ground_cover=True)

    assert dynamic_wind.is_ground_cover is True
    assert dynamic_wind.simulation_groups
    assert all(group.is_trunk_group is False for group in dynamic_wind.simulation_groups)


def test_wind_pipeline_rejects_missing_generator_levels(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, (None, None))

    with pytest.raises(ValueError, match="missing_generator_level"):
        inspect_wind_data(str(input_path))


def test_wind_pipeline_rejects_malformed_generator_levels_for_json_generation(tmp_path: Path) -> None:
    input_path = _write_generator_level_sample(tmp_path, ("Branches", "Branches"))

    with pytest.raises(ValueError, match="missing_generator_level"):
        generate_wind_json(str(input_path), str(tmp_path / "invalid_DynamicWind.json"))
