"""Release zip assembly for the packaged operator build."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile


RELEASE_ZIP_NAME = "SpeedAssembly_release.zip"


def build_release_bundle(*, repo_root: str | Path, dist_path: str | Path, zip_path: str | Path | None = None) -> Path:
    """Create the release zip shipped alongside the standalone executable."""
    resolved_repo_root = Path(repo_root).resolve()
    resolved_dist_path = Path(dist_path).resolve()
    resolved_zip_path = Path(zip_path).resolve() if zip_path is not None else resolved_dist_path / RELEASE_ZIP_NAME

    exe_path = resolved_dist_path / "SpeedAssembly.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"Release executable is missing: {exe_path}")

    resolved_zip_path.parent.mkdir(parents=True, exist_ok=True)
    if resolved_zip_path.exists():
        resolved_zip_path.unlink()

    with zipfile.ZipFile(resolved_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe_path, "SpeedAssembly.exe")
        for legal_name in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
            legal_path = resolved_repo_root / legal_name
            if not legal_path.exists():
                raise FileNotFoundError(f"Release legal notice is missing: {legal_path}")
            archive.write(legal_path, legal_name)
        ufbx_license = resolved_repo_root / "src" / "xml_to_usda" / "vendor" / "ufbx" / "LICENSE"
        if not ufbx_license.exists():
            raise FileNotFoundError(f"Vendored ufbx license is missing: {ufbx_license}")
        archive.write(ufbx_license, "licenses/ufbx-LICENSE")
        sample_path = resolved_repo_root / "samples" / "speedtree" / "simple_tree" / "variants" / "SimpleTree_01.xml"
        if not sample_path.exists():
            raise FileNotFoundError(f"Packaged example is missing: {sample_path}")
        archive.write(sample_path, "examples/SimpleTree_01.xml")

    return resolved_zip_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the SpeedAssembly release zip.")
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--dist-path", required=True)
    parser.add_argument("--zip-path", default=None)
    args = parser.parse_args(argv)

    bundle_path = build_release_bundle(
        repo_root=args.repo_root,
        dist_path=args.dist_path,
        zip_path=args.zip_path,
    )
    print(f"Wrote release zip: {bundle_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
