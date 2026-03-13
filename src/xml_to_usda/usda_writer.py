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
)
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


def render_usda(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
) -> UsdAssemblyDocument:
    error_codes = [issue.code for issue in diagnostics if issue.severity == "error"]
    if error_codes:
        raise ValueError(
            "Cannot author USDA while validation errors are present: " + ", ".join(sorted(dict.fromkeys(error_codes)))
        )
    base_mesh = _render_base_mesh(model, contract)
    skeleton = _render_skeleton(model)
    animation = _render_animation(model)
    point_instancer = _render_point_instancer(model, contract)
    branch_library = _render_branch_library(model)
    skelroot_support = _render_skelroot_support_primvars(model.skeletal_support_primvars)

    text = f'''#usda 1.0
(
    defaultPrim = "Tree"
    metersPerUnit = {contract.stage_meters_per_unit:g}
    upAxis = "{contract.stage_up_axis}"
)

def Xform "Tree" (
    prepend apiSchemas = ["{contract.root_api}"]
    kind = "{contract.root_kind}"
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

{_indent(animation, 2)}

{_indent(base_mesh, 2)}

{_indent(skeleton, 2)}
    }}

{_indent(point_instancer, 1)}
}}
'''
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics)


def _render_base_mesh(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    if model.base_mesh is None:
        raise ValueError("Base skeletal mesh is required before USDA authoring.")
    mesh = model.base_mesh
    joint_paths = _render_joint_names(model)
    joint_indices = ", ".join(str(index) for index in mesh.skel_joint_indices)
    joint_weights = ", ".join(f"{weight:g}" for weight in mesh.skel_joint_weights)
    skinning = ""
    if mesh.skel_joint_indices and mesh.skel_joint_weights:
        skinning = f'''
    int[] primvars:skel:jointIndices = [{joint_indices}] (
        elementSize = {mesh.skel_element_size or 1}
        interpolation = "vertex"
    )
    float[] primvars:skel:jointWeights = [{joint_weights}] (
        elementSize = {mesh.skel_element_size or 1}
        interpolation = "vertex"
    )
    {contract.skinning_method_attr} = "{contract.skinning_method_value}"'''
    return f'''def Mesh "TrunkMesh" (
    apiSchemas = ["{contract.skel_binding_api}"]
)
{{
    uniform token[] skel:joints = [{joint_paths}]
    uniform matrix4d primvars:skel:geomBindTransform = {_identity_matrix()}
    rel skel:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>
    uniform token subdivisionScheme = "none"
    {_render_mesh_payload(mesh)}{skinning}
}}'''


def _render_skeleton(model: CanonicalTreeModel) -> str:
    return f'''def Skeleton "TrunkSkeleton" (
    prepend apiSchemas = ["SkelBindingAPI"]
)
{{
    uniform matrix4d[] bindTransforms = [{_render_bind_transforms(model)}]
    append rel skel:animationSource = </Tree/TrunkSkelRoot/animation>
    uniform token[] joints = [{_render_joint_names(model)}]
    uniform token[] jointNames = [{_render_joint_basenames(model)}]
    float3[] restTransforms:translations = [{_render_joint_translations(model)}]
}}'''


def _render_animation(model: CanonicalTreeModel) -> str:
    joints = _render_joint_names(model)
    rotations = ", ".join(_identity_quaternion() for _ in model.skeleton)
    scales = ", ".join("(1, 1, 1)" for _ in model.skeleton)
    translations = _render_joint_translations(model)
    return f'''def SkelAnimation "animation"
{{
    uniform token[] joints = [{joints}]
    quath[] rotations = [{rotations}]
    half3[] scales = [{scales}]
    float3[] translations = [{translations}]
}}'''


def _render_branch_library(model: CanonicalTreeModel) -> str:
    if not model.prototypes:
        return ""
    definitions = "\n".join(_render_branch_prototype(prototype) for prototype in model.prototypes)
    return f'''def Xform "Branches"
{{
{definitions}
}}'''


def _render_branch_prototype(prototype: Prototype) -> str:
    if prototype.mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")
    mesh = prototype.mesh
    name = prototype.identity.prim_name
    return f'''    def Xform "{name}" (
        kind = "component"
    )
    {{
        token visibility = "invisible"
        def Mesh "{name}_Mesh"
        {{
            {_render_mesh_payload(mesh)}
        }}
    }}'''


def _render_point_instancer(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    leaves = model.leaf_instances
    prototypes = model.prototypes
    if not leaves:
        return ""
    prototype_index_map = {prototype.source_key: index for index, prototype in enumerate(prototypes)}
    proto_indices = ", ".join(str(prototype_index_map.get(leaf.prototype_key, 0)) for leaf in leaves)
    positions = ", ".join(leaf.position.to_usda() for leaf in leaves)
    orientations = ", ".join(leaf.orientation.to_usda() for leaf in leaves)
    scales = ", ".join(leaf.scale.to_usda() for leaf in leaves)
    names = ", ".join(f'"{_prototype_name_for_instance(leaf, prototypes)}"' for leaf in leaves)
    binding_width, bindings = _normalized_bindings(leaves, contract.point_instancer_joint_element_size)
    bind_joints = ", ".join(f'"{token}"' for binding in bindings for token in binding.joint_tokens)
    bind_weights = ", ".join(f"{weight:g}" for binding in bindings for weight in binding.weights)
    prototype_paths = _prototype_target_paths(model)
    prototype_defs = _render_instancer_prototypes(model)
    binding_support = _render_binding_support_primvars(model, bindings)

    return f'''def PointInstancer "PartsInstancer" (
    prepend apiSchemas = ["{contract.binding_api}"]
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
    int[] primvars:unreal:naniteAssembly:bindJoints:indices = None
    {contract.bind_weights_attr} = [{bind_weights}] (
        elementSize = {binding_width}
        interpolation = "vertex"
    )
    int[] primvars:unreal:naniteAssembly:bindJointWeights:indices = None
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
    if prototype.mesh is None:
        raise ValueError(f"Prototype {prototype.identity.prim_name} is missing mesh payload.")
    mesh = prototype.mesh
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


def _normalized_bindings(leaves, target_width: int) -> tuple[int, tuple[InstanceBinding, ...]]:
    width = max((leaf.binding.element_size for leaf in leaves), default=1)
    width = max(width, target_width, 1)
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


def _render_bind_transforms(model: CanonicalTreeModel) -> str:
    return ", ".join(_translation_matrix(joint.bind_translate) for joint in model.skeleton)


def _translation_matrix(translate: Vector3) -> str:
    return (
        "( "
        f"(1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 1, 0), ({translate.x:g}, {translate.y:g}, {translate.z:g}, 1)"
        " )"
    )


def _identity_quaternion() -> str:
    return "(1, 0, 0, 0)"
