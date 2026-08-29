"""Dump Dynamic Wind bone mappings for the selected Unreal Skeletal Mesh."""

import unreal


def _prop(value, name):
    try:
        return value.get_editor_property(name)
    except Exception as exc:
        raise RuntimeError(f"Python cannot read reflected property '{name}': {exc}") from exc


def _optional_prop(value, name):
    try:
        return value.get_editor_property(name)
    except Exception as exc:
        unreal.log_warning(f"DW_DIAG Property '{name}' is not exposed to UE Python: {exc}")
        return None


selected = [asset for asset in unreal.EditorUtilityLibrary.get_selected_assets() if isinstance(asset, unreal.SkeletalMesh)]
if len(selected) != 1:
    raise RuntimeError(f"Select exactly one Skeletal Mesh in Content Browser; found {len(selected)}")

mesh = selected[0]
component = unreal.new_object(unreal.SkeletalMeshComponent)
component.set_skeletal_mesh_asset(mesh)

bones = []
for index in range(component.get_num_bones()):
    name = str(component.get_bone_name(index))
    parent_name = str(component.get_parent_bone(component.get_bone_name(index)))
    bones.append(name)
    unreal.log_warning(f"DW_DIAG Bone[{index}] Name='{name}' Parent='{parent_name}'")

wind_data = next(
    (
        data
        for data in _prop(mesh, "asset_user_data")
        if data and data.get_class().get_name() == "DynamicWindSkeletalData"
    ),
    None,
)
if wind_data is None:
    raise RuntimeError("Selected mesh has no DynamicWindSkeletalData in Asset User Data")

groups = _optional_prop(wind_data, "simulation_groups")
lookups = _optional_prop(wind_data, "simulation_group_bones")
if groups is None or lookups is None:
    unreal.log_warning(
        f"DW_DIAG Mesh='{mesh.get_path_name()}' Bones={len(bones)}; "
        "this UE build hides Dynamic Wind lookup arrays from Python"
    )
    unreal.log_warning("DW_DIAG RESULT: compare the printed RefSkeleton names with JointName strings in the imported JSON")
    raise SystemExit

unreal.log_warning(f"DW_DIAG Mesh='{mesh.get_path_name()}' Bones={len(bones)} SimulationGroups={len(groups)}")

mapped_indices = set()
for lookup in lookups:
    group_index = int(_prop(lookup, "simulation_group_index"))
    indices = sorted(int(index) for index in _prop(lookup, "bone_indices"))
    mapped_indices.update(indices)
    labels = [f"{index}:'{bones[index]}'" if 0 <= index < len(bones) else f"{index}:<INVALID>" for index in indices]
    unreal.log_warning(f"DW_DIAG Group[{group_index}] Bones=[{', '.join(labels)}]")

if not lookups:
    unreal.log_error("DW_DIAG RESULT: no skeleton bones matched the imported Dynamic Wind joints")
elif mapped_indices == {0}:
    unreal.log_error("DW_DIAG RESULT: only bone 0 matched; this can produce rigid rotation around the root pivot")
else:
    missing = [f"{index}:'{bones[index]}'" for index in range(len(bones)) if index not in mapped_indices]
    if missing:
        unreal.log_warning(f"DW_DIAG RESULT: unmapped bones=[{', '.join(missing)}]")
    else:
        unreal.log_warning("DW_DIAG RESULT: every skeleton bone has a Dynamic Wind group")

for origin, chain in _prop(wind_data, "bone_chains").items():
    unreal.log_warning(
        "DW_DIAG Chain "
        f"Origin={int(origin)} NumBones={int(_prop(chain, 'num_bones'))} "
        f"Length={float(_prop(chain, 'chain_length')):.6f}"
    )

for bone_index, extra in _prop(wind_data, "extra_bones_data").items():
    unreal.log_warning(
        "DW_DIAG Extra "
        f"Bone={int(bone_index)} Origin={int(_prop(extra, 'bone_chain_origin_bone_index'))} "
        f"ChainIndex={int(_prop(extra, 'index_in_bone_chain'))}"
    )
