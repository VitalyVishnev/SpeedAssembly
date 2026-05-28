from __future__ import annotations

import hashlib
import json
import os
import pickle
import time
from dataclasses import dataclass
from pathlib import Path

from .models import GeometryBuffer
from .runtime_paths import resolve_runtime_paths


FBX_PAYLOAD_CACHE_SCHEMA_VERSION = 1
FBX_PAYLOAD_CACHE_MAX_BYTES = 20 * 1024 * 1024 * 1024
FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60


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
        with payload_path.open("rb") as handle:
            payload = pickle.load(handle)
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
        with payload_tmp.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
        metadata = _metadata_for(fbx_path, options)
        metadata["created_at_unix"] = time.time()
        metadata["payload_bytes"] = payload_tmp.stat().st_size
        meta_tmp.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
        payload_tmp.replace(payload_path)
        meta_tmp.replace(meta_path)
        sweep_fbx_payload_cache(cache_root=root)
        return FbxPayloadCacheResult(payload, hit=False, message="cache_stored", cache_path=payload_path)
    except Exception as exc:
        _unlink_quietly(payload_tmp)
        _unlink_quietly(meta_tmp)
        return FbxPayloadCacheResult(None, hit=False, message=f"cache_write_failed: {exc}", cache_path=payload_path)


def sweep_fbx_payload_cache(
    *,
    cache_root: Path | None = None,
    max_bytes: int = FBX_PAYLOAD_CACHE_MAX_BYTES,
    max_age_seconds: int = FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS,
    now: float | None = None,
) -> None:
    root = cache_root or _default_fbx_cache_root()
    if not root.exists():
        return
    current_time = time.time() if now is None else now
    entries: list[tuple[float, int, Path, Path]] = []
    for payload_path in root.glob("*.pkl"):
        meta_path = payload_path.with_suffix(".json")
        try:
            stat = payload_path.stat()
        except OSError:
            continue
        age = current_time - stat.st_mtime
        if age > max_age_seconds:
            _unlink_quietly(payload_path)
            _unlink_quietly(meta_path)
            continue
        entries.append((stat.st_mtime, stat.st_size, payload_path, meta_path))

    total_bytes = sum(size for _mtime, size, _payload_path, _meta_path in entries)
    if total_bytes <= max_bytes:
        return
    for _mtime, size, payload_path, meta_path in sorted(entries):
        _unlink_quietly(payload_path)
        _unlink_quietly(meta_path)
        total_bytes -= size
        if total_bytes <= max_bytes:
            return


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
    payload_path = root / f"{key}.pkl"
    return payload_path, payload_path.with_suffix(".json")


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
