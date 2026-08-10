"""Duplicate a UE 5.8 Skeletal Mesh and orient its bones along +X."""

import unreal


OUTPUT_SUFFIX = "_XOriented"


def main():
    if not hasattr(unreal, "SkeletonModifier"):
        raise RuntimeError(
            "SkeletonModifier is unavailable. Enable the Skeletal Mesh Editing Tools plugin."
        )

    selected = [
        asset
        for asset in unreal.EditorUtilityLibrary.get_selected_assets()
        if isinstance(asset, unreal.SkeletalMesh)
    ]
    if len(selected) != 1:
        raise RuntimeError("Select exactly one Skeletal Mesh in the Content Browser.")

    source = selected[0]
    source_package = source.get_path_name().split(".", 1)[0]
    output_folder = source_package.rsplit("/", 1)[0]
    target_name = f"{source.get_name()}{OUTPUT_SUFFIX}"
    target_path = f"{output_folder}/{target_name}"
    if unreal.EditorAssetLibrary.does_asset_exist(target_path):
        raise RuntimeError(f"Experiment asset already exists: {target_path}")

    asset_tools = unreal.AssetToolsHelpers.get_asset_tools()
    target = asset_tools.duplicate_asset(target_name, output_folder, source)
    if not isinstance(target, unreal.SkeletalMesh):
        raise RuntimeError(f"Could not duplicate {source.get_path_name()} to {target_path}")

    modifier = unreal.SkeletonModifier()
    if not modifier.set_skeletal_mesh(target):
        raise RuntimeError(f"Could not initialize SkeletonModifier for {target_path}")

    bones = list(modifier.get_all_bone_names())
    if not bones:
        raise RuntimeError(f"No bones found in {target_path}")

    options = unreal.OrientOptions(
        primary=unreal.OrientAxis.POSITIVE_X,
        secondary=unreal.OrientAxis.POSITIVE_Y,
        use_plane_as_secondary=True,
        orient_children=True,
    )
    if not modifier.orient_bones(bones, options):
        raise RuntimeError(f"Bone orientation failed for {target_path}")
    if not modifier.commit_skeleton_to_skeletal_mesh():
        raise RuntimeError(f"Skeleton commit failed for {target_path}")

    if not unreal.EditorAssetLibrary.save_loaded_asset(
        target, only_if_is_dirty=False
    ):
        raise RuntimeError(f"Could not save {target_path}")

    unreal.EditorAssetLibrary.sync_browser_to_objects([target_path])
    unreal.log(f"Created +X-oriented experiment: {target_path}")
    unreal.log_warning(
        "UE Python cannot set SkeletonFactory.TargetSkeletalMesh. "
        "Right-click the selected mesh and choose Skeleton > Create Skeleton."
    )


main()
