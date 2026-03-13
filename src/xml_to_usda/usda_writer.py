from __future__ import annotations

from collections import OrderedDict

from .models import CanonicalTreeModel, MeshData, PrototypeIdentity, UsdAssemblyDocument, ValidationIssue, Vector3
from .naming import build_prototype_identities
from .ue_schema import DEFAULT_UE_SCHEMA_CONTRACT, UeSchemaContract


def render_usda(
    model: CanonicalTreeModel,
    diagnostics: tuple[ValidationIssue, ...],
    contract: UeSchemaContract = DEFAULT_UE_SCHEMA_CONTRACT,
) -> UsdAssemblyDocument:
    trunk = _render_trunk_mesh(model, contract)
    point_instancer = _render_point_instancer(model, contract)

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

    def SkelRoot "TrunkSkelRoot" (
        kind = "component"
    )
    {{
{_indent(trunk, 2)}

        def Skeleton "TrunkSkeleton"
        {{
            uniform token[] joints = [{_render_joint_names(model)}]
            uniform token[] jointNames = [{_render_joint_basenames(model)}]
            float3[] restTransforms:translations = [{_render_joint_translations(model)}]
        }}
    }}

{_indent(point_instancer, 1)}
}}
'''
    return UsdAssemblyDocument(text=text, diagnostics=diagnostics)


def _render_trunk_mesh(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    skel_rel = 'rel skel:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>'
    mesh = model.trunk_mesh or _fallback_triangle("TrunkMesh")
    return f'''def Mesh "TrunkMesh" (
            apiSchemas = ["{contract.skel_binding_api}"]
        )
        {{
            {skel_rel}
            {_render_mesh_payload(mesh)}
        }}'''


def _render_joint_names(model: CanonicalTreeModel) -> str:
    path_map = _build_joint_path_map(model)
    return ", ".join(f'"{path_map[joint.name]}"' for joint in model.skeleton)


def _render_joint_basenames(model: CanonicalTreeModel) -> str:
    return ", ".join(f'"{joint.name}"' for joint in model.skeleton)


def _render_joint_translations(model: CanonicalTreeModel) -> str:
    return ", ".join(joint.bind_translate.to_usda() for joint in model.skeleton)


def _render_point_instancer(model: CanonicalTreeModel, contract: UeSchemaContract) -> str:
    leaves = model.leaf_instances
    prototype_identities = _collect_prototype_identities(leaves)
    mesh_library = {f"Mesh_{entry.mesh_id}": entry.mesh for entry in model.mesh_library}
    proto_index_map = {identity.source_key: index for index, identity in enumerate(prototype_identities)}
    proto_indices = ", ".join(str(proto_index_map.get(leaf.prototype_key, 0)) for leaf in leaves)
    positions = ", ".join(leaf.position.to_usda() for leaf in leaves)
    orientations = ", ".join(leaf.orientation.to_usda() for leaf in leaves)
    scales = ", ".join(leaf.scale.to_usda() for leaf in leaves)
    bind_joints = ", ".join(f'"{leaf.bind_joint}"' for leaf in leaves)
    bind_weights = ", ".join(f"{leaf.bind_weight:g}" for leaf in leaves)
    prototype_targets = [f"</Tree/PartsInstancer/Prototypes/{identity.prim_name}>" for identity in prototype_identities]
    prototype_paths = f"[{', '.join(prototype_targets)}]" if prototype_targets else "[]"
    prototype_defs = "\n".join(
        _render_prototype_definition(identity, mesh_library.get(identity.source_key), contract)
        for identity in prototype_identities
    )

    return f'''def PointInstancer "PartsInstancer" (
    apiSchemas = ["{contract.binding_api}"]
    kind = "group"
)
{{
    rel prototypes = {prototype_paths}
    int[] protoIndices = [{proto_indices}]
    point3f[] positions = [{positions}]
    quatf[] orientations = [{orientations}]
    float3[] scales = [{scales}]
    {contract.bind_joints_attr} = [{bind_joints}] (
        elementSize = 1
    )
    {contract.bind_weights_attr} = [{bind_weights}] (
        elementSize = 1
    )

    def Scope "Prototypes" (
        kind = "group"
    )
    {{
{prototype_defs}
    }}
}}'''


def _collect_prototype_identities(leaves) -> tuple[PrototypeIdentity, ...]:
    keys = list(OrderedDict.fromkeys(leaf.prototype_key for leaf in leaves)) or ["LeafPrototype"]
    return build_prototype_identities(keys)


def _render_prototype_definition(identity: PrototypeIdentity, mesh: MeshData | None, contract: UeSchemaContract) -> str:
    name = identity.prim_name
    prototype_mesh = mesh or _fallback_triangle(f"{name}_Mesh")
    return f'''        def SkelRoot "{name}" (
            kind = "component"
        )
        {{
            def Skeleton "{name}_Skeleton"
            {{
                uniform token[] joints = ["root"]
                uniform token[] jointNames = ["root"]
                float3[] restTransforms:translations = [(0, 0, 0)]
            }}

            def Mesh "{name}_Mesh" (
                apiSchemas = ["{contract.skel_binding_api}"]
            )
            {{
                rel skel:skeleton = </Tree/PartsInstancer/Prototypes/{name}/{name}_Skeleton>
                {_render_mesh_payload(prototype_mesh)}
            }}
        }}'''


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
