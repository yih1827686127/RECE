from __future__ import annotations

import json
import math
import os
from pathlib import Path
from threading import Event
from typing import Callable

import numpy as np

from .paths import MAX_DEFAULT_LOD_CELLS, ensure_rece_write, mkdir_rece, rel_to_rece, write_text_rece


LOD_BASE_FACTORS = [1, 2, 4, 8, 16]
MAX_LOD_CACHE_CELLS = int(os.environ.get("RECE_MAX_LOD_CACHE_CELLS", "16000000"))
ProgressCallback = Callable[[dict[str, object]], None]


def lod_factors_for_grid(width: int, height: int, *, max_default_cells: int = MAX_DEFAULT_LOD_CELLS) -> tuple[list[int], int]:
    factors = list(LOD_BASE_FACTORS)
    while _cell_count(width, height, factors[-1]) > max_default_cells:
        factors.append(factors[-1] * 2)
    default = next((factor for factor in factors if _cell_count(width, height, factor) <= max_default_cells), factors[-1])
    return factors, default


def build_lod_cache(
    import_id: str,
    source_dir: Path,
    output_dir: Path,
    index: dict[str, object],
    *,
    cancel_event: Event | None = None,
    progress_callback: ProgressCallback | None = None,
    max_default_cells: int = MAX_DEFAULT_LOD_CELLS,
) -> dict[str, object]:
    from .converter import convert_reef3d_outputs

    source_dir = Path(source_dir).resolve()
    output_dir = mkdir_rece(output_dir)
    lod_root = mkdir_rece(output_dir / "lod")
    warnings: list[str] = []
    native_case = index.get("native_case") if isinstance(index.get("native_case"), dict) else {}
    grid = native_case.get("grid") if isinstance(native_case, dict) else None
    if not isinstance(grid, dict):
        warnings.append("LOD cache was not generated because source grid metadata is unavailable.")
        return _write_master_manifest(import_id, output_dir, warnings=warnings)

    case_root_rel = str(native_case.get("case_root") or ".")
    case_root = source_dir / case_root_rel
    bathy_path = case_root / "bathy.txt"
    if not bathy_path.exists():
        warnings.append("LOD cache was not generated because bathy.txt is missing.")
        return _write_master_manifest(import_id, output_dir, warnings=warnings)

    free_surface_files = [
        source_dir / str(item["relative_path"])
        for item in index.get("result_files", [])
        if isinstance(item, dict) and item.get("category") == "free_surface"
    ]
    free_surface_files = [path.resolve() for path in free_surface_files if path.exists()]
    if not free_surface_files:
        warnings.append("LOD cache was not generated because no .pvtp/.vtp free-surface files were found.")
        return _write_master_manifest(import_id, output_dir, warnings=warnings)

    width = int(grid["width"])
    height = int(grid["height"])
    dx = float(grid["dx"])
    dy = float(grid["dy"])
    sea_level = float(grid.get("sea_level", 0.0))
    factors, default_factor = lod_factors_for_grid(width, height, max_default_cells=max_default_cells)
    cache_factors = [factor for factor in factors if _cell_count(width, height, factor) <= MAX_LOD_CACHE_CELLS]
    if not cache_factors:
        cache_factors = [default_factor]
    skipped = [factor for factor in factors if factor not in cache_factors]
    if skipped:
        warnings.append(
            "Skipped fine LOD cache factor(s) "
            + ", ".join(str(factor) for factor in skipped)
            + f" because they exceed {MAX_LOD_CACHE_CELLS} visualization cells."
        )
    source_grid = {
        "width": width,
        "height": height,
        "dx": dx,
        "dy": dy,
        "sea_level": sea_level,
        "cell_count": width * height,
    }

    if progress_callback:
        progress_callback({"phase": "lod_loading_bathy", "progress": 0.32})
    if cancel_event is not None and cancel_event.is_set():
        raise InterruptedError("import cancelled")
    bathy = np.loadtxt(bathy_path, dtype=np.float32)
    if bathy.shape != (height, width):
        raise ValueError(f"bathy.txt shape {bathy.shape} does not match source grid {(height, width)}")

    levels: list[dict[str, object]] = []
    for index_factor, factor in enumerate(cache_factors):
        if cancel_event is not None and cancel_event.is_set():
            raise InterruptedError("import cancelled")
        level_dir = mkdir_rece(lod_root / f"factor_{factor}")
        frames_dir = mkdir_rece(level_dir / "frames")
        for old in frames_dir.glob("*.bin"):
            old.unlink()
        vis_width = int(math.ceil(width / factor))
        vis_height = int(math.ceil(height / factor))
        lod_bathy = bathy[::factor, ::factor]
        lod_bathy = lod_bathy[:vis_height, :vis_width]
        bathy_lod_path = ensure_rece_write(level_dir / f"bathy_lod_{factor}.txt")
        np.savetxt(bathy_lod_path, lod_bathy, fmt="%.6g")
        visualization_grid = {
            "width": vis_width,
            "height": vis_height,
            "dx": dx * factor,
            "dy": dy * factor,
            "lod_factor": factor,
            "cell_count": vis_width * vis_height,
        }
        manifest = convert_reef3d_outputs(
            case_root,
            level_dir,
            bathy_path=bathy_lod_path,
            width=vis_width,
            height=vis_height,
            dx=dx * factor,
            dy=dy * factor,
            sea_level=sea_level,
            scenario=f"local_import_{import_id}_lod_{factor}",
            source_files=free_surface_files,
            complete=True,
            allowed_source_root=source_dir,
            manifest_extras={
                "source": {
                    "kind": "raw REEF3D output",
                    "source_dir": str(source_dir),
                    "free_surface_files": len(free_surface_files),
                    "original_files_preserved": True,
                },
                "source_grid": source_grid,
                "original_grid": source_grid,
                "visualization_grid": visualization_grid,
                "lod": {
                    "factor": factor,
                    "available_factors": factors,
                    "cached_factors": cache_factors,
                    "default_factor": default_factor,
                    "is_default": factor == default_factor,
                },
                "accuracy_note": (
                    "Original REEF3D files are preserved as the scientific result source. "
                    "These Celeris frames are LOD visualization cache."
                ),
            },
        )
        levels.append(
            {
                "factor": factor,
                "is_default": factor == default_factor,
                "manifest_url": f"/api/imports/{import_id}/lod/{factor}/manifest",
                "manifest_path": rel_to_rece(level_dir / "frames_manifest.json"),
                "frames_dir": rel_to_rece(frames_dir),
                "visualization_grid": visualization_grid,
                "frame_count": int(manifest["stats"]["frame_count"]),
            }
        )
        if progress_callback:
            progress_callback(
                {
                    "phase": "lod_generating",
                    "progress": min(0.95, 0.35 + 0.6 * (index_factor + 1) / max(1, len(cache_factors))),
                    "lod_factor": factor,
                }
            )

    return _write_master_manifest(
        import_id,
        output_dir,
        source_grid=source_grid,
        lod_levels=levels,
        default_lod_factor=default_factor,
        available_factors=factors,
        cached_factors=cache_factors,
        warnings=warnings,
    )


def selected_lod_level(master_manifest: dict[str, object], factor: int | None = None) -> dict[str, object] | None:
    levels = master_manifest.get("lod_levels")
    if not isinstance(levels, list):
        return None
    if factor is None:
        factor = int(master_manifest.get("default_lod_factor") or 0)
    for level in levels:
        if isinstance(level, dict) and int(level.get("factor", -1)) == factor:
            return level
    return levels[0] if levels and isinstance(levels[0], dict) else None


def _cell_count(width: int, height: int, factor: int) -> int:
    return int(math.ceil(width / factor) * math.ceil(height / factor))


def _write_master_manifest(
    import_id: str,
    output_dir: Path,
    *,
    source_grid: dict[str, object] | None = None,
    lod_levels: list[dict[str, object]] | None = None,
    default_lod_factor: int | None = None,
    available_factors: list[int] | None = None,
    cached_factors: list[int] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, object]:
    manifest = {
        "import_id": import_id,
        "source_grid": source_grid,
        "original_grid": source_grid,
        "lod_levels": lod_levels or [],
        "default_lod_factor": default_lod_factor,
        "available_factors": available_factors or [],
        "cached_factors": cached_factors or [],
        "max_default_lod_cells": MAX_DEFAULT_LOD_CELLS,
        "warnings": warnings or [],
        "accuracy_note": (
            "Original REEF3D files are preserved without precision reduction. "
            "Celeris LOD frames are an interactive visualization cache."
        ),
    }
    write_text_rece(output_dir / "lod_manifest.json", json.dumps(manifest, indent=2) + "\n")
    return manifest
