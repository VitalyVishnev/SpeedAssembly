"""Source opening facts; native projections and canonical recovery stay private.

Discovery consumes facts, while explicit Wind refresh requests authored joints.
Both views share reader selection without exposing partial XML to their callers.
"""
from __future__ import annotations

from dataclasses import dataclass
import importlib
import logging
import sys
import xml.etree.ElementTree as ET

from .dynamic_wind import build_dynamic_wind_data
from .models import BaseMaterialOverride, DynamicWindData, Joint, PrototypeDiscoveryEntry, SourceXmlDocument
from .normalizer import normalize_to_canonical
from .source_extraction import (
    SourceStructure, count_source_part_instances, extract_authored_wind_joints,
    normalize_source_skeleton, validate_source_part_hosts,
)
from .scattered_parts import ScatteredPartsAnalysis, analyze_scattered_parts
from .skeleton_processing import strictly_vertical_joint_names
from .source_analysis import discover_missing_bone_generator_groups, discover_part_prototypes, discover_source_materials
from .source_limits import DEFAULT_SOURCE_LIMITS, SourceLimits
from .source_transform import build_source_transform
from .xml_reader import analyze_xml, iterparse_source_xml, read_source_xml


@dataclass(frozen=True)
class SourceOpeningFacts:
    materials: tuple[BaseMaterialOverride, ...]
    prototypes: tuple[PrototypeDiscoveryEntry, ...]
    missing_bone_generator_groups: tuple[str, ...]
    scattered_parts: ScatteredPartsAnalysis
    strictly_vertical_joints: tuple[str, ...]
    skeleton_joint_count: int
    wind_data: DynamicWindData | None


def inspect_source_opening(input_path: str, *, is_ground_cover: bool = False) -> SourceOpeningFacts:
    """Inspect the facts needed at opening, without settings or full-model caching."""
    opening = _read_native_opening(input_path)
    document = opening.document if opening is not None else read_source_xml(input_path)
    analysis = analyze_xml(document)
    source_transform = build_source_transform(
        document.tree.getroot(), analysis.report.units_hint,
        analysis.report.up_axis_hint, analysis.source_nodes.meshes,
    )
    skeleton = normalize_source_skeleton(analysis.source_nodes.bones, source_transform)
    if not skeleton and opening is not None and opening.projected:
        # An unusable rest pose cannot establish the skeletal exclusion. Full
        # geometry must be available before canonical Scattered Parts analysis.
        opening = _read_native_opening(input_path, projection=False)
        document = opening.document if opening is not None else read_source_xml(input_path)
        analysis = analyze_xml(document)
    if skeleton:
        if opening is not None and opening.instance_count is not None:
            validate_source_part_hosts(analysis.source_nodes.objects, source_transform)
            instance_count = opening.instance_count
        else:
            instance_count = count_source_part_instances(analysis.source_nodes.objects, source_transform)
        scattered_parts = ScatteredPartsAnalysis(False, False, instance_count, reason="skeleton is present")
    else:
        source_model = normalize_to_canonical(document, analysis.report, source_nodes=analysis.source_nodes)
        scattered_parts = analyze_scattered_parts(source_model)
    wind_data = None
    if opening is not None:
        wind_skeleton = extract_authored_wind_joints(analysis.source_nodes.bones)
        if wind_skeleton:
            try:
                wind_data = build_dynamic_wind_data(wind_skeleton, is_ground_cover=is_ground_cover)
            except ValueError:
                # Source rows survive invalid Generator metadata. Explicit Wind
                # inspection retains ownership of reporting its domain error.
                pass
    if opening is not None and opening.materials is not None and opening.prototypes is not None:
        materials, prototypes = opening.materials, opening.prototypes
    else:
        materials = discover_source_materials(input_path, document=document)
        prototypes = discover_part_prototypes(input_path, document=document)
    return SourceOpeningFacts(
        materials, prototypes, discover_missing_bone_generator_groups(input_path, document=document),
        scattered_parts, strictly_vertical_joint_names(skeleton), len(skeleton), wind_data,
    )


def read_source_structure(input_path: str) -> SourceStructure:
    """Read structural facts once without changing native opening projections."""
    document = read_source_xml(input_path)
    analysis = analyze_xml(document)
    transform = build_source_transform(
        document.tree.getroot(), analysis.report.units_hint,
        analysis.report.up_axis_hint, analysis.source_nodes.meshes,
    )
    return SourceStructure(analysis.source_nodes, transform)


def read_authored_wind_skeleton(input_path: str) -> tuple[Joint, ...]:
    """Reread authored Wind identities; synthetic rig resolution belongs to Wind."""
    opening = _read_native_opening(input_path)
    elements = (opening.document.tree.iter('Bone') if opening is not None else
                (elem for _event, elem in iterparse_source_xml(input_path, events=("end",)) if elem.tag == 'Bone'))
    return extract_authored_wind_joints(elements)


@dataclass(frozen=True)
class _NativeOpening:
    document: SourceXmlDocument
    projected: bool
    materials: tuple[BaseMaterialOverride, ...] | None = None
    prototypes: tuple[PrototypeDiscoveryEntry, ...] | None = None
    instance_count: int | None = None


def _read_native_opening(
    input_path: str, *, projection: bool = True,
    limits: SourceLimits = DEFAULT_SOURCE_LIMITS,
) -> _NativeOpening | None:
    # Keep native loading at the actual XML action, including in frozen workers.
    try:
        native = importlib.import_module('xml_to_usda._xml_reader')
    except ModuleNotFoundError as exc:
        if exc.name != 'xml_to_usda._xml_reader':
            raise
        if getattr(sys, 'frozen', False):
            raise RuntimeError('Packaged Rust XML reader is missing; rebuild the application.') from exc
        return None
    if getattr(native, 'API_VERSION', None) != 1:
        raise RuntimeError('Rust XML reader API mismatch; rebuild the native module.')
    payload = native.read_opening(str(input_path), (
        limits.max_xml_bytes, limits.max_xml_depth, limits.max_packed_field_values,
        limits.max_total_packed_values, limits.max_repeated_part_instances,
        limits.max_mesh_face_vertex_entries,
    ), projection)
    if payload is None:
        logging.getLogger(__name__).debug('Using canonical XML reader for source encoding/structure: %s', input_path)
        return None
    xml, projected, facts = payload
    root = ET.fromstring(xml)
    materials = prototypes = count = None
    if facts is not None:
        raw_materials, raw_prototypes, count = facts
        materials = tuple(BaseMaterialOverride(source_id, name) for source_id, name in raw_materials)
        prototypes = tuple(PrototypeDiscoveryEntry(
            f'Mesh_{source_id}' if source_id is not None else 'LeafPrototype', source_id, name, instances,
        ) for source_id, name, instances in raw_prototypes)
    return _NativeOpening(
        SourceXmlDocument(str(input_path), root.tag, ET.ElementTree(root)),
        projected, materials, prototypes, count,
    )
