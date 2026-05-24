"""Public facade for conversion and inspection entry points.

Layer: application facade.

External callers, older tests, CLI glue, and subprocess workers may continue
to import from this module. Real implementation now lives in focused internal
modules; this facade should not grow new business logic.
"""

from __future__ import annotations

from .canonical_loader import (
    _apply_material_policy,
    load_canonical_model,
    load_resolved_assembly_model,
    load_source_tree_model,
    resolve_assembly_model,
)
from .conversion_orchestrator import convert_file, convert_request
from .output_resolution import REPO_ROOT, VAULT_ROOT
from .source_analysis import discover_part_prototypes, discover_source_materials, inspect_source
from .wind_pipeline import generate_wind_json, inspect_wind_data

__all__ = [
    "REPO_ROOT",
    "VAULT_ROOT",
    "inspect_source",
    "discover_part_prototypes",
    "discover_source_materials",
    "load_canonical_model",
    "load_source_tree_model",
    "resolve_assembly_model",
    "load_resolved_assembly_model",
    "convert_file",
    "convert_request",
    "inspect_wind_data",
    "generate_wind_json",
    "_apply_material_policy",
]
