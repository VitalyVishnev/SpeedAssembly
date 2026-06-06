from __future__ import annotations

from pathlib import Path, PureWindowsPath

from .models import ConversionRequest


REPO_ROOT = Path(__file__).resolve().parents[2]
VAULT_ROOT = REPO_ROOT / "vault"


def resolve_output_path(request: ConversionRequest, input_path: str) -> Path | None:
    if request.output_path:
        return Path(request.output_path)

    if request.output_directory:
        output_dir = Path(request.output_directory)
        file_name = render_output_file_name(Path(input_path), request.output_naming_template)
        return resolve_output_file_in_directory(output_dir, file_name)

    if len(request.input_paths) == 1:
        input_file = Path(input_path)
        return input_file.with_suffix(".usda")

    raise ValueError("Batch conversion requires output_directory or explicit per-file naming.")


def render_output_file_name(input_path: Path, naming_template: str | None) -> str:
    stem = input_path.stem
    if naming_template:
        file_name = naming_template.format(stem=stem)
        _ensure_usda_file_name(file_name)
        if not file_name.lower().endswith(".usda"):
            file_name = f"{file_name}.usda"
        _ensure_usda_file_name(file_name)
        return file_name
    return f"{stem}.usda"


def resolve_output_file_in_directory(output_dir: Path, file_name: str) -> Path:
    _ensure_usda_file_name(file_name)
    output_path = output_dir / file_name
    resolved_dir = output_dir.resolve()
    resolved_output = output_path.resolve()
    if not resolved_output.is_relative_to(resolved_dir):
        raise ValueError("Output naming template must produce a USDA filename inside the selected output directory.")
    return output_path


def resolve_skeletal_parts_output_directory(output_path: Path) -> Path:
    if output_path.suffix:
        return output_path.with_suffix("")
    return output_path


def ensure_output_path_allowed(output_path: Path) -> None:
    if not VAULT_ROOT.exists():
        return
    resolved_output = output_path.resolve()
    resolved_vault = VAULT_ROOT.resolve()
    if resolved_output.is_relative_to(resolved_vault):
        raise ValueError(f"Generated outputs must not be written inside the immutable vault: {resolved_output}")


def _ensure_usda_file_name(file_name: str) -> None:
    windows_path = PureWindowsPath(file_name)
    if (
        not file_name
        or file_name in {".", ".."}
        or "/" in file_name
        or "\\" in file_name
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.name != file_name
        or windows_path.stem.upper() in _WINDOWS_RESERVED_NAMES
    ):
        raise ValueError("Output naming template must produce a USDA filename, not a path.")


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
