from __future__ import annotations

from dataclasses import dataclass, replace

from .models import ConversionMode


@dataclass(frozen=True)
class UeSchemaContract:
    stage_meters_per_unit: float = 1.0
    stage_up_axis: str = "Y"
    root_prim_name: str = "Tree"
    base_skel_root_name: str = "BaseTreeSkelRoot"
    base_mesh_name: str = "BaseTreeMesh"
    base_animation_name: str = "BaseTreeAnimation"
    skeleton_name: str = "MainSkeleton"
    assembly_parts_instancer_name: str = "AssemblyPartsInstancer"
    prototype_scope_name: str = "Prototypes"
    part_skel_root_name: str = "PartSkelRoot"
    part_mesh_name: str = "PartMesh"
    part_animation_name: str = "PartAnimation"
    part_skeleton_name: str = "PartSkeleton"
    mesh_orientation: str = "rightHanded"
    mesh_type_attr: str = "unreal:naniteAssembly:meshType"
    mesh_type_value: str = "skeletalMesh"
    root_api: str = "NaniteAssemblyRootAPI"
    root_kind: str = "component"
    binding_api: str = "NaniteAssemblySkelBindingAPI"
    external_ref_api: str = "NaniteAssemblyExternalRefAPI"
    skel_binding_api: str = "SkelBindingAPI"
    bind_joints_attr: str = "token[] primvars:unreal:naniteAssembly:bindJoints"
    bind_weights_attr: str = "float[] primvars:unreal:naniteAssembly:bindJointWeights"
    skinning_method_attr: str = "uniform token primvars:skel:skinningMethod"
    skinning_method_value: str = "classicLinear"
    point_instancer_joint_element_size: int = 2
    root_api_allowed_prims: tuple[str, ...] = ("Xform",)
    external_ref_api_allowed_prims: tuple[str, ...] = ("Xform",)
    binding_api_allowed_prims: tuple[str, ...] = ("Xform", "Mesh", "SkelRoot", "PointInstancer")

    def for_conversion_mode(
        self,
        conversion_mode: ConversionMode,
        *,
        root_prim_name: str | None = None,
    ) -> "UeSchemaContract":
        if conversion_mode in {ConversionMode.SKELETAL_ASSEMBLY, ConversionMode.SKELETAL_PARTS}:
            if root_prim_name and root_prim_name != self.root_prim_name:
                return replace(self, root_prim_name=root_prim_name)
            return self
        if conversion_mode == ConversionMode.STATIC_ASSEMBLY:
            updates = {
                "mesh_type_value": "staticMesh",
                "root_kind": "group",
            }
            if root_prim_name:
                updates["root_prim_name"] = root_prim_name
            return replace(self, **updates)
        raise ValueError(f"Unsupported conversion mode for UE schema contract: {conversion_mode.value}.")

    @property
    def main_skeleton_path(self) -> str:
        return f"</{self.root_prim_name}/{self.base_skel_root_name}/{self.skeleton_name}>"

    @property
    def base_animation_path(self) -> str:
        return f"</{self.root_prim_name}/{self.base_skel_root_name}/{self.base_animation_name}>"

    @property
    def skeleton_relationship_attr(self) -> str:
        return f"rel unreal:naniteAssembly:skeleton = {self.main_skeleton_path}"

    def prototype_root_path(self, prototype_name: str) -> str:
        return (
            f"</{self.root_prim_name}/{self.assembly_parts_instancer_name}/"
            f"{self.prototype_scope_name}/{prototype_name}>"
        )

    def part_skeleton_path(self, prototype_name: str) -> str:
        return (
            f"</{self.root_prim_name}/{self.assembly_parts_instancer_name}/"
            f"{self.prototype_scope_name}/{prototype_name}/{self.part_skel_root_name}/{self.part_skeleton_name}>"
        )

    def part_animation_path(self, prototype_name: str) -> str:
        return (
            f"</{self.root_prim_name}/{self.assembly_parts_instancer_name}/"
            f"{self.prototype_scope_name}/{prototype_name}/{self.part_skel_root_name}/{self.part_animation_name}>"
        )


DEFAULT_UE_SCHEMA_CONTRACT = UeSchemaContract()
