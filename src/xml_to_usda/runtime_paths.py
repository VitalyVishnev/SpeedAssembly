from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .models import CleanupPolicy, ConversionPhase


APP_NAME = "XMLtoUSDAConverter"
DEFAULT_STALE_JOB_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class RuntimePaths:
    settings_dir: Path
    settings_path: Path
    cache_root: Path
    jobs_root: Path

    def partial_output_path(self, output_path: Path) -> Path:
        return output_path.with_name(f"{output_path.name}.partial")


@dataclass(frozen=True)
class RuntimeCleanupSummary:
    removed_jobs: int = 0
    removed_partial_outputs: int = 0
    failed_jobs: int = 0
    failed_paths: tuple[str, ...] = ()

    @property
    def has_activity(self) -> bool:
        return self.removed_jobs > 0 or self.removed_partial_outputs > 0 or self.failed_jobs > 0

    def to_message(self) -> str:
        parts: list[str] = []
        if self.removed_jobs:
            parts.append(f"removed {self.removed_jobs} stale job workspace(s)")
        if self.removed_partial_outputs:
            parts.append(f"removed {self.removed_partial_outputs} stale partial USDA file(s)")
        if self.failed_jobs:
            parts.append(f"failed to remove {self.failed_jobs} stale job workspace(s)")
        return ", ".join(parts)


@dataclass
class JobWorkspace:
    runtime_paths: RuntimePaths
    job_id: str
    input_path: str
    output_path: str | None
    cleanup_policy: CleanupPolicy
    job_dir: Path
    manifest_path: Path
    runtime_context: dict[str, object]
    started_at: float = field(default_factory=time.time)
    current_phase: ConversionPhase = ConversionPhase.PREPARING

    @classmethod
    def create(
        cls,
        runtime_paths: RuntimePaths,
        *,
        input_path: str,
        output_path: str | None,
        cleanup_policy: CleanupPolicy,
    ) -> "JobWorkspace":
        _ensure_existing_directory(runtime_paths.jobs_root)
        job_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        job_dir = runtime_paths.jobs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=False)
        workspace = cls(
            runtime_paths=runtime_paths,
            job_id=job_id,
            input_path=input_path,
            output_path=output_path,
            cleanup_policy=cleanup_policy,
            job_dir=job_dir,
            manifest_path=job_dir / "job_manifest.json",
            runtime_context=capture_runtime_context(),
        )
        workspace.write_manifest(status="running")
        return workspace

    @property
    def debug_preserve(self) -> bool:
        return self.cleanup_policy == CleanupPolicy.PRESERVE_FOR_DEBUGGING

    def update_phase(self, phase: ConversionPhase) -> None:
        if phase == self.current_phase:
            return
        self.current_phase = phase
        self.write_manifest(status="running")

    def write_manifest(self, *, status: str, error_message: str | None = None) -> None:
        payload = {
            "job_id": self.job_id,
            "input_path": self.input_path,
            "output_path": self.output_path,
            "phase": self.current_phase.value,
            "status": status,
            "cleanup_policy": self.cleanup_policy.value,
            "debug_preserve": self.debug_preserve,
            "started_at_unix": self.started_at,
            "updated_at_unix": time.time(),
            "runtime_context": self.runtime_context,
        }
        if error_message:
            payload["error_message"] = error_message
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def finalize(self, *, status: str, error_message: str | None = None) -> str | None:
        warning_messages: list[str] = []
        try:
            self.write_manifest(status=status, error_message=error_message)
        except OSError as exc:
            warning_messages.append(f"Failed to update runtime job manifest {self.manifest_path}: {exc}")

        if self.output_path:
            partial_output = self.runtime_paths.partial_output_path(Path(self.output_path))
            if partial_output.exists():
                try:
                    partial_output.unlink()
                except OSError as exc:
                    warning_messages.append(f"Failed to remove partial USDA {partial_output}: {exc}")

        if not self.debug_preserve:
            try:
                shutil.rmtree(self.job_dir)
            except FileNotFoundError:
                pass
            except OSError as exc:
                warning_messages.append(f"Failed to remove runtime job directory {self.job_dir}: {exc}")

        if warning_messages:
            return " ".join(warning_messages)
        return None


def resolve_runtime_paths(
    *,
    settings_dir: Path | None = None,
    settings_path: Path | None = None,
    cache_root: Path | None = None,
) -> RuntimePaths:
    resolved_settings_dir = Path(settings_dir) if settings_dir is not None else (Path.home() / ".xml_to_usda")
    resolved_settings_path = Path(settings_path) if settings_path is not None else (resolved_settings_dir / "gui_settings.json")
    resolved_cache_root = Path(cache_root) if cache_root is not None else _resolve_default_cache_root()
    return RuntimePaths(
        settings_dir=resolved_settings_dir,
        settings_path=resolved_settings_path,
        cache_root=resolved_cache_root,
        jobs_root=resolved_cache_root / "jobs",
    )


def sweep_stale_job_workspaces(
    runtime_paths: RuntimePaths,
    *,
    stale_after_seconds: int = DEFAULT_STALE_JOB_SECONDS,
    now: float | None = None,
) -> RuntimeCleanupSummary:
    try:
        if not runtime_paths.jobs_root.exists():
            return RuntimeCleanupSummary()
    except OSError:
        return RuntimeCleanupSummary(
            failed_jobs=1,
            failed_paths=(str(runtime_paths.jobs_root),),
        )

    try:
        job_dirs = list(runtime_paths.jobs_root.iterdir())
    except OSError:
        return RuntimeCleanupSummary(
            failed_jobs=1,
            failed_paths=(str(runtime_paths.jobs_root),),
        )

    current_time = now if now is not None else time.time()
    removed_jobs = 0
    removed_partial_outputs = 0
    failed_paths: list[str] = []
    for job_dir in job_dirs:
        if not job_dir.is_dir():
            continue
        manifest_path = job_dir / "job_manifest.json"
        timestamp_source = manifest_path if manifest_path.exists() else job_dir
        try:
            age_seconds = current_time - timestamp_source.stat().st_mtime
        except OSError:
            failed_paths.append(str(job_dir))
            continue
        if age_seconds < stale_after_seconds:
            continue
        removed_partial_outputs += _remove_stale_partial_output(manifest_path, runtime_paths, failed_paths)
        try:
            shutil.rmtree(job_dir)
            removed_jobs += 1
        except OSError:
            failed_paths.append(str(job_dir))
    return RuntimeCleanupSummary(
        removed_jobs=removed_jobs,
        removed_partial_outputs=removed_partial_outputs,
        failed_jobs=len(failed_paths),
        failed_paths=tuple(failed_paths),
    )


def _default_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_NAME / "cache"
    return Path.home() / "AppData" / "Local" / APP_NAME / "cache"


def capture_runtime_context() -> dict[str, object]:
    meipass = getattr(sys, "_MEIPASS", None)
    return {
        "pid": os.getpid(),
        "ppid": os.getppid() if hasattr(os, "getppid") else None,
        "frozen": bool(getattr(sys, "frozen", False)),
        "meipass": str(meipass) if meipass else None,
        "executable": sys.executable,
        "argv0": sys.argv[0] if sys.argv else "",
        "cwd": os.getcwd(),
    }


def _resolve_default_cache_root() -> Path:
    primary_root = _default_cache_root()
    if _is_runtime_cache_root_usable(primary_root):
        return primary_root
    fallback_root = Path(tempfile.gettempdir()) / APP_NAME / "cache"
    _ensure_existing_directory(fallback_root)
    return fallback_root


def _remove_stale_partial_output(
    manifest_path: Path,
    runtime_paths: RuntimePaths,
    failed_paths: list[str],
) -> int:
    if not manifest_path.exists():
        return 0
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        failed_paths.append(str(manifest_path))
        return 0
    output_path = payload.get("output_path")
    if not output_path:
        return 0
    partial_output = runtime_paths.partial_output_path(Path(str(output_path)))
    if not partial_output.exists():
        return 0
    try:
        partial_output.unlink()
        return 1
    except OSError:
        failed_paths.append(str(partial_output))
        return 0


def _ensure_existing_directory(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        if os.path.isdir(str(path)):
            return
        raise


def _is_runtime_cache_root_usable(path: Path) -> bool:
    try:
        _ensure_existing_directory(path)
        probe_path = path / ".runtime_probe"
        probe_path.write_text("", encoding="utf-8")
        probe_path.unlink()
        return True
    except OSError:
        return False
