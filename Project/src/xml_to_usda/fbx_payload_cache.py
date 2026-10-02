from __future__ import annotations

import hashlib
import json
import os
import time
from array import array
from base64 import b64decode, b64encode
from dataclasses import dataclass
from pathlib import Path

from .models import CompactMeshSection, FbxMaterialSlotSpec, GeometryBuffer
from .runtime_paths import resolve_runtime_paths


FBX_PAYLOAD_CACHE_SCHEMA_VERSION = 2
FBX_PAYLOAD_CACHE_MAX_BYTES = 20 * 1024 * 1024 * 1024
FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
_PAYLOAD_SUFFIX = ".payload.json"
_META_SUFFIX = ".meta.json"


@dataclass(frozen=True)
class FbxPayloadCacheOptions:
    read_vertex_colors: bool
    read_material_slots: bool
    strict_vertex_colors: bool


@dataclass(frozen=True)
class FbxPayloadCacheResult:
    payload: GeometryBuffer | None
    hit: bool
    message: str = ""
    cache_path: Path | None = None


@dataclass(frozen=True)
class FbxPayloadCacheSummary:
    entry_count: int = 0
    total_bytes: int = 0
    removed_entries: int = 0
    removed_bytes: int = 0
    failed_paths: tuple[Path, ...] = ()


def load_fbx_payload_from_cache(
    fbx_path: str,
    options: FbxPayloadCacheOptions,
    *,
    cache_root: Path | None = None,
) -> FbxPayloadCacheResult:
    if not _is_cacheable_source_path(fbx_path):
        return FbxPayloadCacheResult(None, hit=False, message="cache_skipped_for_test_backend")
    payload_path, meta_path = _cache_paths(fbx_path, options, cache_root=cache_root)
    if payload_path is None or meta_path is None:
        return FbxPayloadCacheResult(None, hit=False, message="cache_key_unavailable")
    if not payload_path.exists() or not meta_path.exists():
        return FbxPayloadCacheResult(None, hit=False, cache_path=payload_path)
    try:
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("schema_version") != FBX_PAYLOAD_CACHE_SCHEMA_VERSION:
            return FbxPayloadCacheResult(None, hit=False, message="schema_mismatch", cache_path=payload_path)
        payload = _read_geometry_payload_json(payload_path)
        if not isinstance(payload, GeometryBuffer):
            return FbxPayloadCacheResult(None, hit=False, message="payload_type_mismatch", cache_path=payload_path)
        _touch_cache_files(payload_path, meta_path)
        return FbxPayloadCacheResult(payload, hit=True, cache_path=payload_path)
    except Exception as exc:
        _unlink_quietly(payload_path)
        _unlink_quietly(meta_path)
        return FbxPayloadCacheResult(None, hit=False, message=f"cache_read_failed: {exc}", cache_path=payload_path)


def store_fbx_payload_in_cache(
    fbx_path: str,
    options: FbxPayloadCacheOptions,
    payload: GeometryBuffer,
    *,
    cache_root: Path | None = None,
    max_bytes: int = FBX_PAYLOAD_CACHE_MAX_BYTES,
    max_age_seconds: int = FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS,
) -> FbxPayloadCacheResult:
    if not _is_cacheable_source_path(fbx_path):
        return FbxPayloadCacheResult(None, hit=False, message="cache_skipped_for_test_backend")
    payload_path, meta_path = _cache_paths(fbx_path, options, cache_root=cache_root)
    if payload_path is None or meta_path is None:
        return FbxPayloadCacheResult(None, hit=False, message="cache_key_unavailable")
    root = payload_path.parent
    root.mkdir(parents=True, exist_ok=True)
    payload_tmp = payload_path.with_suffix(f"{payload_path.suffix}.partial")
    meta_tmp = meta_path.with_suffix(f"{meta_path.suffix}.partial")
    try:
        _write_geometry_payload_json(payload_tmp, payload)
        metadata = _metadata_for(fbx_path, options)
        metadata["created_at_unix"] = time.time()
        metadata["payload_bytes"] = payload_tmp.stat().st_size
        meta_tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        payload_tmp.replace(payload_path)
        meta_tmp.replace(meta_path)
        sweep_fbx_payload_cache(cache_root=root, max_bytes=max_bytes, max_age_seconds=max_age_seconds)
        return FbxPayloadCacheResult(payload, hit=False, message="cache_stored", cache_path=payload_path)
    except Exception as exc:
        _unlink_quietly(payload_tmp)
        _unlink_quietly(meta_tmp)
        return FbxPayloadCacheResult(None, hit=False, message=f"cache_write_failed: {exc}", cache_path=payload_path)


def summarize_fbx_payload_cache(*, cache_root: Path | None = None) -> FbxPayloadCacheSummary:
    root = cache_root or _default_fbx_cache_root()
    if not root.exists():
        return FbxPayloadCacheSummary()
    entry_count = 0
    total_bytes = 0
    failed_paths: list[Path] = []
    for payload_path in _iter_cache_payload_paths(root):
        try:
            stat = payload_path.stat()
        except OSError:
            failed_paths.append(payload_path)
            continue
        entry_count += 1
        total_bytes += stat.st_size
    return FbxPayloadCacheSummary(
        entry_count=entry_count,
        total_bytes=total_bytes,
        failed_paths=tuple(failed_paths),
    )


def clear_fbx_payload_cache(*, cache_root: Path | None = None) -> FbxPayloadCacheSummary:
    root = cache_root or _default_fbx_cache_root()
    if not root.exists():
        return FbxPayloadCacheSummary()
    removed_entries = 0
    removed_bytes = 0
    failed_paths: list[Path] = []
    for payload_path in _iter_cache_payload_paths(root):
        meta_path = _meta_path_for_payload(payload_path)
        size = _payload_size_or_zero(payload_path, failed_paths)
        if _unlink_report(payload_path, failed_paths):
            removed_entries += 1
            removed_bytes += size
        _unlink_report(meta_path, failed_paths)
    after = summarize_fbx_payload_cache(cache_root=root)
    return FbxPayloadCacheSummary(
        entry_count=after.entry_count,
        total_bytes=after.total_bytes,
        removed_entries=removed_entries,
        removed_bytes=removed_bytes,
        failed_paths=tuple([*failed_paths, *after.failed_paths]),
    )


def sweep_fbx_payload_cache(
    *,
    cache_root: Path | None = None,
    max_bytes: int = FBX_PAYLOAD_CACHE_MAX_BYTES,
    max_age_seconds: int = FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS,
    now: float | None = None,
) -> FbxPayloadCacheSummary:
    root = cache_root or _default_fbx_cache_root()
    if not root.exists():
        return FbxPayloadCacheSummary()
    current_time = time.time() if now is None else now
    entries: list[tuple[float, int, Path, Path]] = []
    removed_entries = 0
    removed_bytes = 0
    failed_paths: list[Path] = []
    for payload_path in _iter_cache_payload_paths(root):
        meta_path = _meta_path_for_payload(payload_path)
        try:
            stat = payload_path.stat()
        except OSError:
            failed_paths.append(payload_path)
            continue
        age = current_time - stat.st_mtime
        if age > max_age_seconds:
            if _unlink_report(payload_path, failed_paths):
                removed_entries += 1
                removed_bytes += stat.st_size
            _unlink_report(meta_path, failed_paths)
            continue
        entries.append((stat.st_mtime, stat.st_size, payload_path, meta_path))

    total_bytes = sum(size for _mtime, size, _payload_path, _meta_path in entries)
    if total_bytes <= max_bytes:
        after = summarize_fbx_payload_cache(cache_root=root)
        return FbxPayloadCacheSummary(
            entry_count=after.entry_count,
            total_bytes=after.total_bytes,
            removed_entries=removed_entries,
            removed_bytes=removed_bytes,
            failed_paths=tuple([*failed_paths, *after.failed_paths]),
        )
    for _mtime, size, payload_path, meta_path in sorted(entries):
        if _unlink_report(payload_path, failed_paths):
            removed_entries += 1
            removed_bytes += size
        _unlink_report(meta_path, failed_paths)
        total_bytes -= size
        if total_bytes <= max_bytes:
            break
    after = summarize_fbx_payload_cache(cache_root=root)
    return FbxPayloadCacheSummary(
        entry_count=after.entry_count,
        total_bytes=after.total_bytes,
        removed_entries=removed_entries,
        removed_bytes=removed_bytes,
        failed_paths=tuple([*failed_paths, *after.failed_paths]),
    )


def _cache_paths(
    fbx_path: str,
    options: FbxPayloadCacheOptions,
    *,
    cache_root: Path | None,
) -> tuple[Path | None, Path | None]:
    try:
        key = _cache_key(fbx_path, options)
    except OSError:
        return None, None
    root = cache_root or _default_fbx_cache_root()
    payload_path = root / f"{key}{_PAYLOAD_SUFFIX}"
    return payload_path, root / f"{key}{_META_SUFFIX}"


def _cache_key(fbx_path: str, options: FbxPayloadCacheOptions) -> str:
    metadata = _metadata_for(fbx_path, options)
    encoded = json.dumps(metadata, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _metadata_for(fbx_path: str, options: FbxPayloadCacheOptions) -> dict[str, object]:
    path = Path(fbx_path).expanduser().resolve()
    stat = path.stat()
    return {
        "schema_version": FBX_PAYLOAD_CACHE_SCHEMA_VERSION,
        "fbx_path": str(path),
        "fbx_size": stat.st_size,
        "fbx_mtime_ns": stat.st_mtime_ns,
        "read_vertex_colors": options.read_vertex_colors,
        "read_material_slots": options.read_material_slots,
        "strict_vertex_colors": options.strict_vertex_colors,
    }


def _default_fbx_cache_root() -> Path:
    return resolve_runtime_paths().cache_root / "fbx-payloads"


def _write_geometry_payload_json(path: Path, payload: GeometryBuffer) -> None:
    path.write_text(json.dumps(_geometry_payload_to_json(payload), separators=(",", ":")), encoding="utf-8")


def _read_geometry_payload_json(path: Path) -> GeometryBuffer:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("payload_type") != "GeometryBuffer":
        raise TypeError("FBX payload cache entry must contain a GeometryBuffer payload.")
    return GeometryBuffer(
        name=str(raw["name"]),
        point_components=_array_from_json(raw["point_components"], "f"),
        face_vertex_counts=_array_from_json(raw["face_vertex_counts"], "i"),
        face_vertex_indices=_array_from_json(raw["face_vertex_indices"], "i"),
        uv_components=_array_from_json(raw.get("uv_components", _array_to_json(array("f"))), "f"),
        secondary_uv_components=_array_from_json(
            raw.get("secondary_uv_components", _array_to_json(array("f"))),
            "f",
        ),
        vertex_color_components=_array_from_json(raw.get("vertex_color_components", _array_to_json(array("f"))), "f"),
        vertex_color_warning=raw.get("vertex_color_warning"),
        fbx_material_slots=tuple(
            FbxMaterialSlotSpec(
                source_id=int(slot["source_id"]),
                name=str(slot["name"]),
                face_count=int(slot.get("face_count", 0)),
            )
            for slot in _object_list(raw.get("fbx_material_slots", []), "fbx_material_slots")
        ),
        sections=tuple(
            CompactMeshSection(
                material_id=int(section["material_id"]),
                face_indices=_array_from_json(section["face_indices"], "i"),
            )
            for section in _object_list(raw.get("sections", []), "sections")
        ),
        skel_joint_indices=_array_from_json(raw.get("skel_joint_indices", _array_to_json(array("i"))), "i"),
        skel_joint_weights=_array_from_json(raw.get("skel_joint_weights", _array_to_json(array("f"))), "f"),
        skel_element_size=int(raw.get("skel_element_size", 0)),
    )


def _geometry_payload_to_json(payload: GeometryBuffer) -> dict[str, object]:
    return {
        "payload_type": "GeometryBuffer",
        "name": payload.name,
        "point_components": _array_to_json(payload.point_components),
        "face_vertex_counts": _array_to_json(payload.face_vertex_counts),
        "face_vertex_indices": _array_to_json(payload.face_vertex_indices),
        "uv_components": _array_to_json(payload.uv_components),
        "secondary_uv_components": _array_to_json(payload.secondary_uv_components),
        "vertex_color_components": _array_to_json(payload.vertex_color_components),
        "vertex_color_warning": payload.vertex_color_warning,
        "fbx_material_slots": [
            {"source_id": slot.source_id, "name": slot.name, "face_count": slot.face_count}
            for slot in payload.fbx_material_slots
        ],
        "sections": [
            {"material_id": section.material_id, "face_indices": _array_to_json(section.face_indices)}
            for section in payload.sections
        ],
        "skel_joint_indices": _array_to_json(payload.skel_joint_indices),
        "skel_joint_weights": _array_to_json(payload.skel_joint_weights),
        "skel_element_size": payload.skel_element_size,
    }


def _array_to_json(values: array) -> dict[str, str]:
    return {
        "typecode": values.typecode,
        "data": b64encode(values.tobytes()).decode("ascii"),
    }


def _array_from_json(raw: object, expected_typecode: str) -> array:
    if not isinstance(raw, dict) or raw.get("typecode") != expected_typecode:
        raise TypeError(f"FBX payload cache array must be array('{expected_typecode}').")
    values = array(expected_typecode)
    values.frombytes(b64decode(str(raw.get("data", "")).encode("ascii")))
    return values


def _object_list(raw: object, field_name: str) -> list[dict[str, object]]:
    if not isinstance(raw, list):
        raise TypeError(f"FBX payload cache {field_name} must be a list.")
    if not all(isinstance(item, dict) for item in raw):
        raise TypeError(f"FBX payload cache {field_name} entries must be objects.")
    return raw


def _iter_cache_payload_paths(root: Path) -> tuple[Path, ...]:
    return tuple(root.glob(f"*{_PAYLOAD_SUFFIX}")) + tuple(root.glob("*.pkl"))


def _meta_path_for_payload(payload_path: Path) -> Path:
    name = payload_path.name
    if name.endswith(_PAYLOAD_SUFFIX):
        return payload_path.with_name(f"{name[:-len(_PAYLOAD_SUFFIX)]}{_META_SUFFIX}")
    return payload_path.with_suffix(".json")


def _is_cacheable_source_path(fbx_path: str) -> bool:
    return Path(fbx_path).suffix.lower() == ".fbx"


def _touch_cache_files(payload_path: Path, meta_path: Path) -> None:
    now = time.time()
    try:
        os.utime(payload_path, (now, now))
        os.utime(meta_path, (now, now))
    except OSError:
        pass


def _unlink_quietly(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _payload_size_or_zero(path: Path, failed_paths: list[Path]) -> int:
    try:
        return path.stat().st_size
    except OSError:
        failed_paths.append(path)
        return 0


def _unlink_report(path: Path, failed_paths: list[Path]) -> bool:
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        failed_paths.append(path)
        return False
