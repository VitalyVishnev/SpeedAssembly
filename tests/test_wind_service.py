from __future__ import annotations

from pathlib import Path

from xml_to_usda.models import DynamicWindData, DynamicWindJointAssignment, DynamicWindSimulationGroup, WindJsonResult
from xml_to_usda.wind_service import (
    WindGenerationRequest,
    WindInspectionRequest,
    derive_wind_json_output_path,
    format_wind_error,
    generate_wind_json_from_request,
    inspect_wind_groups,
    prepare_wind_inspection_plan,
    should_retry_wind_error,
)


def test_prepare_wind_inspection_plan_uses_threshold(tmp_path: Path) -> None:
    input_path = tmp_path / "tree.xml"
    input_path.write_text("<Tree />", encoding="utf-8")

    sync_plan = prepare_wind_inspection_plan(
        input_path=str(input_path),
        is_ground_cover=False,
        async_threshold_bytes=1_000_000,
    )
    async_plan = prepare_wind_inspection_plan(
        input_path=str(input_path),
        is_ground_cover=True,
        async_threshold_bytes=0,
    )

    assert sync_plan.run_async is False
    assert async_plan.run_async is True
    assert async_plan.request.is_ground_cover is True


def test_wind_service_formats_errors_and_retry_policy() -> None:
    error_payload = {
        "type": "SystemError",
        "message": r"D:\w1\s\Objects\setobject.c:2295: bad argument to internal function",
        "traceback": "Traceback line 1",
    }

    assert should_retry_wind_error(error_payload["type"], error_payload["message"]) is True
    assert "SystemError:" in format_wind_error(error_payload)
    assert "Traceback line 1" in format_wind_error(error_payload)


def test_derive_wind_json_output_path_prefers_output_usda_stem() -> None:
    assert str(derive_wind_json_output_path("tree.xml", "out.usda")) == "out_DynamicWind.json"
    assert str(derive_wind_json_output_path("tree.xml", "")) == "tree_DynamicWind.json"


def test_inspect_wind_groups_wraps_pipeline(monkeypatch) -> None:
    expected = DynamicWindData(
        joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
        simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
    )

    monkeypatch.setattr("xml_to_usda.wind_service.inspect_wind_data", lambda input_path, is_ground_cover=False: expected)

    result = inspect_wind_groups(WindInspectionRequest(input_path="tree.xml", is_ground_cover=True))

    assert result == expected


def test_generate_wind_json_from_request_wraps_pipeline(monkeypatch) -> None:
    expected = WindJsonResult(
        input_path="tree.xml",
        output_path="tree_DynamicWind.json",
        dynamic_wind=DynamicWindData(
            joint_assignments=(DynamicWindJointAssignment(joint_name="root", simulation_group_index=0, branch_order=0),),
            simulation_groups=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
        ),
    )

    monkeypatch.setattr(
        "xml_to_usda.wind_service.generate_wind_json",
        lambda input_path, output_path, group_settings=(), gust_attenuation=0.0, is_ground_cover=False: expected,
    )

    result = generate_wind_json_from_request(
        WindGenerationRequest(
            input_path="tree.xml",
            output_path="tree_DynamicWind.json",
            group_settings=(DynamicWindSimulationGroup(group_index=0, branch_order=0, is_trunk_group=True),),
            gust_attenuation=0.5,
            is_ground_cover=False,
        )
    )

    assert result == expected
