"""Release zip assembly for the packaged operator build."""

from __future__ import annotations

import argparse
from pathlib import Path
import zipfile

from .qt_ui.help_deck import HELP_SLIDES


RELEASE_ZIP_NAME = "XMLtoUSDAConverter_release.zip"


def build_release_bundle(*, repo_root: str | Path, dist_path: str | Path, zip_path: str | Path | None = None) -> Path:
    """Create the release zip shipped alongside the standalone executable."""
    resolved_repo_root = Path(repo_root).resolve()
    resolved_dist_path = Path(dist_path).resolve()
    resolved_zip_path = Path(zip_path).resolve() if zip_path is not None else resolved_dist_path / RELEASE_ZIP_NAME

    exe_path = resolved_dist_path / "XMLtoUSDAConverter.exe"
    if not exe_path.exists():
        raise FileNotFoundError(f"Release executable is missing: {exe_path}")
    worker_exe_path = resolved_dist_path / "XMLtoUSDAWorker.exe"
    if not worker_exe_path.exists():
        raise FileNotFoundError(f"Release worker executable is missing: {worker_exe_path}")

    resolved_zip_path.parent.mkdir(parents=True, exist_ok=True)
    if resolved_zip_path.exists():
        resolved_zip_path.unlink()

    with zipfile.ZipFile(resolved_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(exe_path, "XMLtoUSDAConverter.exe")
        archive.write(worker_exe_path, "XMLtoUSDAWorker.exe")
        build_info_path = resolved_dist_path / "build_info.json"
        if build_info_path.exists():
            archive.write(build_info_path, "build_info.json")
        for source_path, archive_name in _example_asset_entries(resolved_repo_root):
            archive.write(source_path, archive_name)
        archive.writestr("help/How_to_use.txt", _render_help_text())

    return resolved_zip_path


def _example_asset_entries(repo_root: Path) -> tuple[tuple[Path, str], ...]:
    entries: list[tuple[Path, str]] = []
    for root in (
        repo_root / "samples" / "README.md",
        repo_root / "samples" / "speedtree" / "simple_tree",
        repo_root / "samples" / "expected_usda",
    ):
        if root.is_file():
            entries.append((root, _example_archive_name(repo_root, root)))
        elif root.is_dir():
            for path in sorted((candidate for candidate in root.rglob("*") if _is_packaged_example_file(candidate)), key=_path_key):
                entries.append((path, _example_archive_name(repo_root, path)))
    return tuple(entries)


def _example_archive_name(repo_root: Path, path: Path) -> str:
    return f"examples/{path.relative_to(repo_root).as_posix()}"


def _render_help_text() -> str:
    lines = ["XML to USDA Converter - How to use", ""]
    for slide in HELP_SLIDES:
        lines.extend((slide.title, slide.body, ""))
    return "\n".join(lines).strip() + "\n"


def _path_key(path: Path) -> str:
    return path.as_posix().casefold()


def _is_packaged_example_file(path: Path) -> bool:
    return path.is_file() and not path.name.startswith(".")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the XML to USDA release zip.")
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
