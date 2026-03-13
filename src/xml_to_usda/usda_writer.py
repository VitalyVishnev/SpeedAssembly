from __future__ import annotations

from .models import (
    CanonicalTreeModel,
    InstanceBinding,
    MeshData,
    Prototype,
    PrototypeStrategy,
    SkeletalSupportPrimvars,
    UsdAssemblyDocument,
    ValidationIssue,
    Vector3,
)
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


def render_usda(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
) -> UsdAssemblyDocument:
    base_mesh = _render_base_mesh(model, contract)
    skeleton = _render_skeleton(model)
    point_instancer = _render_point_instancer(model, contract)
    branch_library = _render_branch_library(model)
    skelroot_support = _render_skelroot_support_primvars(model.skeletal_support_primvars)

    text = f'''#usda 1.0
(
    defaultPrim = "Tree"
    metersPerUnit = {model.metadata.meters_per_unit}
    upAxis = "{model.metadata.up_axis}"
)

def Xform "Tree" (
    kind = "group"
    apiSchemas = ["{contract.root_api}"]
)
{{
    uniform token {contract.mesh_type_attr} = "{contract.mesh_type_value}"
    {contract.skeleton_relationship_attr}

{_indent(branch_library, 1)}

    def SkelRoot "TrunkSkelRoot" (
        kind = "component"
    )
    {{
{_indent(skelroot_support, 2)}
        matrix4d xformOp:transform = {_identity_matrix()}
        uniform token[] xformOpOrder = ["xformOp:transform"]

{_indent(base_mesh, 2)}

{_indent(skeleton, 2)}
    }}

{_indent(point_instancer, 1)}
}}
'''
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics)


def _render_base_mesh(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    mesh = model.base_mesh or _fallback_triangle("TrunkMesh")
    return f'''def Mesh "TrunkMesh" (
    apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    rel skel:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>
    {_render_mesh_payload(mesh)}
}}'''


def _render_skeleton(model: CanonicalTreeModel) -> str:
    return f'''def Skeleton "TrunkSkeleton"
{{
    uniform token[] joints = [{_render_joint_names(model)}]
    uniform token[] jointNames = [{_render_joint_basenames(model)}]
    float3[] restTransforms:translations = [{_render_joint_translations(model)}]
}}'''


def _render_branch_library(model: CanonicalTreeModel) -> str:
    if not model.prototypes:
        return 'def Xform "Branches" {}'
    definitions = "\n".join(_render_branch_prototype(prototype) for prototype in model.prototypes)
    return f'''def Xform "Branches"
{{
{definitions}
}}'''


def _render_branch_prototype(prototype: Prototype) -> str:
    mesh = prototype.mesh or _fallback_triangle(f"{prototype.identity.prim_name}_Mesh")
    name = prototype.identity.prim_name
    return f'''    def Xform "{name}" (
        kind = "component"
    )
    {{
        def Mesh "{name}_Mesh"
        {{
            {_render_mesh_payload(mesh)}
        }}
    }}'''


def _render_point_instancer(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    leaves = model.leaf_instances
    prototypes = model.prototypes
    prototype_index_map = {prototype.source_key: index for index, prototype in enumerate(prototypes)}
    proto_indices = ", ".join(str(prototype_index_map.get(leaf.prototype_key, 0)) for leaf in leaves)
    positions = ", ".join(leaf.position.to_usda() for leaf in leaves)
    orientations = ", ".join(leaf.orientation.to_usda() for leaf in leaves)
    scales = ", ".join(leaf.scale.to_usda() for leaf in leaves)
    names = ", ".join(f'"{_prototype_name_for_instance(leaf, prototypes)}"' for leaf in leaves)
    binding_width, bindings = _normalized_bindings(leaves)
    bind_joints = ", ".join(f'"{token}"' for binding in bindings for token in binding.joint_tokens)
    bind_weights = ", ".join(f"{weight:g}" for binding in bindings for weight in binding.weights)
    prototype_paths = _prototype_target_paths(model)
    prototype_defs = _render_instancer_prototypes(model)
    binding_support = _render_binding_support_primvars(model, bindings)

    return f'''def PointInstancer "PartsInstancer" (
    apiSchemas = ["{contract.binding_api}"]
    kind = "group"
)
{{
    int64[] invisibleIds = []
    quath[] orientations = [{orientations}]
    point3f[] positions = [{positions}]
{_indent(binding_support, 1)}
    {contract.bind_joints_attr} = [{bind_joints}] (
        elementSize = {binding_width}
        interpolation = "vertex"
    )
    {contract.bind_weights_attr} = [{bind_weights}] (
        elementSize = {binding_width}
        interpolation = "vertex"
    )
    int[] protoIndices = [{proto_indices}]
    rel prototypes = [{prototype_paths}]
    float3[] scales = [{scales}]
    string[] primvars:name = [{names}] (
        interpolation = "varying"
    )

    def Scope "Prototypes" (
        kind = "group"
    )
    {{
{_indent(prototype_defs, 2)}
    }}
}}'''


def _render_binding_support_primvars(model: CanonicalTreeModel, bindings: tuple[InstanceBinding, ...]) -> str:
    support = model.skeletal_support_primvars
    if support is None or not bindings:
        return ""
    hierarchical_map = {token: depth for token, depth in zip(support.capture_paths, support.hierarchical_depths)}
    logical_map = {token: depth for token, depth in zip(support.capture_paths, support.logical_depths)}
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


def _render_instancer_prototypes(model: CanonicalTreeModel) -> str:
    if model.prototype_strategy == PrototypeStrategy.INLINE_MESH:
        return "\n".join(_render_inline_instancer_prototype(prototype) for prototype in model.prototypes)

    definitions = "\n".join(
        f'''            def "{prototype.identity.prim_name}" (
                append references = </Tree/Branches/{prototype.identity.prim_name}>
            )
            {{
                token visibility = None
            }}'''
        for prototype in model.prototypes
    )
    return f'''def Xform "Tree"
{{
    def Xform "Branches"
    {{
{definitions}
    }}
}}'''


def _render_inline_instancer_prototype(prototype: Prototype) -> str:
    mesh = prototype.mesh or _fallback_triangle(f"{prototype.identity.prim_name}_Mesh")
    name = prototype.identity.prim_name
    return f'''        def Xform "{name}"
        {{
            def Mesh "{name}_Mesh"
            {{
                {_render_mesh_payload(mesh)}
            }}
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


def _prototype_target_paths(model: CanonicalTreeModel) -> str:
    if model.prototype_strategy == PrototypeStrategy.INLINE_MESH:
        return ", ".join(f"</Tree/PartsInstancer/Prototypes/{prototype.identity.prim_name}>" for prototype in model.prototypes)
    return ", ".join(
        f"</Tree/PartsInstancer/Prototypes/Tree/Branches/{prototype.identity.prim_name}>"
        for prototype in model.prototypes
    )


def _normalized_bindings(leaves) -> tuple[int, tuple[InstanceBinding, ...]]:
    width = max((leaf.binding.element_size for leaf in leaves), default=1)
    width = max(width, 1)
    return width, tuple(leaf.binding.padded(width) for leaf in leaves)


def _prototype_name_for_instance(leaf, prototypes: tuple[Prototype, ...]) -> str:
    for prototype in prototypes:
        if prototype.source_key == leaf.prototype_key:
            return prototype.source_name
    return leaf.prototype_key


def _render_joint_names(model: CanonicalTreeModel) -> str:
    path_map = _build_joint_path_map(model)
    return ", ".join(f'"{path_map[joint.name]}"' for joint in model.skeleton)


def _render_joint_basenames(model: CanonicalTreeModel) -> str:
    return ", ".join(f'"{joint.name}"' for joint in model.skeleton)


def _render_joint_translations(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.bind_translate.to_usda() for joint in model.skeleton)


def _render_mesh_payload(mesh: MeshData) -> str:
    points = ", ".join(point.to_usda() for point in mesh.points)
    counts = ", ".join(str(value) for value in mesh.face_vertex_counts)
    indices = ", ".join(str(value) for value in mesh.face_vertex_indices)
    return f'''point3f[] points = [{points}]
    int[] faceVertexCounts = [{counts}]
    int[] faceVertexIndices = [{indices}]'''


def _fallback_triangle(name: str) -> MeshData:
    return MeshData(
        name=name,
        points=(
            Vector3(0.0, 0.0, 0.0),
            Vector3(0.01, 0.0, 0.0),
            Vector3(0.0, 0.01, 0.0),
        ),
        face_vertex_counts=(3,),
        face_vertex_indices=(0, 1, 2),
    )


def _indent(value: str, level: int) -> str:
    if not value:
        return ""
    prefix = " " * 4 * level
    return "\n".join(f"{prefix}{line}" if line else "" for line in value.splitlines())


def _build_joint_path_map(model: CanonicalTreeModel) -> dict[str, str]:
    joints_by_name = {joint.name: joint for joint in model.skeleton}
    path_map: dict[str, str] = {}

    def resolve(name: str) -> str:
        if name in path_map:
            return path_map[name]
        joint = joints_by_name[name]
        if joint.parent is None:
            path_map[name] = joint.name
        else:
            path_map[name] = f"{resolve(joint.parent)}/{joint.name}"
        return path_map[name]

    for joint in model.skeleton:
        resolve(joint.name)
    return path_map


def _identity_matrix() -> str:
    return "( (1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1) )"
