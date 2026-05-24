"""UDIM settings loading for CLI and preset adapters."""

from __future__ import annotations

import json
from pathlib import Path

from .models import UdimMaterialSetting, UdimMode


def load_udim_material_settings_from_json(path: str | Path) -> tuple[UdimMaterialSetting, ...]:
    config_path = Path(path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("UDIM settings JSON must be an array of setting objects.")

    settings: list[UdimMaterialSetting] = []
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise ValueError(f"UDIM settings row {index} must be an object.")
        try:
            material_id = int(record["material_id"])
            mode = UdimMode.parse(record.get("mode"))
            udim_id = int(record.get("udim_id", 1001))
        except KeyError as exc:
            raise ValueError(f"UDIM settings row {index} is missing {exc.args[0]!r}.") from exc
        except (TypeError, ValueError) as exc:
            raise ValueError(f"UDIM settings row {index} has an invalid material_id, mode, or udim_id.") from exc
        settings.append(
            UdimMaterialSetting(
                material_id=material_id,
                mode=mode,
                udim_id=udim_id,
            )
        )
    return tuple(settings)
