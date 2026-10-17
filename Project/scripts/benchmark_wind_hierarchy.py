"""Compare automatic groups with operator-selected XML and USD/JSON references.

Reference data never enters the application classifier. Run from Project/ with
the repository's Python environment; --report writes Markdown and JSON results.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from xml_to_usda.canonical_loader import load_source_tree_model
from xml_to_usda.dynamic_wind import build_dynamic_wind_data
from xml_to_usda.wind_external_skeleton import _load_usd_skeleton_candidates
from xml_to_usda.wind_tree_hierarchy import TreeHierarchySettings, analyze_tree_hierarchy
from xml_to_usda.wind_viewport_scene import build_auto_wind_viewport_data


def usd_reference(path: Path):
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    target = {joint["JointName"]: int(joint["SimulationGroupIndex"]) for joint in payload["Joints"]}
    if len(target) != len(payload["Joints"]):
        raise ValueError(f"Duplicate reference joint names: {path}")
    usd_path = path.with_name(path.name.removesuffix("_DynamicWind.json") + ".usda")
    matches = []
    for candidate in _load_usd_skeleton_candidates(usd_path):
        skeleton = candidate.joints
        names = {joint.name for joint in skeleton}
        mapped = dict(target)
        roots = [joint for joint in skeleton if joint.parent is None]
        # The converter aliases one XML root to the authored asset stem.
        if len(roots) == 1 and "root" in mapped and "root" not in names and roots[0].name not in mapped:
            mapped[roots[0].name] = mapped.pop("root")
        extras = names - set(mapped)
        synthetic = {joint.name for joint in skeleton if joint.source_id == -1}
        if set(mapped) <= names and extras <= synthetic:
            matches.append((skeleton, mapped, str(candidate.choice.prim_path), sorted(extras)))
    if len(matches) != 1:
        raise ValueError(f"Expected one skeleton matching reference joints, found {len(matches)}: {usd_path}")
    return matches[0]


def xml_reference(path: Path):
    _, model, _ = load_source_tree_model(path, source_cache_enabled=False)
    groups = build_dynamic_wind_data(model.skeleton)
    return model.skeleton, {joint.joint_name: joint.simulation_group_index for joint in groups.joint_assignments}, "XML Bones", []


def compare(path: Path, settings: TreeHierarchySettings = TreeHierarchySettings()) -> dict:
    skeleton, target, prim, unlabelled = usd_reference(path) if path.suffix.lower() == ".json" else xml_reference(path)
    # All methods receive precisely the same bare rig. Endpoints and labels
    # cannot leak from the gold XML into the geometric method's inputs.
    bare = tuple(replace(joint, source_id=None, generator_label=None, generator_level=None, bind_end_transform=None) for joint in skeleton)
    group_count = max(target.values()) + 1
    methods = {}
    analysis = analyze_tree_hierarchy(bare, settings)
    for method in ("order", "pve", "tree"):
        data = build_auto_wind_viewport_data(bare, group_count, method=method, tree_analysis=analysis if method == "tree" else None)
        predicted = {joint.joint_name: joint.simulation_group_index for joint in data.joint_assignments}
        differences = [{"joint": name, "expected": group, "actual": predicted[name]} for name, group in target.items() if predicted[name] != group]
        methods[method] = {"mismatches": len(differences), "accuracy": 1 - len(differences) / len(target), "differences": differences}
    return {
        "reference": str(path), "skeleton": prim, "joint_count": len(skeleton),
        "labelled_joint_count": len(target), "unlabelled_synthetic_roots": unlabelled,
        "group_count": group_count, "ambiguous_joints": [joint.name for joint in analysis if joint.ambiguous],
        "tree_settings": asdict(settings),
        "methods": methods,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-dir", type=Path, help="Directory containing paired *_DynamicWind.json and .usda references.")
    parser.add_argument("--xml", type=Path, action="append", default=[], help="Explicitly approved XML reference; repeat as needed.")
    parser.add_argument("--report", type=Path, default=Path("tmp/wind-hierarchy-benchmark.md"))
    parser.add_argument("--equivalent-forks", choices=("keep_parent", "advance", "continuation"), default="keep_parent")
    args = parser.parse_args()
    paths = sorted(args.reference_dir.rglob("*_DynamicWind.json")) if args.reference_dir else []
    paths += args.xml
    if not paths:
        parser.error("Select reference data with --reference-dir or --xml.")
    rows = []
    for path in paths:
        result = compare(path, TreeHierarchySettings(equivalent_forks=args.equivalent_forks))
        rows.append(result)
        print(path.name, {method: result["methods"][method]["mismatches"] for method in ("order", "pve", "tree")}, flush=True)
    lines = ["# Wind hierarchy reference comparison", "", f"Equivalent fork policy: {args.equivalent_forks}.", "", "Inputs: bare bind poses and parent relationships, without names as features, XML generator labels, physical endpoints, mesh geometry, or companion-file lookup.", "",
             "Group count matches each reference. Errors count labelled joints; an imported synthetic root absent from the reference is reported separately. XML generator groups and manual JSON groups are evaluated as supplied, including source-specific boundaries.", "",
             "| Reference | Labelled joints | Groups | Order errors | PVE errors | Tree errors |", "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for row in rows:
        errors = [row["methods"][method]["mismatches"] for method in ("order", "pve", "tree")]
        lines.append(f"| {Path(row['reference']).name} | {row['labelled_joint_count']} | {row['group_count']} | {' | '.join(str(value) for value in errors)} |")
    lines += ["", "These are calibration/reference results, not independent proof of generalization. The Norway 01 XML and USDA/JSON are the same rig and should not be counted as two independent examples.", "",
              "Tree is a proposal for operator comparison. Review the JSON report's per-joint differences, especially Willow and 03_28mil. Some near-collinear generator transitions are not recoverable as certain anatomical boundaries from the bare rig.", ""]
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text("\n".join(lines), encoding="utf-8")
    args.report.with_suffix(".json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
