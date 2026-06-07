from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from threading import Event
from typing import Callable

from .custom_case import _read_config, infer_case_mpi_ranks


CASE_REQUIRED = {"geo.dat", "control.txt", "ctrl.txt"}
CASE_METADATA = {"config.json", "rece_metadata.json"}
CASE_AUXILIARY = {"bathy.txt", "waves.txt"}
VTK_SURFACE_SUFFIXES = {".pvtp", ".vtp"}
VTK_VOLUME_SUFFIXES = {".pvtu", ".vtu"}
LOG_HINTS = ("reef3d_log", "log-probes", "log-wave", "probe", "volume", "runup", "diagnostic")
EXCLUDED_LOG_NAMES = CASE_REQUIRED | CASE_METADATA | CASE_AUXILIARY


ProgressCallback = Callable[[dict[str, object]], None]


def file_entry(root: Path, path: Path, category: str, family: str) -> dict[str, object]:
    rel = path.relative_to(root).as_posix()
    digest = hashlib.sha256(rel.encode("utf-8")).hexdigest()[:20]
    stat = path.stat()
    return {
        "id": digest,
        "name": path.name,
        "relative_path": rel,
        "category": category,
        "family": family,
        "size_bytes": stat.st_size,
        "modified_at": stat.st_mtime,
    }


def scan_reef3d_directory(
    root: Path,
    *,
    cancel_event: Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    root = Path(root).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"Import path is not a directory: {root}")

    started = time.time()
    files_scanned = 0
    bytes_scanned = 0
    result_files: list[dict[str, object]] = []
    case_roots: dict[str, set[str]] = {}
    all_files_by_rel: dict[str, Path] = {}

    stack = [root]
    while stack:
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("import cancelled")
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            if progress_callback:
                progress_callback({"warning": f"Could not scan {current}: {exc}"})
            continue
        for entry in entries:
            if cancel_event is not None and cancel_event.is_set():
                raise InterruptedError("import cancelled")
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                stack.append(path)
                continue
            if not entry.is_file(follow_symlinks=False):
                continue
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                size = 0
            files_scanned += 1
            bytes_scanned += max(0, size)
            rel = path.relative_to(root).as_posix()
            all_files_by_rel[rel] = path
            lower_name = path.name.lower()
            lower_rel = rel.lower()
            suffix = path.suffix.lower()
            if lower_name in CASE_REQUIRED or lower_name in CASE_METADATA or lower_name in CASE_AUXILIARY:
                case_roots.setdefault(path.parent.relative_to(root).as_posix(), set()).add(lower_name)
            if suffix in VTK_SURFACE_SUFFIXES:
                result_files.append(file_entry(root, path, "free_surface", "reef3d_vtp_fsf" if "fsf" in lower_rel else "reef3d_vtp"))
            elif suffix in VTK_VOLUME_SUFFIXES:
                result_files.append(file_entry(root, path, "volume_field", "reef3d_vtu"))
            elif _looks_like_log(lower_name, lower_rel):
                result_files.append(file_entry(root, path, "diagnostic_log", _log_family(lower_rel)))
            if progress_callback and (files_scanned % 50 == 0):
                elapsed = max(0.001, time.time() - started)
                progress_callback(
                    {
                        "files_scanned": files_scanned,
                        "bytes_scanned": bytes_scanned,
                        "estimated_total_bytes": bytes_scanned,
                        "eta_seconds": None,
                        "scan_rate_files_per_second": files_scanned / elapsed,
                    }
                )

    native_case = _select_native_case(root, case_roots)
    summary = {
        "files_scanned": files_scanned,
        "bytes_scanned": bytes_scanned,
        "free_surface_files": sum(1 for item in result_files if item["category"] == "free_surface"),
        "volume_field_files": sum(1 for item in result_files if item["category"] == "volume_field"),
        "diagnostic_logs": sum(1 for item in result_files if item["category"] == "diagnostic_log"),
    }
    return {
        "source_dir": str(root),
        "summary": summary,
        "native_case": native_case,
        "result_files": sorted(result_files, key=lambda item: (str(item["category"]), str(item["relative_path"]))),
        "all_files": all_files_by_rel,
    }


def _looks_like_log(lower_name: str, lower_rel: str) -> bool:
    if lower_name in EXCLUDED_LOG_NAMES:
        return False
    if any(hint in lower_rel for hint in LOG_HINTS):
        return lower_name.endswith((".txt", ".log", ".dat", ".csv", ".out"))
    return lower_name.startswith("reef3d_log")


def _log_family(lower_rel: str) -> str:
    if "probe" in lower_rel:
        return "reef3d_log_probes"
    if "log-wave" in lower_rel or "wave" in lower_rel:
        return "reef3d_log_wave"
    if "volume" in lower_rel:
        return "reef3d_volume_log"
    if "runup" in lower_rel:
        return "reef3d_runup_log"
    return "reef3d_log"


def _select_native_case(root: Path, case_roots: dict[str, set[str]]) -> dict[str, object]:
    candidates: list[tuple[str, set[str]]] = []
    for rel, names in case_roots.items():
        if CASE_REQUIRED.issubset(names):
            candidates.append((rel, names))
    if not candidates:
        return {"recognized": False, "reason": "geo.dat, control.txt, and ctrl.txt were not found in one directory"}
    candidates.sort(key=lambda item: (0 if "bathy.txt" in item[1] and item[1].intersection(CASE_METADATA) else 1, len(item[0])))
    rel, names = candidates[0]
    case_dir = root / rel
    metadata_path = case_dir / "config.json"
    if not metadata_path.exists():
        metadata_path = case_dir / "rece_metadata.json"
    grid: dict[str, object] | None = None
    if metadata_path.exists():
        config = _read_config(metadata_path)
        width, height, dx, dy, sea_level = _grid_from_metadata(config)
        grid = {"width": width, "height": height, "dx": dx, "dy": dy, "sea_level": sea_level}
    mpi_ranks = infer_case_mpi_ranks(case_dir)
    return {
        "recognized": True,
        "case_root": rel,
        "has_bathy": "bathy.txt" in names,
        "metadata_file": metadata_path.name if metadata_path.exists() else "",
        "grid": grid,
        "mpi_ranks": mpi_ranks,
        "warnings": _case_warnings(names, grid),
    }


def _case_warnings(names: set[str], grid: dict[str, object] | None) -> list[str]:
    warnings: list[str] = []
    if "bathy.txt" not in names:
        warnings.append("Native case was recognized, but bathy.txt is missing; LOD visualization cannot be generated.")
    if not names.intersection(CASE_METADATA):
        warnings.append("Native case was recognized, but config.json or rece_metadata.json is missing; grid metadata is unavailable.")
    if grid is None:
        warnings.append("Source/original grid metadata is unavailable.")
    return warnings


def _grid_from_metadata(config: dict[str, object]) -> tuple[int, int, float, float, float]:
    try:
        width = int(config["WIDTH"])
        height = int(config["HEIGHT"])
        dx = float(config["dx"])
        dy = float(config["dy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("config.json or rece_metadata.json must include numeric WIDTH, HEIGHT, dx, and dy") from exc
    if width <= 0 or height <= 0:
        raise ValueError("WIDTH and HEIGHT must be positive")
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError("dx and dy must be positive")
    sea_level = float(config.get("seaLevel", config.get("sea_level", 0.0)))
    return width, height, dx, dy, sea_level
