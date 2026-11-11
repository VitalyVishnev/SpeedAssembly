"""Dynamic Wind profile values and the UE 5.9 group authoring contract."""

from dataclasses import dataclass, fields
import math

LEGACY = "legacy"
FORCE_BASED = "force_based"


def wind_profile(value: str) -> str:
    if value not in (LEGACY, FORCE_BASED):
        raise ValueError(f"Unknown Dynamic Wind profile: {value!r}")
    return value


@dataclass(frozen=True, slots=True)
class ForceWindSettings:
    is_trunk_group: bool = False
    wind_response_scale: float = 1.0
    base_frequency_scale: float | None = None
    tip_frequency_scale: float | None = None
    modal_frequency_scale: float | None = None
    flutter_frequency_scale: float | None = None
    tip_falloff_power: float | None = None
    base_settling_time_scale: float | None = None
    tip_settling_time_scale: float | None = None
    base_max_bend_angle: float | None = None
    tip_max_bend_angle: float | None = None
    length_frequency_variation: float | None = None
    stiffness_compensation_scale: float | None = None


# Names and limits: UE 5.9 DynamicWindSkeletalData.h and DynamicWindUSDImport.cpp.
# One table keeps the two editors and both export formats on the same contract.
FORCE_PARAMETERS = (
    ("wind_response_scale", "Wind Response", 0.0, 4.0, 1.0, "Scales aerodynamic response. Does not scale direct capsule pushes."),
    ("base_frequency_scale", "Base Frequency Scale", 0.1, 10.0, 1.0, "Scales the base frequency model. With physical modal frequencies it affects amplitude compensation."),
    ("tip_frequency_scale", "Tip Frequency Scale", 0.1, 10.0, 1.0, "Scales the tip frequency model. With physical modal frequencies it affects amplitude compensation."),
    ("modal_frequency_scale", "Modal Frequency Scale", 0.1, 10.0, 1.0, "Scales baked physical frequency before Unreal remaps it. Requires usable structural radii."),
    ("flutter_frequency_scale", "Flutter Frequency Scale", 0.0, 12.0, 1.0, "Sets flutter frequency as a multiple of each bone's natural frequency."),
    ("tip_falloff_power", "Tip Falloff Power", 0.1, 5.0, 1.0, "Shapes the base-to-tip parameter ramp. 1 is linear; higher reaches tip values earlier."),
    ("base_settling_time_scale", "Base Settling Time Scale", 0.1, 10.0, 1.0, "Scales base settling time in the fallback model. Unreal replaces this with physical damping when valid modal data is available."),
    ("tip_settling_time_scale", "Tip Settling Time Scale", 0.1, 10.0, 1.0, "Scales tip settling time in the fallback model. Unreal replaces this with physical damping when valid modal data is available."),
    ("base_max_bend_angle", "Base Max Bend Angle (degrees)", 0.0, 360.0, 90.0, "Whole-chain bend budget at the base, in degrees. 0 is rigid."),
    ("tip_max_bend_angle", "Tip Max Bend Angle (degrees)", 0.0, 360.0, 90.0, "Whole-chain bend budget at the tip, in degrees. Higher permits greater bending."),
    ("length_frequency_variation", "Length Frequency Variation", 0.0, 3.0, 0.5, "Fallback frequency exponent. 0 removes length variation; higher makes short structures faster."),
    ("stiffness_compensation_scale", "Stiffness Compensation Scale", 0.0, 2.0, 1.0, "Scales amplitude compensation. Lower reduces swing; higher increases it without changing physical frequency."),
)


def unreal_parameter_name(name: str) -> str:
    return "".join(part.title() for part in name.split("_"))


def parse_force_settings(payload) -> ForceWindSettings:
    if payload is None:
        return ForceWindSettings()
    if not isinstance(payload, dict):
        raise ValueError("Force Based settings must be an object.")
    result = ForceWindSettings(**{f.name: payload[f.name] for f in fields(ForceWindSettings) if f.name in payload})
    validate_force_settings(result)
    return result


def validate_force_settings(settings: ForceWindSettings) -> None:
    if not isinstance(settings.is_trunk_group, bool):
        raise ValueError("Force Based is_trunk_group must be a boolean.")
    for name, _label, minimum, maximum, _default, _help in FORCE_PARAMETERS:
        value = getattr(settings, name)
        if value is None and name != "wind_response_scale":
            continue
        if (
            not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < minimum
            or (name != "wind_response_scale" and value > maximum)
        ):
            raise ValueError(f"Invalid Force Based {name}: {value!r}")


def force_group_payload(settings: ForceWindSettings) -> dict:
    validate_force_settings(settings)
    result = {"bIsTrunkGroup": settings.is_trunk_group, "WindResponseScale": settings.wind_response_scale}
    for name, *_ in FORCE_PARAMETERS[1:]:
        value = getattr(settings, name)
        ue_name = unreal_parameter_name(name)
        result["bOverride" + ue_name] = value is not None
        if value is not None:
            result[ue_name] = value
    return result
