"""Shared USDA authoring engine used by both text and streaming export paths.

Layer: infrastructure.

This module owns exporter semantics and prim/block emitters. Callers should use
`usda_writer` for public entrypoints rather than depending on these internals
directly.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .job_control import emit_telemetry, throw_if_cancelled
from .models import (
    AssemblyPartInstance,
    CanonicalTreeModel,
    CompactMeshSection,
    ConversionPhase,
    ConversionMode,
    GeometryBuffer,
    InstanceBinding,
    MaterialSpec,
    MeshData,
    MeshSection,
    Prototype,
    PrototypeIdentity,
    PrototypeResolutionMode,
    PrototypeSourceMode,
    PrototypeStrategy,
    Quaternion,
    ResolvedAssemblyModel,
    SkeletalSupportPrimvars,
    ValidationIssue,
    Vector3,
)
from .naming import make_stable_prim_name
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


@dataclass(frozen=True)
class AuthoringContext:
    """Resolved authoring state shared by both text and streaming sinks."""
    model: CanonicalTreeModel
    diagnostics: tuple[ValidationIssue, ...]
    contract: UeSchemaContract
    conversion_mode: ConversionMode
    base_mesh_name: str | None
    resolved_base_mesh_name: str
    resolved_base_skel_root_name: str
    resolved_skeleton_name: str
    resolved_base_animation_name: str
    resolved_base_joint_root_name: str | None


class TextSink:
    def __init__(self) -> None:
        self._parts: list[str] = []

    def write(self, text: str) -> None:
        self._parts.append(text)

    def value(self) -> str:
        return "".join(self._parts)


class HandleSink:
    def __init__(self, handle) -> None:
        self._handle = handle

    def write(self, text: str) -> None:
        self._handle.write(text)


def build_authoring_context(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    *,
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
    conversion_mode: ConversionMode | str | None = None,
) -> AuthoringContext:
    error_codes = [issue.code for issue in diagnostics if issue.severity == "error"]
    if error_codes:
        raise ValueError(
            "Cannot author USDA while validation errors are present: " + ", ".join(sorted(dict.fromkeys(error_codes)))
        )

    resolved_conversion_mode = ConversionMode.parse(conversion_mode or model.metadata.conversion_mode)
    if resolved_conversion_mode == ConversionMode.STATIC_PARTS:
        raise ValueError(f"Unsupported conversion mode: {resolved_conversion_mode.value}.")
    if resolved_conversion_mode not in {
        ConversionMode.SKELETAL_ASSEMBLY,
        ConversionMode.SKELETAL_PARTS,
        ConversionMode.STATIC_ASSEMBLY,
    }:
        raise ValueError(f"Unsupported conversion mode: {resolved_conversion_mode.value}.")

    resolved_root_prim_name = contract.root_prim_name
    if resolved_conversion_mode == ConversionMode.STATIC_ASSEMBLY:
        resolved_root_prim_name = make_stable_prim_name(
            base_mesh_name or Path(model.metadata.source_path).stem or contract.root_prim_name,
            fallback=contract.root_prim_name,
        )
        contract = contract.for_conversion_mode(
            resolved_conversion_mode,
            root_prim_name=resolved_root_prim_name,
        )

    resolved_base_mesh_name = make_stable_prim_name(
        base_mesh_name or contract.base_mesh_name,
        fallback=contract.base_mesh_name,
    )
    resolved_base_skel_root_name = (
        make_stable_prim_name(
            f"{resolved_base_mesh_name}_Geo",
            fallback=contract.base_skel_root_name,
        )
        if base_mesh_name
        else contract.base_skel_root_name
    )
    resolved_skeleton_name = (
        make_stable_prim_name(
            f"{resolved_base_mesh_name}_Skeleton",
            fallback=contract.skeleton_name,
        )
        if base_mesh_name
        else contract.skeleton_name
    )
    resolved_base_animation_name = "animation" if base_mesh_name else contract.base_animation_name
    resolved_base_joint_root_name = (
        _resolved_root_joint_alias(model, resolved_base_mesh_name)
        if base_mesh_name
        else None
    )
    return AuthoringContext(
        model=model,
        diagnostics=diagnostics,
        contract=contract,
        conversion_mode=resolved_conversion_mode,
        base_mesh_name=base_mesh_name,
        resolved_base_mesh_name=resolved_base_mesh_name,
        resolved_base_skel_root_name=resolved_base_skel_root_name,
        resolved_skeleton_name=resolved_skeleton_name,
        resolved_base_animation_name=resolved_base_animation_name,
        resolved_base_joint_root_name=resolved_base_joint_root_name,
    )


def build_resolved_authoring_context(
    resolved: ResolvedAssemblyModel,
    *,
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
    base_mesh_name: str | None = None,
) -> AuthoringContext:
    """Build authoring context from the preferred Resolved Assembly Model seam."""
    return build_authoring_context(
        resolved.authoring_model,
        resolved.diagnostics,
        contract=contract,
        base_mesh_name=base_mesh_name if base_mesh_name is not None else resolved.output_stem,
        conversion_mode=resolved.conversion_mode,
    )


def author_usda_text(context: AuthoringContext) -> str:
    sink = TextSink()
    author_usda(sink, context)
    return sink.value()


def author_usda_stream(
    handle,
    context: AuthoringContext,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    author_usda(
        HandleSink(handle),
        context,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )


def author_usda(
    sink,
    context: AuthoringContext,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    contract = context.contract
    model = context.model
    stage_root_name = _stage_root_name(context)

    if context.conversion_mode == ConversionMode.STATIC_ASSEMBLY:
        _emit_static_assembly_document(
            sink,
            context,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
        return

    _write_line(sink, 0, "#usda 1.0")
    _write_line(sink, 0, "(")
    _write_line(sink, 1, f"metersPerUnit = {contract.stage_meters_per_unit:g}")
    _write_line(sink, 1, f'upAxis = "{contract.stage_up_axis}"')
    _write_line(sink, 1, f'defaultPrim = "{stage_root_name}"')
    _write_line(sink, 0, ")")
    _write_line(sink, 0)
    if context.conversion_mode == ConversionMode.SKELETAL_PARTS:
        if _is_single_prototype_parts_document(context):
            _emit_single_prototype_parts_document(sink, context)
            return
        single_prototype_name = _single_parts_asset_name(context)
        if single_prototype_name:
            _write_line(sink, 1, f'def Xform "{stage_root_name}" (')
            _emit_asset_info_name_metadata(sink, 2, single_prototype_name)
            _write_line(sink, 1, ")")
        else:
            _write_line(sink, 1, f'def Xform "{stage_root_name}"')
        _write_line(sink, 0, "{")

        materials = _render_materials_scope(model.materials, stage_root_name)
        if materials:
            _write_block(sink, materials, 1)
            _write_line(sink, 0)

        _emit_parts_only_prototype_scope(
            sink,
            context,
            1,
            telemetry_callback=telemetry_callback,
            cancel_event=cancel_event,
            started_at=started_at,
        )
        _write_line(sink, 0, "}")
        return

    _write_line(sink, 1, f'def Xform "{contract.root_prim_name}" (')
    _write_line(sink, 2, f'prepend apiSchemas = ["{contract.root_api}"]')
    _write_line(sink, 2, f'kind = "{contract.root_kind}"')
    _write_line(sink, 0, ")")
    _write_line(sink, 0, "{")
    _write_line(sink, 1, f'uniform token {contract.mesh_type_attr} = "{contract.mesh_type_value}"')
    _write_line(
        sink,
        1,
        f'{("custom rel" if context.base_mesh_name else "rel")} unreal:naniteAssembly:skeleton = '
        f'</{contract.root_prim_name}/{context.resolved_base_skel_root_name}/{context.resolved_skeleton_name}>',
    )
    _write_line(sink, 0)

    materials = _render_materials_scope(model.materials, contract.root_prim_name)
    if materials:
        _write_block(sink, materials, 1)
        _write_line(sink, 0)

    if model.prototype_strategy == PrototypeStrategy.REFERENCED_SCOPE:
        _emit_prototype_library(sink, context, 1)
        _write_line(sink, 0)

    _write_line(sink, 1, f'def SkelRoot "{context.resolved_base_skel_root_name}" (')
    _write_line(sink, 2, 'kind = "component"')
    _write_line(sink, 1, ")")
    _write_line(sink, 1, "{")
    skelroot_support = _render_skelroot_support_primvars(model.skeletal_support_primvars)
    if skelroot_support:
        _write_block(sink, skelroot_support, 2)
    _write_line(sink, 2, f"matrix4d xformOp:transform = {_identity_matrix()}")
    _write_line(sink, 2, 'uniform token[] xformOpOrder = ["xformOp:transform"]')
    _write_line(sink, 0)
    _write_block(
        sink,
        _render_base_animation(
            model,
            context.resolved_base_animation_name,
            context.resolved_base_joint_root_name,
        ),
        2,
    )
    _write_line(sink, 0)
    _emit_base_mesh(sink, context, 2)
    _write_line(sink, 0)
    _write_block(
        sink,
        _render_main_skeleton(
            model,
            contract,
            context.resolved_base_skel_root_name,
            context.resolved_base_animation_name,
            context.resolved_skeleton_name,
            context.resolved_base_joint_root_name,
        ),
        2,
    )
    _write_line(sink, 1, "}")
    _write_line(sink, 0)
    _emit_point_instancer(
        sink,
        context,
        1,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )
    _write_line(sink, 0, "}")


def model_requires_streaming_writer(model: CanonicalTreeModel) -> bool:
    if any(prototype.geometry_payload is not None for prototype in model.prototypes):
        return True
    if len(model.assembly_parts) >= 10000:
        return True
    base_mesh = model.base_mesh
    if base_mesh is not None:
        if len(base_mesh.points) >= 100000:
            return True
        if len(base_mesh.face_vertex_indices) >= 300000:
            return True
    return False


def _emit_prototype_library(sink, context: AuthoringContext, indent_level: int) -> None:
    if not context.model.prototypes:
        return
    _write_line(sink, indent_level, 'def Xform "PrototypeLibrary"')
    _write_line(sink, indent_level, "{")
    for prototype in context.model.prototypes:
        _emit_library_prototype(sink, prototype, context.contract, indent_level + 1)
    _write_line(sink, indent_level, "}")


def _emit_static_assembly_document(
    sink,
    context: AuthoringContext,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    contract = context.contract
    model = context.model
    prototypes = _static_assembly_prototypes(context)
    instances = _static_assembly_instances(context, prototypes)

    _write_line(sink, 0, "#usda 1.0")
    _write_line(sink, 0, "(")
    _write_line(sink, 1, f"metersPerUnit = {contract.stage_meters_per_unit:g}")
    _write_line(sink, 1, f'upAxis = "{contract.stage_up_axis}"')
    _write_line(sink, 0, ")")
    _write_line(sink, 0)
    _write_line(sink, 0, f'def Xform "{contract.root_prim_name}" (')
    _write_line(sink, 1, f'apiSchemas = ["{contract.root_api}"]')
    _write_line(sink, 1, f'kind = "{contract.root_kind}"')
    _write_line(sink, 0, ")")
    _write_line(sink, 0, "{")
    _write_line(sink, 1, f'uniform token {contract.mesh_type_attr} = "{contract.mesh_type_value}"')
    _write_line(sink, 0)

    materials = _render_materials_scope(model.materials, contract.root_prim_name)
    if materials:
        _write_block(sink, materials, 1)
        _write_line(sink, 0)

    _emit_static_point_instancer(
        sink,
        context,
        1,
        prototypes=prototypes,
        instances=instances,
        telemetry_callback=telemetry_callback,
        cancel_event=cancel_event,
        started_at=started_at,
    )
    _write_line(sink, 0, "}")


def _emit_library_prototype(sink, prototype: Prototype, contract: UeSchemaContract, indent_level: int) -> None:
    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    part_mesh_name = _static_mesh_prim_name(prototype, contract)
    _write_line(sink, indent_level, f'def Xform "{prototype.identity.prim_name}" (')
    _write_line(sink, indent_level + 1, 'kind = "component"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, 'token visibility = "invisible"')
    _write_line(sink, indent_level + 1, f'def Mesh "{part_mesh_name}"')
    _write_line(sink, indent_level + 1, "{")
    _write_line(sink, indent_level + 2, 'uniform token subdivisionScheme = "none"')
    _emit_material_binding(sink, mesh, indent_level + 2, context.contract.root_prim_name)
    _emit_mesh_payload(sink, mesh, contract.mesh_orientation, indent_level + 2)
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _static_assembly_prototypes(context: AuthoringContext) -> tuple[Prototype, ...]:
    prototypes: list[Prototype] = []
    if context.model.base_mesh is not None:
        prototypes.append(_make_static_base_prototype(context))
    prototypes.extend(context.model.prototypes)
    return tuple(prototypes)


def _static_assembly_instances(
    context: AuthoringContext,
    prototypes: tuple[Prototype, ...],
) -> tuple[AssemblyPartInstance, ...]:
    instances: list[AssemblyPartInstance] = []
    if context.model.base_mesh is not None and prototypes:
        instances.append(_make_static_base_instance(context, prototypes[0].identity.source_key))
    instances.extend(context.model.assembly_parts)
    return tuple(instances)


def _make_static_base_prototype(context: AuthoringContext) -> Prototype:
    root_name = context.contract.root_prim_name
    base_name = make_stable_prim_name(f"{root_name}_BaseMesh", fallback="BaseMesh")
    return Prototype(
        identity=PrototypeIdentity(
            source_key="__static_base_mesh__",
            prim_name=base_name,
            prototype_type="static_base_mesh",
        ),
        mesh=context.model.base_mesh,
        source_key="__static_base_mesh__",
        source_mesh_id=None,
        source_name=root_name,
        prototype_type="static_base_mesh",
        resolution_mode=PrototypeResolutionMode.INLINE_MESH,
        source_mode=PrototypeSourceMode.XML_MESH,
        geometry_payload=None,
    )


def _make_static_base_instance(context: AuthoringContext, prototype_key: str) -> AssemblyPartInstance:
    return AssemblyPartInstance(
        name=context.contract.root_prim_name,
        prototype_key=prototype_key,
        position=Vector3(0.0, 0.0, 0.0),
        orientation=Quaternion(1.0, 0.0, 0.0, 0.0),
        scale=Vector3(1.0, 1.0, 1.0),
        binding=InstanceBinding(joint_tokens=(), weights=()),
        source_object_id=None,
        source_mesh_id=None,
    )


def _emit_static_point_instancer(
    sink,
    context: AuthoringContext,
    indent_level: int,
    *,
    prototypes: tuple[Prototype, ...],
    instances: tuple[AssemblyPartInstance, ...],
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    if not instances:
        return

    contract = context.contract
    prototype_index_map = {prototype.identity.source_key: index for index, prototype in enumerate(prototypes)}
    prototype_paths = ", ".join(contract.prototype_root_path(prototype.identity.prim_name) for prototype in prototypes)
    include_orientations = any(not _is_identity_quaternion(instance.orientation) for instance in instances)
    include_scales = any(not _is_unit_scale(instance.scale) for instance in instances)

    _write_line(sink, indent_level, f'def PointInstancer "{contract.assembly_parts_instancer_name}" (')
    _write_line(sink, indent_level + 1, 'kind = "group"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, f"rel prototypes = [{prototype_paths}]")
    _write_array_attribute(
        sink,
        indent_level + 1,
        "int[] protoIndices",
        (
            str(_static_prototype_index(instance.prototype_key, prototype_index_map, instance.name))
            for instance in instances
        ),
    )
    _write_array_attribute(
        sink,
        indent_level + 1,
        "point3f[] positions",
        (instance.position.to_usda() for instance in instances),
    )
    if include_orientations:
        _write_array_attribute(
            sink,
            indent_level + 1,
            "quath[] orientations",
            (instance.orientation.to_usda() for instance in instances),
        )
    if include_scales:
        _write_array_attribute(
            sink,
            indent_level + 1,
            "float3[] scales",
            (instance.scale.to_usda() for instance in instances),
        )
    _write_line(sink, 0)
    _write_line(sink, indent_level + 1, f'def Scope "{contract.prototype_scope_name}" (')
    _write_line(sink, indent_level + 2, 'kind = "group"')
    _write_line(sink, indent_level + 1, ")")
    _write_line(sink, indent_level + 1, "{")
    for index, prototype in enumerate(prototypes, start=1):
        throw_if_cancelled(cancel_event)
        _emit_static_instancer_prototype(sink, prototype, context, indent_level + 2)
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.USDA_WRITING,
            completed_units=index,
            total_units=len(prototypes),
            message=f"Writing prototype {prototype.identity.prim_name}.",
            started_at=started_at,
        )
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _emit_static_instancer_prototype(
    sink,
    prototype: Prototype,
    context: AuthoringContext,
    indent_level: int,
) -> None:
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        _write_block(sink, _render_external_instancer_prototype(prototype, context.contract), indent_level)
        return

    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    part_mesh_name = _static_mesh_prim_name(prototype, context.contract)
    _write_line(sink, indent_level, f'def Xform "{prototype.identity.prim_name}" (')
    _write_line(sink, indent_level + 1, 'kind = "component"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, f'def Mesh "{part_mesh_name}"')
    _write_line(sink, indent_level + 1, "{")
    _write_line(sink, indent_level + 2, 'uniform token subdivisionScheme = "none"')
    _emit_material_binding(sink, mesh, indent_level + 2, context.contract.root_prim_name)
    _emit_mesh_payload(sink, mesh, context.contract.mesh_orientation, indent_level + 2)
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _static_prototype_index(prototype_key: str, prototype_index_map: dict[str, int], instance_name: str) -> int:
    try:
        return prototype_index_map[prototype_key]
    except KeyError as exc:
        raise ValueError(f"Instance {instance_name} references missing prototype {prototype_key}.") from exc


def _static_mesh_prim_name(prototype: Prototype, contract: UeSchemaContract) -> str:
    raw_name = prototype.identity.prim_name
    if not raw_name.startswith("SM_"):
        raw_name = f"SM_{raw_name}"
    return make_stable_prim_name(raw_name, fallback=f"SM_{contract.part_mesh_name}")


def _is_identity_quaternion(value: Quaternion) -> bool:
    return value.real == 1.0 and value.i == 0.0 and value.j == 0.0 and value.k == 0.0


def _is_unit_scale(value: Vector3) -> bool:
    return value.x == 1.0 and value.y == 1.0 and value.z == 1.0


def _emit_base_mesh(sink, context: AuthoringContext, indent_level: int) -> None:
    model = context.model
    contract = context.contract
    if model.base_mesh is None:
        raise ValueError("Base skeletal tree mesh is required before USDA authoring.")

    mesh = model.base_mesh
    joint_paths = _render_joint_paths(model, root_joint_name=context.resolved_base_joint_root_name)
    _write_line(sink, indent_level, f'def Mesh "{context.resolved_base_mesh_name}" (')
    _write_line(sink, indent_level + 1, f'prepend apiSchemas = ["{contract.skel_binding_api}"]')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, f'uniform token[] skel:joints = [{joint_paths}]')
    _write_line(sink, indent_level + 1, f"uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}")
    _write_line(
        sink,
        indent_level + 1,
        f"append rel skel:skeleton = </{context.contract.root_prim_name}/{context.resolved_base_skel_root_name}/"
        f"{context.resolved_skeleton_name}>",
    )
    _write_line(sink, indent_level + 1, 'uniform token subdivisionScheme = "none"')
    _emit_material_binding(sink, mesh, indent_level + 1, context.contract.root_prim_name)
    _emit_mesh_payload(sink, mesh, contract.mesh_orientation, indent_level + 1)
    if mesh.skel_joint_indices and mesh.skel_joint_weights:
        element_size = mesh.skel_element_size or 1
        _write_array_attribute(
            sink,
            indent_level + 1,
            "uniform int[] primvars:skel:jointIndices",
            (str(index) for index in mesh.skel_joint_indices),
            metadata_lines=(
                f"elementSize = {element_size}",
                'interpolation = "vertex"',
            ),
        )
        _write_array_attribute(
            sink,
            indent_level + 1,
            "uniform float[] primvars:skel:jointWeights",
            (f"{weight:g}" for weight in mesh.skel_joint_weights),
            metadata_lines=(
                f"elementSize = {element_size}",
                'interpolation = "vertex"',
            ),
        )
        _write_line(
            sink,
            indent_level + 1,
            f'{contract.skinning_method_attr} = "{contract.skinning_method_value}"',
        )
    _write_line(sink, indent_level, "}")


def _emit_point_instancer(
    sink,
    context: AuthoringContext,
    indent_level: int,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    assembly_parts = context.model.assembly_parts
    if not assembly_parts:
        return

    contract = context.contract
    prototypes = context.model.prototypes
    prototype_index_map = {prototype.source_key: index for index, prototype in enumerate(prototypes)}
    binding_width, bindings = _normalized_bindings(assembly_parts, contract.point_instancer_joint_element_size)
    binding_support = _render_binding_support_primvars(context.model, bindings)
    prototype_paths = _prototype_target_paths(context.model, contract)

    _write_line(sink, indent_level, f'def PointInstancer "{contract.assembly_parts_instancer_name}" (')
    _write_line(sink, indent_level + 1, f'prepend apiSchemas = ["{contract.binding_api}"]')
    _write_line(sink, indent_level + 1, 'kind = "group"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, "int64[] invisibleIds = []")
    _write_array_attribute(
        sink,
        indent_level + 1,
        "quath[] orientations",
        (part.orientation.to_usda() for part in assembly_parts),
    )
    _write_array_attribute(
        sink,
        indent_level + 1,
        "point3f[] positions",
        (part.position.to_usda() for part in assembly_parts),
    )
    if binding_support:
        _write_block(sink, binding_support, indent_level + 1)
    _write_array_attribute(
        sink,
        indent_level + 1,
        contract.bind_joints_attr,
        (f'"{token}"' for binding in bindings for token in binding.joint_tokens),
        metadata_lines=(
            f"elementSize = {binding_width}",
            'interpolation = "vertex"',
        ),
    )
    _write_line(sink, indent_level + 1, "int[] primvars:unreal:naniteAssembly:bindJoints:indices = None")
    _write_array_attribute(
        sink,
        indent_level + 1,
        contract.bind_weights_attr,
        (f"{weight:g}" for binding in bindings for weight in binding.weights),
        metadata_lines=(
            f"elementSize = {binding_width}",
            'interpolation = "vertex"',
        ),
    )
    _write_line(sink, indent_level + 1, "int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None")
    _write_array_attribute(
        sink,
        indent_level + 1,
        "int[] protoIndices",
        (str(prototype_index_map.get(part.prototype_key, 0)) for part in assembly_parts),
    )
    _write_line(sink, indent_level + 1, f"rel prototypes = [{prototype_paths}]")
    _write_array_attribute(
        sink,
        indent_level + 1,
        "float3[] scales",
        (part.scale.to_usda() for part in assembly_parts),
    )
    _write_array_attribute(
        sink,
        indent_level + 1,
        "string[] primvars:name",
        (f'"{_prototype_name_for_instance(part, prototypes)}"' for part in assembly_parts),
        metadata_lines=('interpolation = "varying"',),
    )
    _write_line(sink, 0)
    _write_line(sink, indent_level + 1, f'def Scope "{contract.prototype_scope_name}" (')
    _write_line(sink, indent_level + 2, 'kind = "group"')
    _write_line(sink, indent_level + 1, ")")
    _write_line(sink, indent_level + 1, "{")
    for index, prototype in enumerate(prototypes, start=1):
        throw_if_cancelled(cancel_event)
        _emit_instancer_prototype(sink, prototype, context, indent_level + 2)
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.USDA_WRITING,
            completed_units=index,
            total_units=len(prototypes),
            message=f"Writing prototype {prototype.identity.prim_name}.",
            started_at=started_at,
        )
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _emit_parts_only_prototype_scope(
    sink,
    context: AuthoringContext,
    indent_level: int,
    *,
    telemetry_callback=None,
    cancel_event=None,
    started_at: float | None = None,
) -> None:
    contract = context.contract
    prototypes = context.model.prototypes
    if not prototypes:
        return

    _write_line(sink, indent_level, f'def Xform "{contract.assembly_parts_instancer_name}" (')
    _write_line(sink, indent_level + 1, 'kind = "group"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, f'def Scope "{contract.prototype_scope_name}" (')
    _write_line(sink, indent_level + 2, 'kind = "group"')
    _write_line(sink, indent_level + 1, ")")
    _write_line(sink, indent_level + 1, "{")
    for index, prototype in enumerate(prototypes, start=1):
        throw_if_cancelled(cancel_event)
        _emit_instancer_prototype(sink, prototype, context, indent_level + 2)
        emit_telemetry(
            telemetry_callback,
            ConversionPhase.USDA_WRITING,
            completed_units=index,
            total_units=len(prototypes),
            message=f"Writing prototype {prototype.identity.prim_name}.",
            started_at=started_at,
        )
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _emit_single_prototype_parts_document(
    sink,
    context: AuthoringContext,
) -> None:
    prototype = context.model.prototypes[0]
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        _write_block(sink, _render_external_instancer_prototype(prototype, context.contract), 0)
        return

    root_name = prototype.identity.prim_name
    _write_line(sink, 0, f'def Xform "{root_name}" (')
    _emit_asset_info_name_metadata(sink, 1, root_name)
    _write_line(sink, 0, ")")
    _write_line(sink, 0, "{")

    materials = _render_materials_scope(context.model.materials, root_name)
    if materials:
        _write_block(sink, materials, 1)
        _write_line(sink, 0)

    _emit_inline_part_payload(
        sink,
        prototype,
        context,
        indent_level=1,
        material_root_prim_name=root_name,
    )
    _write_line(sink, 0, "}")


def _emit_instancer_prototype(
    sink,
    prototype: Prototype,
    context: AuthoringContext,
    indent_level: int,
) -> None:
    contract = context.contract
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        _write_block(sink, _render_external_instancer_prototype(prototype, contract), indent_level)
        return

    if context.model.prototype_strategy != PrototypeStrategy.INLINE_SKELETAL_PART:
        _write_line(sink, indent_level, f'def "{prototype.identity.prim_name}" (')
        _write_line(
            sink,
            indent_level + 1,
            f"append references = </{contract.root_prim_name}/PrototypeLibrary/{prototype.identity.prim_name}>",
        )
        _write_line(sink, indent_level, ")")
        _write_line(sink, indent_level, "{")
        _write_line(sink, indent_level + 1, "token visibility = None")
        _write_line(sink, indent_level, "}")
        return

    _emit_part_prim(sink, prototype, context, indent_level)


def _emit_part_prim(
    sink,
    prototype: Prototype,
    context: AuthoringContext,
    indent_level: int,
) -> None:
    contract = context.contract
    if prototype.resolution_mode == PrototypeResolutionMode.EXTERNAL_ASSET:
        _write_block(sink, _render_external_instancer_prototype(prototype, contract), indent_level)
        return

    name = prototype.identity.prim_name
    if context.conversion_mode == ConversionMode.SKELETAL_PARTS:
        _write_line(sink, indent_level, f'def Xform "{name}" (')
        _emit_asset_info_name_metadata(sink, indent_level + 1, name)
        _write_line(sink, indent_level, ")")
    else:
        _write_line(sink, indent_level, f'def Xform "{name}"')
    _write_line(sink, indent_level, "{")
    _emit_inline_part_payload(
        sink,
        prototype,
        context,
        indent_level=indent_level + 1,
        material_root_prim_name=_parts_material_root_name(context),
    )
    _write_line(sink, indent_level, "}")


def _emit_inline_part_payload(
    sink,
    prototype: Prototype,
    context: AuthoringContext,
    *,
    indent_level: int,
    material_root_prim_name: str,
) -> None:
    contract = context.contract
    mesh = _prototype_inline_mesh(prototype)
    if mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")

    name = prototype.identity.prim_name
    part_mesh_name, part_joint_name, part_skeleton_name, part_animation_name = _resolve_inline_part_names(
        prototype,
        contract,
    )
    _write_line(sink, indent_level, f'def SkelRoot "{contract.part_skel_root_name}" (')
    _write_line(sink, indent_level + 1, 'kind = "component"')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, f'def SkelAnimation "{part_animation_name}"')
    _write_line(sink, indent_level + 1, "{")
    _write_line(sink, indent_level + 2, f'uniform token[] joints = ["{part_joint_name}"]')
    _write_line(sink, indent_level + 2, f"quath[] rotations = [{_identity_quaternion()}]")
    _write_line(sink, indent_level + 2, "half3[] scales = [(1, 1, 1)]")
    _write_line(sink, indent_level + 2, "float3[] translations = [(0, 0, 0)]")
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, 0)
    _write_line(sink, indent_level + 1, f'def Mesh "{part_mesh_name}" (')
    _write_line(sink, indent_level + 2, f'prepend apiSchemas = ["{contract.skel_binding_api}"]')
    if context.conversion_mode == ConversionMode.SKELETAL_PARTS:
        _emit_asset_info_name_metadata(sink, indent_level + 2, part_mesh_name)
    _write_line(sink, indent_level + 1, ")")
    _write_line(sink, indent_level + 1, "{")
    _write_line(sink, indent_level + 2, f'uniform token[] skel:joints = ["{part_joint_name}"]')
    _write_line(sink, indent_level + 2, f"uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}")
    _write_line(
        sink,
        indent_level + 2,
        f"append rel skel:skeleton = {_part_skeleton_path(context, name, part_skeleton_name)}",
    )
    _write_line(sink, indent_level + 2, 'uniform token subdivisionScheme = "none"')
    _emit_material_binding(sink, mesh, indent_level + 2, material_root_prim_name)
    _emit_mesh_payload(sink, mesh, contract.mesh_orientation, indent_level + 2)
    _emit_single_joint_skinning(sink, mesh, contract, indent_level + 2)
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, 0)
    _write_line(sink, indent_level + 1, f'def Skeleton "{part_skeleton_name}" (')
    _write_line(sink, indent_level + 2, f'prepend apiSchemas = ["{contract.skel_binding_api}"]')
    if context.conversion_mode == ConversionMode.SKELETAL_PARTS:
        _emit_asset_info_name_metadata(sink, indent_level + 2, part_skeleton_name)
    _write_line(sink, indent_level + 1, ")")
    _write_line(sink, indent_level + 1, "{")
    _write_line(sink, indent_level + 2, f"uniform matrix4d[] bindTransforms = [{_identity_matrix()}]")
    _write_line(sink, indent_level + 2, f'uniform token[] jointNames = ["{part_joint_name}"]')
    _write_line(sink, indent_level + 2, f'uniform token[] joints = ["{part_joint_name}"]')
    _write_line(sink, indent_level + 2, 'uniform token purpose = "guide"')
    _write_line(sink, indent_level + 2, f"uniform matrix4d[] restTransforms = [{_identity_matrix()}]")
    _write_line(
        sink,
        indent_level + 2,
        f"append rel skel:animationSource = {_part_animation_path(context, name, part_animation_name)}",
    )
    _write_line(sink, indent_level + 2, 'uniform token visibility = "invisible"')
    _write_line(sink, indent_level + 1, "}")
    _write_line(sink, indent_level, "}")


def _emit_material_binding(
    sink,
    mesh: MeshData | GeometryBuffer,
    indent_level: int,
    root_prim_name: str | None,
) -> None:
    sections = mesh.sections
    if not sections:
        return
    if len(sections) == 1:
        _write_line(
            sink,
            indent_level,
            f"rel material:binding = {_material_target_path(root_prim_name, sections[0].material_id)}",
        )
        return
    _write_line(sink, indent_level, 'uniform token subsetFamily:materialBind:familyType = "nonOverlapping"')
    for section in sections:
        _emit_geom_subset(sink, section, indent_level, root_prim_name)


def _emit_geom_subset(
    sink,
    section: MeshSection | CompactMeshSection,
    indent_level: int,
    root_prim_name: str | None,
) -> None:
    _write_line(sink, indent_level, f'def GeomSubset "{_material_prim_name_from_id(section.material_id)}" (')
    _write_line(sink, indent_level + 1, 'prepend apiSchemas = ["MaterialBindingAPI"]')
    _write_line(sink, indent_level, ")")
    _write_line(sink, indent_level, "{")
    _write_line(sink, indent_level + 1, 'uniform token elementType = "face"')
    _write_line(sink, indent_level + 1, 'uniform token familyName = "materialBind"')
    _write_array_attribute(
        sink,
        indent_level + 1,
        "int[] indices",
        (str(index) for index in section.face_indices),
    )
    _write_line(
        sink,
        indent_level + 1,
        f"rel material:binding = {_material_target_path(root_prim_name, section.material_id)}",
    )
    _write_line(sink, indent_level, "}")


def _emit_mesh_payload(sink, mesh: MeshData | GeometryBuffer, mesh_orientation: str, indent_level: int) -> None:
    _write_line(sink, indent_level, f'uniform token orientation = "{mesh_orientation}"')
    _write_array_attribute(
        sink,
        indent_level,
        "point3f[] points",
        _iter_payload_point_strings(mesh),
        metadata_lines=('interpolation = "vertex"',),
    )
    _write_array_attribute(
        sink,
        indent_level,
        "int[] faceVertexCounts",
        _iter_payload_face_count_strings(mesh),
    )
    _write_array_attribute(
        sink,
        indent_level,
        "int[] faceVertexIndices",
        _iter_payload_face_index_strings(mesh),
    )
    if _payload_has_uvs(mesh):
        _write_array_attribute(
            sink,
            indent_level,
            "texCoord2f[] primvars:st",
            _iter_payload_uv_strings(mesh),
            metadata_lines=('interpolation = "faceVarying"',),
        )


def _emit_single_joint_skinning(
    sink,
    mesh: MeshData | GeometryBuffer,
    contract: UeSchemaContract,
    indent_level: int,
) -> None:
    point_count = mesh.point_count if isinstance(mesh, GeometryBuffer) else len(mesh.points)
    _write_array_attribute(
        sink,
        indent_level,
        "uniform int[] primvars:skel:jointIndices",
        ("0" for _ in range(point_count)),
        metadata_lines=(
            "elementSize = 1",
            'interpolation = "vertex"',
        ),
    )
    _write_array_attribute(
        sink,
        indent_level,
        "uniform float[] primvars:skel:jointWeights",
        ("1" for _ in range(point_count)),
        metadata_lines=(
            "elementSize = 1",
            'interpolation = "vertex"',
        ),
    )
    _write_line(
        sink,
        indent_level,
        f'{contract.skinning_method_attr} = "{contract.skinning_method_value}"',
    )


def _write_line(sink, indent_level: int, text: str = "") -> None:
    sink.write(f'{" " * 4 * indent_level}{text}\n')


def _write_block(sink, value: str, indent_level: int) -> None:
    if not value:
        return
    sink.write(_indent(value, indent_level))
    sink.write("\n")


def _write_array_attribute(
    sink,
    indent_level: int,
    attribute_decl: str,
    values: Iterable[str],
    *,
    metadata_lines: tuple[str, ...] = (),
    chunk_size: int = 4096,
) -> None:
    prefix = " " * 4 * indent_level
    sink.write(f"{prefix}{attribute_decl} = [")
    _write_formatted_values(sink, values, chunk_size=chunk_size)
    sink.write("]")
    if metadata_lines:
        sink.write(" (\n")
        for line in metadata_lines:
            sink.write(f"{prefix}    {line}\n")
        sink.write(f"{prefix})\n")
        return
    sink.write("\n")


def _write_formatted_values(sink, values: Iterable[str], *, chunk_size: int) -> None:
    pending: list[str] = []
    wrote_any = False
    for value in values:
        pending.append(value)
        if len(pending) >= chunk_size:
            if wrote_any:
                sink.write(", ")
            sink.write(", ".join(pending))
            wrote_any = True
            pending.clear()
    if pending:
        if wrote_any:
            sink.write(", ")
        sink.write(", ".join(pending))


def _render_materials_scope(materials: tuple[MaterialSpec, ...], root_prim_name: str | None) -> str:
    if not materials:
        return ""
    definitions = "\n".join(_render_material(material, root_prim_name) for material in materials)
    return f'''def Scope "Materials"
{{
{definitions}
}}'''


def _render_material(material: MaterialSpec, root_prim_name: str | None) -> str:
    material_name = _material_prim_name(material)
    shader_name = _material_shader_name(material)
    diffuse_color = _material_diffuse_color(material)
    unreal_output = _render_unreal_material_output(material, root_prim_name)
    material_prefix = f"/{root_prim_name}" if root_prim_name else ""
    return f'''    def Material "{material_name}"
    {{
        token outputs:displacement.connect = <{material_prefix}/Materials/{material_name}/{shader_name}.outputs:displacement>
        token outputs:surface.connect = <{material_prefix}/Materials/{material_name}/{shader_name}.outputs:surface>
{_indent(unreal_output, 2)}

        def Shader "{shader_name}"
        {{
            uniform token info:id = "UsdPreviewSurface"
            color3f inputs:diffuseColor = {diffuse_color}
            token outputs:displacement
            token outputs:surface
        }}
    }}'''


def _render_main_skeleton(
    model: CanonicalTreeModel,
    contract: UeSchemaContract,
    base_skel_root_name: str,
    base_animation_name: str,
    skeleton_name: str,
    base_joint_root_name: str | None,
) -> str:
    return f'''def Skeleton "{skeleton_name}" (
    prepend apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform matrix4d[] bindTransforms = [{_render_bind_transforms(model)}]
    uniform token[] jointNames = [{_render_joint_basenames(model, root_joint_name=base_joint_root_name)}]
    uniform token[] joints = [{_render_joint_paths(model, root_joint_name=base_joint_root_name)}]
    uniform token purpose = "guide"
    uniform matrix4d[] restTransforms = [{_render_rest_transforms(model)}]
    append rel skel:animationSource = </{contract.root_prim_name}/{base_skel_root_name}/{base_animation_name}>
    uniform token visibility = "invisible"
}}'''


def _render_base_animation(
    model: CanonicalTreeModel,
    animation_name: str,
    root_joint_name: str | None,
) -> str:
    joints = _render_joint_paths(model, root_joint_name=root_joint_name)
    rotations = ", ".join(_identity_quaternion() for _ in model.skeleton)
    scales = ", ".join("(1, 1, 1)" for _ in model.skeleton)
    translations = _render_joint_rest_translations(model)
    return f'''def SkelAnimation "{animation_name}"
{{
    uniform token[] joints = [{joints}]
    quath[] rotations = [{rotations}]
    half3[] scales = [{scales}]
    float3[] translations = [{translations}]
}}'''


def _render_external_instancer_prototype(prototype: Prototype, contract: UeSchemaContract) -> str:
    if not prototype.mesh_asset_path:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing Unreal asset path.")
    return f'''def Xform "{prototype.identity.prim_name}" (
    prepend apiSchemas = ["{contract.external_ref_api}"]
    kind = "component"
)
{{
    uniform token unreal:naniteAssembly:meshAssetPath = "{prototype.mesh_asset_path}"
}}'''


def _render_skelroot_support_primvars(support: SkeletalSupportPrimvars | None) -> str:
    if support is None:
        return ""

    capture_paths = ", ".join(f'"{token}"' for token in support.capture_paths)
    ue_joint_names = ", ".join(f'"{token}"' for token in support.ue_joint_names)
    joint_count = len(support.capture_paths)
    hierarchical = ", ".join(str(value) for value in support.hierarchical_depths)
    logical = ", ".join(str(value) for value in support.logical_depths)
    return f'''string[] primvars:boneCapture_pCaptPath = [{capture_paths}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:boneCapture_pCaptPath:indices = None
        int[] primvars:boneCapture_pCaptPath:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        int[] primvars:hierarchicalDepth = [{hierarchical}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:hierarchicalDepth:indices = None
        int[] primvars:hierarchicalDepth:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        matrix4d primvars:localtransform = {support.local_transform.to_usda()}
        int[] primvars:localtransform:indices = None
        int[] primvars:logicalDepth = [{logical}] (
            elementSize = 1
            interpolation = "constant"
        )
        int[] primvars:logicalDepth:indices = None
        int[] primvars:logicalDepth:lengths = [{joint_count}] (
            interpolation = "constant"
        )
        token[] primvars:ueJointNames = [{ue_joint_names}] (
            elementSize = {joint_count}
            interpolation = "constant"
        )
        int[] primvars:ueJointNames:indices = None
        int[] primvars:ueJointNames:lengths = [{joint_count}] (
            interpolation = "constant"
        )'''


def _render_binding_support_primvars(
    model: CanonicalTreeModel,
    bindings: tuple[InstanceBinding, ...],
) -> str:
    support = model.skeletal_support_primvars
    if support is None or not bindings:
        return ""

    path_map = _build_joint_path_map(model)
    hierarchical_map = {token: depth for token, depth in zip(support.capture_paths, support.hierarchical_depths)}
    logical_map = {token: depth for token, depth in zip(support.capture_paths, support.logical_depths)}
    for joint, hierarchical_depth, logical_depth in zip(
        model.skeleton,
        support.hierarchical_depths,
        support.logical_depths,
        strict=False,
    ):
        hierarchical_map[joint.name] = hierarchical_depth
        logical_map[joint.name] = logical_depth
        hierarchical_map[path_map[joint.name]] = hierarchical_depth
        logical_map[path_map[joint.name]] = logical_depth

    hierarchical_values = [str(hierarchical_map.get(token, 0)) for binding in bindings for token in binding.joint_tokens]
    logical_values = [str(logical_map.get(token, 0)) for binding in bindings for token in binding.joint_tokens]
    lengths = ", ".join(str(binding.element_size) for binding in bindings)
    return f'''int[] primvars:hierarchicalDepth = [{", ".join(hierarchical_values)}] (
        interpolation = "vertex"
    )
    int[] primvars:hierarchicalDepth:lengths = [{lengths}] (
        interpolation = "varying"
    )
    int[] primvars:logicalDepth = [{", ".join(logical_values)}] (
        interpolation = "vertex"
    )
    int[] primvars:logicalDepth:lengths = [{lengths}] (
        interpolation = "varying"
    )'''


def _prototype_target_paths(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    if model.prototype_strategy == PrototypeStrategy.INLINE_SKELETAL_PART:
        return ", ".join(contract.prototype_root_path(prototype.identity.prim_name) for prototype in model.prototypes)
    return ", ".join(
        f"</{contract.root_prim_name}/{contract.assembly_parts_instancer_name}/{contract.prototype_scope_name}/"
        f"{prototype.identity.prim_name}>"
        for prototype in model.prototypes
    )


def _normalized_bindings(
    assembly_parts: tuple[AssemblyPartInstance, ...],
    target_width: int,
) -> tuple[int, tuple[InstanceBinding, ...]]:
    width = max((part.binding.element_size for part in assembly_parts), default=1)
    width = max(width, target_width, 1)
    return width, tuple(part.binding.padded(width) for part in assembly_parts)


def _prototype_name_for_instance(
    part: AssemblyPartInstance,
    prototypes: tuple[Prototype, ...],
) -> str:
    for prototype in prototypes:
        if prototype.source_key == part.prototype_key:
            return prototype.source_name
    return part.prototype_key


def _material_prim_name(material: MaterialSpec) -> str:
    return _material_prim_name_from_id(material.source_id)


def _material_prim_name_from_id(material_id: int, name: str | None = None) -> str:
    safe_name = "".join(
        character if character.isalnum() else "_"
        for character in (name or f"Material_{material_id}")
    ).strip("_")
    if not safe_name:
        safe_name = f"Material_{material_id}"
    return f"{safe_name}_{material_id}"


def _emit_asset_info_name_metadata(sink, indent_level: int, name: str) -> None:
    _write_line(sink, indent_level, "assetInfo = {")
    _write_line(sink, indent_level + 1, f'string name = "{name}"')
    _write_line(sink, indent_level, "}")


def _single_parts_asset_name(context: AuthoringContext) -> str | None:
    if context.conversion_mode != ConversionMode.SKELETAL_PARTS:
        return None
    if len(context.model.prototypes) != 1:
        return None
    return context.model.prototypes[0].identity.prim_name


def _is_single_prototype_parts_document(context: AuthoringContext) -> bool:
    return context.conversion_mode == ConversionMode.SKELETAL_PARTS and len(context.model.prototypes) == 1


def _stage_root_name(context: AuthoringContext) -> str:
    if _is_single_prototype_parts_document(context):
        return context.model.prototypes[0].identity.prim_name
    return context.contract.root_prim_name


def _parts_material_root_name(context: AuthoringContext) -> str:
    if _is_single_prototype_parts_document(context):
        return context.model.prototypes[0].identity.prim_name
    return context.contract.root_prim_name


def _material_target_path(root_prim_name: str | None, material_id: int) -> str:
    prefix = f"/{root_prim_name}" if root_prim_name else ""
    return f"<{prefix}/Materials/{_material_prim_name_from_id(material_id)}>"


def _material_shader_name(material: MaterialSpec) -> str:
    return f"{_material_prim_name(material)}_shader"


def _material_unreal_shader_name(material: MaterialSpec) -> str:
    return f"{_material_prim_name(material)}_unreal_shader"


def _render_unreal_material_output(material: MaterialSpec, root_prim_name: str | None) -> str:
    if not material.ue_asset_path:
        return ""
    material_name = _material_prim_name(material)
    shader_name = _material_unreal_shader_name(material)
    material_prefix = f"/{root_prim_name}" if root_prim_name else ""
    return f'''token outputs:unreal:surface.connect = <{material_prefix}/Materials/{material_name}/{shader_name}.outputs:out>

def Shader "{shader_name}"
{{
    uniform token info:implementationSource = "sourceAsset"
    uniform asset info:unreal:sourceAsset = @{material.ue_asset_path}@
    token outputs:out
}}'''


def _material_diffuse_color(material: MaterialSpec) -> str:
    color_map = next((dict(payload) for map_name, payload in material.maps if map_name == "Color"), None)
    if color_map is None:
        return "(0.5, 0.5, 0.5)"
    red = _clamp_material_channel(color_map.get("ColorR"))
    green = _clamp_material_channel(color_map.get("ColorG"))
    blue = _clamp_material_channel(color_map.get("ColorB"))
    return f"({red:g}, {green:g}, {blue:g})"


def _clamp_material_channel(value: str | None) -> float:
    if value is None:
        return 0.5
    try:
        numeric = float(value)
    except ValueError:
        return 0.5
    return max(0.0, min(1.0, numeric))


def _render_joint_paths(model: CanonicalTreeModel, root_joint_name: str | None = None) -> str:
    path_map = _build_joint_path_map(model, root_joint_name=root_joint_name)
    return ", ".join(f'"{path_map[joint.name]}"' for joint in model.skeleton)


def _render_joint_basenames(model: CanonicalTreeModel, root_joint_name: str | None = None) -> str:
    return ", ".join(f'"{_joint_render_name(joint, root_joint_name)}"' for joint in model.skeleton)


def _render_joint_rest_translations(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_translate.to_usda() for joint in model.skeleton)


def _indent(value: str, level: int) -> str:
    if not value:
        return ""
    prefix = " " * 4 * level
    return "\n".join(f"{prefix}{line}" if line else "" for line in value.splitlines())


def _build_joint_path_map(model: CanonicalTreeModel, root_joint_name: str | None = None) -> dict[str, str]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    path_map: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in path_map:
            return path_map[name]
        joint = joints_by_name[name]
        if joint.parent is None:
            path_map[name] = _joint_render_name(joint, root_joint_name)
        else:
            path_map[name] = f"{resolve(joint.parent)}/{_joint_render_name(joint, root_joint_name)}"
        return path_map[name]

    for joint in model.skeleton:
        resolve(joint.name)
    return path_map


def _joint_render_name(joint, root_joint_name: str | None) -> str:
    if root_joint_name and joint.parent is None:
        return root_joint_name
    return joint.name


def _resolved_root_joint_alias(model: CanonicalTreeModel, default_name: str) -> str | None:
    root_joint_count = sum(1 for joint in model.skeleton if joint.parent is None)
    if root_joint_count == 1:
        return default_name
    return None


def _identity_matrix() -> str:
    return "( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )"


def _render_bind_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.bind_transform.to_usda() for joint in model.skeleton)


def _render_rest_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.rest_transform.to_usda() for joint in model.skeleton)


def _identity_quaternion() -> str:
    return "(1, 0, 0, 0)"


def _prototype_inline_mesh(prototype: Prototype) -> MeshData | GeometryBuffer | None:
    if prototype.mesh is not None:
        return prototype.mesh
    if prototype.geometry_payload is not None:
        return prototype.geometry_payload
    return None


def _iter_payload_point_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.point_components), 3):
            yield f"({mesh.point_components[index]:g}, {mesh.point_components[index + 1]:g}, {mesh.point_components[index + 2]:g})"
        return
    for point in mesh.points:
        yield point.to_usda()


def _iter_payload_face_count_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for value in mesh.face_vertex_counts:
            yield str(value)
        return
    for value in mesh.face_vertex_counts:
        yield str(value)


def _iter_payload_face_index_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for value in mesh.face_vertex_indices:
            yield str(value)
        return
    for value in mesh.face_vertex_indices:
        yield str(value)


def _iter_payload_uv_strings(mesh: MeshData | GeometryBuffer):
    if isinstance(mesh, GeometryBuffer):
        for index in range(0, len(mesh.uv_components), 2):
            yield f"({mesh.uv_components[index]:g}, {mesh.uv_components[index + 1]:g})"
        return
    for uv in mesh.uv_coords:
        yield uv.to_usda()


def _payload_has_uvs(mesh: MeshData | GeometryBuffer) -> bool:
    if isinstance(mesh, GeometryBuffer):
        return bool(mesh.uv_components)
    return bool(mesh.uv_coords)


def _resolve_inline_part_names(
    prototype: Prototype,
    contract: UeSchemaContract,
) -> tuple[str, str, str, str]:
    prototype_name = prototype.identity.prim_name
    part_mesh_name = make_stable_prim_name(prototype_name, fallback=contract.part_mesh_name)
    part_joint_name = make_stable_prim_name(prototype_name, fallback="root")
    if prototype.source_mode == PrototypeSourceMode.FBX_FILE:
        part_skeleton_name = make_stable_prim_name(
            f"{prototype_name}_Skeleton",
            fallback=contract.part_skeleton_name,
        )
        part_animation_name = make_stable_prim_name(
            f"{prototype_name}_Animation",
            fallback=contract.part_animation_name,
        )
        return part_mesh_name, part_joint_name, part_skeleton_name, part_animation_name
    return part_mesh_name, part_joint_name, contract.part_skeleton_name, contract.part_animation_name


def _part_skeleton_path(context: AuthoringContext, prototype_name: str, skeleton_name: str) -> str:
    contract = context.contract
    if _is_single_prototype_parts_document(context):
        return f"</{prototype_name}/{contract.part_skel_root_name}/{skeleton_name}>"
    return (
        f"</{contract.root_prim_name}/{contract.assembly_parts_instancer_name}/"
        f"{contract.prototype_scope_name}/{prototype_name}/{contract.part_skel_root_name}/{skeleton_name}>"
    )


def _part_animation_path(context: AuthoringContext, prototype_name: str, animation_name: str) -> str:
    contract = context.contract
    if _is_single_prototype_parts_document(context):
        return f"</{prototype_name}/{contract.part_skel_root_name}/{animation_name}>"
    return (
        f"</{contract.root_prim_name}/{contract.assembly_parts_instancer_name}/"
        f"{contract.prototype_scope_name}/{prototype_name}/{contract.part_skel_root_name}/{animation_name}>"
    )
