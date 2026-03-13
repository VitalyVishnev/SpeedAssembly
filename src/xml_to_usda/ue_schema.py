from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class UeSchemaContract:
    stage_meters_per_unit: float = 1.0
    stage_up_axis: str = "Y"
    mesh_type_attr: str = "unreal:naniteAssembly:meshType"
    mesh_type_value: str = "skeletalMesh"
    root_api: str = "NaniteAssemblyRootAPI"
    root_kind: str = "component"
    binding_api: str = "NaniteAssemblySkelBindingAPI"
    external_ref_api: str = "NaniteAssemblyExternalRefAPI"
    skel_binding_api: str = "SkelBindingAPI"
    skeleton_relationship_attr: str = "custom rel unreal:naniteAssembly:skeleton = </Tree/TrunkSkelRoot/TrunkSkeleton>"
    bind_joints_attr: str = "token[] primvars:unreal:naniteAssembly:bindJoints"
    bind_weights_attr: str = "float[] primvars:unreal:naniteAssembly:bindJointWeights"
    skinning_method_attr: str = "uniform token primvars:skel:skinningMethod"
    skinning_method_value: str = "classicLinear"
    point_instancer_joint_element_size: int = 2
    root_api_allowed_prims: tuple[str, ...] = ("Xform",)
    external_ref_api_allowed_prims: tuple[str, ...] = ("Xform",)
    binding_api_allowed_prims: tuple[str, ...] = ("Xform", "Mesh", "SkelRoot", "PointInstancer")


DEFAULT_UE_SCHEMA_CONTRACT = UeSchemaContract()
