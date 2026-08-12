"""Fix selected foliage Skeletal Meshes and their Skeleton Assets in UE 5.7."""

import unreal


_ZERO_LENGTH_SQUARED = 1.0e-8


def _package_name(asset):
    return asset.get_path_name().split(".", 1)[0]


def _other_meshes_using(skeletal_mesh):
    skeleton = skeletal_mesh.skeleton
    registry = unreal.AssetRegistryHelpers.get_asset_registry()
    options = unreal.AssetRegistryDependencyOptions(
        include_soft_package_references=True,
        include_hard_package_references=True,
        include_game_package_references=True,
        include_editor_only_package_references=True,
    )
    own_package = _package_name(skeletal_mesh)
    result = []
    for package in registry.get_referencers(_package_name(skeleton), options) or []:
        if str(package) == own_package:
            continue
        for asset_data in registry.get_assets_by_package_name(package) or []:
            if asset_data.get_class() == unreal.SkeletalMesh:
                result.append(str(asset_data.package_name))
    return sorted(set(result))


def _normalized(vector):
    length_squared = vector.x * vector.x + vector.y * vector.y + vector.z * vector.z
    if length_squared <= _ZERO_LENGTH_SQUARED:
        return None
    return vector / (length_squared ** 0.5)


def _project_perpendicular(vector, normal):
    return vector - normal * (vector.x * normal.x + vector.y * normal.y + vector.z * normal.z)


def _continuation_direction(index, positions, parent_indices, children):
    origin = positions[index]
    descendant = index
    while children[descendant]:
        descendant = min(children[descendant])
        direction = _normalized(positions[descendant] - origin)
        if direction is not None:
            return direction
    ancestor = parent_indices[index]
    while ancestor >= 0:
        direction = _normalized(origin - positions[ancestor])
        if direction is not None:
            return direction
        ancestor = parent_indices[ancestor]
    return None


def _modifier_for(skeletal_mesh):
    modifier = unreal.SkeletonModifier()
    if not modifier.set_skeletal_mesh(skeletal_mesh):
        raise RuntimeError(f"Cannot edit {skeletal_mesh.get_path_name()}")
    return modifier


def _orient(modifier, bones):
    index_by_name = {str(bone): index for index, bone in enumerate(bones)}
    parent_indices = []
    children = [[] for _bone in bones]
    for index, bone in enumerate(bones):
        parent_index = index_by_name.get(str(modifier.get_parent_name(bone)), -1)
        parent_indices.append(parent_index)
        if parent_index >= 0:
            children[parent_index].append(index)

    source_globals = [modifier.get_bone_transform(bone, True) for bone in bones]
    positions = [transform.translation for transform in source_globals]
    oriented_globals = []

    world_axes = (
        unreal.Vector(1.0, 0.0, 0.0),
        unreal.Vector(0.0, 1.0, 0.0),
        unreal.Vector(0.0, 0.0, 1.0),
    )
    for index, source_global in enumerate(source_globals):
        parent_index = parent_indices[index]
        direction = _continuation_direction(index, positions, parent_indices, children)
        if direction is None:
            if parent_index < 0:
                raise RuntimeError(f"Cannot determine direction for root bone {bones[index]}")
            direction = oriented_globals[parent_index].rotation.get_axis_x()

        if parent_index >= 0:
            preferred_y = oriented_globals[parent_index].rotation.get_axis_y()
            fallback_y = oriented_globals[parent_index].rotation.get_axis_z()
        else:
            preferred_y = source_global.rotation.get_axis_y()
            fallback_y = source_global.rotation.get_axis_z()
        secondary = _normalized(_project_perpendicular(preferred_y, direction))
        if secondary is None:
            secondary = _normalized(_project_perpendicular(fallback_y, direction))
        if secondary is None:
            fallback_y = min(
                world_axes,
                key=lambda axis: abs(axis.x * direction.x + axis.y * direction.y + axis.z * direction.z),
            )
            secondary = _normalized(_project_perpendicular(fallback_y, direction))

        oriented = unreal.Transform(
            location=source_global.translation,
            rotation=unreal.MathLibrary.make_rot_from_xy(direction, secondary),
            scale=source_global.scale3d,
        )
        oriented_globals.append(oriented)

    local_transforms = [
        transform
        if parent_indices[index] < 0
        else transform.make_relative(oriented_globals[parent_indices[index]])
        for index, transform in enumerate(oriented_globals)
    ]
    if not modifier.set_bones_transforms(bones, local_transforms, False):
        raise RuntimeError("Bone orientation failed")


def _temporary_leaf_name(modifier, bones):
    existing = {str(bone) for bone in bones}
    leaves = [
        bone
        for bone in reversed(bones)
        if str(modifier.get_parent_name(bone)) != "None"
        and not modifier.get_children_names(bone, False)
    ]
    if not leaves:
        raise RuntimeError("The skeleton has no non-root leaf bone")
    original = leaves[0]
    temporary = f"{original}__XSync"
    while temporary in existing:
        temporary += "_"
    return original, unreal.Name(temporary)


def _fix(skeletal_mesh):
    skeleton = skeletal_mesh.skeleton
    modifier = _modifier_for(skeletal_mesh)
    bones = list(modifier.get_all_bone_names())
    if len(bones) < 2:
        raise RuntimeError(f"{skeletal_mesh.get_path_name()} has no orientable bone chain")
    skeleton_pose = skeleton.get_reference_pose()
    if not skeleton_pose.is_valid() or list(skeleton_pose.get_bone_names()) != bones:
        raise RuntimeError(
            f"{skeletal_mesh.get_path_name()} and its Skeleton Asset do not have the same bone tree"
        )

    _orient(modifier, bones)
    original, temporary = _temporary_leaf_name(modifier, bones)
    if not modifier.rename_bones([original], [temporary]):
        raise RuntimeError("Cannot prepare Skeleton Asset synchronization")
    if not modifier.commit_skeleton_to_skeletal_mesh():
        raise RuntimeError(f"Cannot synchronize {skeletal_mesh.get_path_name()}")

    modifier = _modifier_for(skeletal_mesh)
    if not modifier.rename_bones([temporary], [original]):
        raise RuntimeError("Cannot restore the original bone name")
    if not modifier.commit_skeleton_to_skeletal_mesh():
        raise RuntimeError(f"Cannot finish {skeletal_mesh.get_path_name()}")

    modifier = _modifier_for(skeletal_mesh)
    final_bones = list(modifier.get_all_bone_names())
    skeleton_pose = skeleton.get_reference_pose()
    if not skeleton_pose.is_valid() or any(
        not modifier.get_bone_transform(bone, False).is_near_equal(
            skeleton_pose.get_bone_pose(bone, unreal.AnimPoseSpaces.LOCAL)
        )
        for bone in final_bones
    ):
        raise RuntimeError(f"Skeleton Asset did not synchronize for {skeletal_mesh.get_path_name()}")
    return skeleton


def main():
    if not hasattr(unreal, "SkeletonModifier"):
        raise RuntimeError("Enable the Skeletal Mesh Editing Tools plugin")
    meshes = sorted(
        {
            asset.get_path_name(): asset
            for asset in unreal.EditorUtilityLibrary.get_selected_assets()
            if isinstance(asset, unreal.SkeletalMesh)
        }.values(),
        key=lambda asset: asset.get_path_name(),
    )
    if not meshes:
        raise RuntimeError("Select at least one Skeletal Mesh")

    conflicts = {}
    for mesh in meshes:
        if mesh.skeleton is None:
            conflicts[mesh.get_path_name()] = ["No Skeleton Asset"]
            continue
        references = _other_meshes_using(mesh)
        if references:
            conflicts[mesh.get_path_name()] = references
    if conflicts:
        raise RuntimeError(f"Each selected mesh must have a dedicated Skeleton Asset: {conflicts}")

    transaction = unreal.ScopedEditorTransaction("Fix Foliage Bones Orientation")
    try:
        assets_to_save = []
        for mesh in meshes:
            assets_to_save.extend((mesh, _fix(mesh)))
        if not unreal.EditorAssetLibrary.save_loaded_assets(
            assets_to_save, only_if_is_dirty=False
        ):
            raise RuntimeError("Could not save all modified assets")
    finally:
        del transaction


if __name__ == "__main__":
    main()
