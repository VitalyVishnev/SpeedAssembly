"""Application cache maintenance.

Layer: runtime infrastructure.

This module owns disk-retention policy for converter caches. Cache producers
own their payload formats; this module owns when old payloads stop living on a
user machine.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from .fbx_payload_cache import (
    FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS,
    FBX_PAYLOAD_CACHE_MAX_BYTES,
    FbxPayloadCacheSummary,
    clear_fbx_payload_cache,
    summarize_fbx_payload_cache,
    sweep_fbx_payload_cache,
)
from .runtime_paths import DEFAULT_STALE_JOB_SECONDS, RuntimeCleanupSummary, RuntimePaths, sweep_stale_job_workspaces


SOURCE_FACTS_CACHE_MAX_BYTES = 2 * 1024 * 1024 * 1024
SOURCE_FACTS_CACHE_MAX_AGE_SECONDS = 14 * 24 * 60 * 60
_NO_SIZE_LIMIT = 2**63 - 1


@dataclass(frozen=True)
class CacheBucketSummary:
    name: str
    root: Path
    entry_count: int = 0
    total_bytes: int = 0
    removed_entries: int = 0
    removed_bytes: int = 0
    failed_paths: tuple[Path, ...] = ()

    @property
    def has_activity(self) -> bool:
        return self.removed_entries > 0 or bool(self.failed_paths)


@dataclass(frozen=True)
class CacheMaintenanceSummary:
    runtime: RuntimeCleanupSummary
    fbx: FbxPayloadCacheSummary
    source_facts: tuple[CacheBucketSummary, ...] = ()
    temp_files: CacheBucketSummary | None = None

    @property
    def entry_count(self) -> int:
        return self.fbx.entry_count + sum(bucket.entry_count for bucket in self.source_facts) + (
            self.temp_files.entry_count if self.temp_files else 0
        )

    @property
    def total_bytes(self) -> int:
        return self.fbx.total_bytes + sum(bucket.total_bytes for bucket in self.source_facts) + (
            self.temp_files.total_bytes if self.temp_files else 0
        )

    @property
    def removed_entries(self) -> int:
        return self.fbx.removed_entries + sum(bucket.removed_entries for bucket in self.source_facts) + (
            self.temp_files.removed_entries if self.temp_files else 0
        )

    @property
    def removed_bytes(self) -> int:
        return self.fbx.removed_bytes + sum(bucket.removed_bytes for bucket in self.source_facts) + (
            self.temp_files.removed_bytes if self.temp_files else 0
        )

    @property
    def failed_paths(self) -> tuple[str, ...]:
        paths: list[str] = [str(path) for path in self.fbx.failed_paths]
        for bucket in self.source_facts:
            paths.extend(str(path) for path in bucket.failed_paths)
        if self.temp_files:
            paths.extend(str(path) for path in self.temp_files.failed_paths)
        paths.extend(self.runtime.failed_paths)
        return tuple(paths)

    @property
    def has_activity(self) -> bool:
        return (
            self.runtime.has_activity
            or self.fbx.removed_entries > 0
            or bool(self.fbx.failed_paths)
            or any(bucket.has_activity for bucket in self.source_facts)
            or bool(self.temp_files and self.temp_files.has_activity)
        )


@dataclass(frozen=True)
class _CacheBucket:
    name: str
    root: Path
    suffixes: tuple[str, ...]


@dataclass(frozen=True)
class _CacheEntry:
    bucket_name: str
    path: Path
    size: int
    mtime: float


def sweep_application_cache(
    runtime_paths: RuntimePaths,
    *,
    fbx_max_bytes: int = FBX_PAYLOAD_CACHE_MAX_BYTES,
    fbx_max_age_seconds: int = FBX_PAYLOAD_CACHE_MAX_AGE_SECONDS,
    source_facts_max_bytes: int = SOURCE_FACTS_CACHE_MAX_BYTES,
    source_facts_max_age_seconds: int = SOURCE_FACTS_CACHE_MAX_AGE_SECONDS,
    runtime_stale_after_seconds: int = DEFAULT_STALE_JOB_SECONDS,
    now: float | None = None,
) -> CacheMaintenanceSummary:
    current_time = time.time() if now is None else now
    runtime = sweep_stale_job_workspaces(
        runtime_paths,
        stale_after_seconds=runtime_stale_after_seconds,
        now=current_time,
    )
    fbx = sweep_fbx_payload_cache(
        cache_root=_fbx_root(runtime_paths),
        max_bytes=max(0, int(fbx_max_bytes)),
        max_age_seconds=max(0, int(fbx_max_age_seconds)),
        now=current_time,
    )
    source_facts = _sweep_flat_cache_group(
        _source_fact_buckets(runtime_paths),
        max_bytes=max(0, int(source_facts_max_bytes)),
        max_age_seconds=max(0, int(source_facts_max_age_seconds)),
        now=current_time,
    )
    temp_files = _sweep_flat_cache_group(
        _temp_file_buckets(runtime_paths),
        max_bytes=_NO_SIZE_LIMIT,
        max_age_seconds=max(0, int(runtime_stale_after_seconds)),
        now=current_time,
    )
    return CacheMaintenanceSummary(
        runtime=runtime,
        fbx=fbx,
        source_facts=source_facts,
        temp_files=_merge_temp_summaries(temp_files),
    )


def summarize_application_cache(runtime_paths: RuntimePaths) -> CacheMaintenanceSummary:
    runtime = RuntimeCleanupSummary()
    fbx = summarize_fbx_payload_cache(cache_root=_fbx_root(runtime_paths))
    source_facts = tuple(_summarize_bucket(bucket) for bucket in _source_fact_buckets(runtime_paths))
    temp_files = _merge_temp_summaries(tuple(_summarize_bucket(bucket) for bucket in _temp_file_buckets(runtime_paths)))
    return CacheMaintenanceSummary(runtime=runtime, fbx=fbx, source_facts=source_facts, temp_files=temp_files)


def clear_application_cache(runtime_paths: RuntimePaths) -> CacheMaintenanceSummary:
    fbx = clear_fbx_payload_cache(cache_root=_fbx_root(runtime_paths))
    source_facts = _clear_flat_cache_group(_source_fact_buckets(runtime_paths))
    temp_files = _merge_temp_summaries(_clear_flat_cache_group(_temp_file_buckets(runtime_paths)))
    return CacheMaintenanceSummary(
        runtime=RuntimeCleanupSummary(),
        fbx=fbx,
        source_facts=source_facts,
        temp_files=temp_files,
    )


def _source_fact_buckets(runtime_paths: RuntimePaths) -> tuple[_CacheBucket, ...]:
    root = runtime_paths.cache_root
    return (
        _CacheBucket("source_models", root / "source_models", (".json",)),
        _CacheBucket("proxy_source_projections", root / "proxy_source_projections", (".npz",)),
        _CacheBucket("fracture_preview_source_models", root / "fracture_preview_source_models", (".npz",)),
    )


def _temp_file_buckets(runtime_paths: RuntimePaths) -> tuple[_CacheBucket, ...]:
    root = runtime_paths.cache_root
    return (
        _CacheBucket("fbx_payload_temp_files", root / "fbx-payloads", (".partial", ".tmp")),
        _CacheBucket("source_model_temp_files", root / "source_models", (".tmp",)),
        _CacheBucket("proxy_projection_temp_files", root / "proxy_source_projections", (".tmp",)),
        _CacheBucket("fracture_preview_temp_files", root / "fracture_preview_source_models", (".tmp",)),
    )


def _fbx_root(runtime_paths: RuntimePaths) -> Path:
    return runtime_paths.cache_root / "fbx-payloads"


def _sweep_flat_cache_group(
    buckets: tuple[_CacheBucket, ...],
    *,
    max_bytes: int,
    max_age_seconds: int,
    now: float,
) -> tuple[CacheBucketSummary, ...]:
    removed_counts = {bucket.name: 0 for bucket in buckets}
    removed_bytes = {bucket.name: 0 for bucket in buckets}
    failed_paths: dict[str, list[Path]] = {bucket.name: [] for bucket in buckets}
    remaining: list[_CacheEntry] = []

    for entry in _collect_entries(buckets, failed_paths):
        if now - entry.mtime > max_age_seconds:
            if _unlink_entry(entry, failed_paths):
                removed_counts[entry.bucket_name] += 1
                removed_bytes[entry.bucket_name] += entry.size
            else:
                remaining.append(entry)
            continue
        remaining.append(entry)

    total_bytes = sum(entry.size for entry in remaining)
    if total_bytes > max_bytes:
        for entry in sorted(remaining, key=lambda candidate: (candidate.mtime, str(candidate.path))):
            if total_bytes <= max_bytes:
                break
            if _unlink_entry(entry, failed_paths):
                removed_counts[entry.bucket_name] += 1
                removed_bytes[entry.bucket_name] += entry.size
                total_bytes -= entry.size

    summaries = []
    for bucket in buckets:
        current = _summarize_bucket(bucket, failed_paths=failed_paths[bucket.name])
        summaries.append(
            CacheBucketSummary(
                name=bucket.name,
                root=bucket.root,
                entry_count=current.entry_count,
                total_bytes=current.total_bytes,
                removed_entries=removed_counts[bucket.name],
                removed_bytes=removed_bytes[bucket.name],
                failed_paths=current.failed_paths,
            )
        )
    return tuple(summaries)


def _clear_flat_cache_group(buckets: tuple[_CacheBucket, ...]) -> tuple[CacheBucketSummary, ...]:
    removed_counts = {bucket.name: 0 for bucket in buckets}
    removed_bytes = {bucket.name: 0 for bucket in buckets}
    failed_paths: dict[str, list[Path]] = {bucket.name: [] for bucket in buckets}
    for entry in _collect_entries(buckets, failed_paths):
        if _unlink_entry(entry, failed_paths):
            removed_counts[entry.bucket_name] += 1
            removed_bytes[entry.bucket_name] += entry.size
    summaries = []
    for bucket in buckets:
        current = _summarize_bucket(bucket, failed_paths=failed_paths[bucket.name])
        summaries.append(
            CacheBucketSummary(
                name=bucket.name,
                root=bucket.root,
                entry_count=current.entry_count,
                total_bytes=current.total_bytes,
                removed_entries=removed_counts[bucket.name],
                removed_bytes=removed_bytes[bucket.name],
                failed_paths=current.failed_paths,
            )
        )
    return tuple(summaries)


def _collect_entries(
    buckets: tuple[_CacheBucket, ...],
    failed_paths: dict[str, list[Path]] | None = None,
) -> tuple[_CacheEntry, ...]:
    entries: list[_CacheEntry] = []
    for bucket in buckets:
        if not bucket.root.exists():
            continue
        try:
            children = tuple(bucket.root.iterdir())
        except OSError:
            if failed_paths is not None:
                failed_paths.setdefault(bucket.name, []).append(bucket.root)
            continue
        for path in children:
            if not path.is_file() or not path.name.endswith(bucket.suffixes):
                continue
            try:
                stat = path.stat()
            except OSError:
                if failed_paths is not None:
                    failed_paths.setdefault(bucket.name, []).append(path)
                continue
            entries.append(_CacheEntry(bucket.name, path, stat.st_size, stat.st_mtime))
    return tuple(entries)


def _summarize_bucket(bucket: _CacheBucket, *, failed_paths: list[Path] | None = None) -> CacheBucketSummary:
    failures = list(failed_paths or [])
    entries = _collect_entries((bucket,), {bucket.name: failures})
    return CacheBucketSummary(
        name=bucket.name,
        root=bucket.root,
        entry_count=len(entries),
        total_bytes=sum(entry.size for entry in entries),
        failed_paths=tuple(failures),
    )


def _unlink_entry(entry: _CacheEntry, failed_paths: dict[str, list[Path]]) -> bool:
    try:
        entry.path.unlink()
        return True
    except OSError:
        failed_paths.setdefault(entry.bucket_name, []).append(entry.path)
        return False


def _merge_temp_summaries(summaries: tuple[CacheBucketSummary, ...]) -> CacheBucketSummary:
    if not summaries:
        return CacheBucketSummary("cache_temp_files", Path(""))
    failed_paths: list[Path] = []
    for summary in summaries:
        failed_paths.extend(summary.failed_paths)
    return CacheBucketSummary(
        name="cache_temp_files",
        root=summaries[0].root.parent,
        entry_count=sum(summary.entry_count for summary in summaries),
        total_bytes=sum(summary.total_bytes for summary in summaries),
        removed_entries=sum(summary.removed_entries for summary in summaries),
        removed_bytes=sum(summary.removed_bytes for summary in summaries),
        failed_paths=tuple(failed_paths),
    )
