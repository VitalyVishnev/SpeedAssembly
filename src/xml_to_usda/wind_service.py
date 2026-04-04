"""Application-facing wind inspection and JSON-generation services.

Layer: application.

This module converts UI/CLI wind intents into typed requests and keeps retry and
error-formatting policy out of the Tk layer. The actual wind analysis and JSON
authoring stay in `wind_pipeline`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import DynamicWindSimulationGroup
from .wind_pipeline import generate_wind_json, inspect_wind_data


@dataclass(frozen=True)
class WindInspectionRequest:
    """Typed request for wind-group inspection."""
    input_path: str
    is_ground_cover: bool = False


@dataclass(frozen=True)
class WindInspectionPlan:
    """Wind inspection request plus the chosen execution mode."""
    request: WindInspectionRequest
    run_async: bool


@dataclass(frozen=True)
class WindGenerationRequest:
    """Typed request for Dynamic Wind JSON generation."""
    input_path: str
    output_path: str
    group_settings: tuple[DynamicWindSimulationGroup, ...]
    gust_attenuation: float
    is_ground_cover: bool = False


def prepare_wind_inspection_plan(
    *,
    input_path: str,
    is_ground_cover: bool,
    async_threshold_bytes: int,
) -> WindInspectionPlan:
    """Build one wind-inspection plan from operator-facing inputs."""
    resolved_input_path = input_path.strip()
    return WindInspectionPlan(
        request=WindInspectionRequest(
            input_path=resolved_input_path,
            is_ground_cover=is_ground_cover,
        ),
        run_async=_should_run_wind_inspection_async(
            input_path=resolved_input_path,
            async_threshold_bytes=async_threshold_bytes,
        ),
    )


def inspect_wind_groups(request: WindInspectionRequest):
    return inspect_wind_data(
        request.input_path,
        is_ground_cover=request.is_ground_cover,
    )


def generate_wind_json_from_request(request: WindGenerationRequest):
    return generate_wind_json(
        request.input_path,
        request.output_path,
        group_settings=request.group_settings,
        gust_attenuation=request.gust_attenuation,
        is_ground_cover=request.is_ground_cover,
    )


def derive_wind_json_output_path(input_path: str, output_path: str) -> Path:
    if output_path.strip():
        resolved_output = Path(output_path)
        return resolved_output.with_name(f"{resolved_output.stem}_DynamicWind.json")
    resolved_input = Path(input_path.strip())
    return resolved_input.with_name(f"{resolved_input.stem}_DynamicWind.json")


def should_retry_wind_error(error_type: str, message: str) -> bool:
    return error_type == "SystemError" or "bad argument to internal function" in message or "setobject.c" in message


def format_wind_error(error_payload: dict[str, str]) -> str:
    error_type = error_payload.get("type", "Exception")
    message = error_payload.get("message", "")
    formatted_traceback = error_payload.get("traceback", "").strip()
    lines = [f"{error_type}: {message}"]
    if formatted_traceback:
        lines.extend(["", formatted_traceback])
    return "\n".join(lines).strip()


def _should_run_wind_inspection_async(*, input_path: str, async_threshold_bytes: int) -> bool:
    try:
        return Path(input_path).stat().st_size >= async_threshold_bytes
    except OSError:
        return False
