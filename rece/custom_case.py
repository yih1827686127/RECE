from __future__ import annotations

import json
import math
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import numpy as np

from .paths import RECE_ROOT, SCENARIOS_ROOT, ensure_rece_write, mkdir_rece, rel_to_rece, write_text_rece


CUSTOM_RUNS_ROOT = SCENARIOS_ROOT / "custom_runs"
MAX_GRID_WIDTH = 1024
MAX_GRID_HEIGHT = 1024
MAX_GRID_CELLS = 262_144
MIN_GRID_SIZE = 8
DEFAULT_WAVE_HEIGHT = 0.4
DEFAULT_WAVE_PERIOD = 10.0
DEFAULT_OUTPUT_FRAMES = 5
DEFAULT_OUTPUT_INTERVAL = 1.0
DEFAULT_REEF3D_WAVE_TYPE = 2


@dataclass(frozen=True)
class PreparedCase:
    run_id: str
    run_dir: Path
    case_dir: Path
    assets_dir: Path
    bathy_path: Path
    config_path: Path
    width: int
    height: int
    dx: float
    dy: float
    sea_level: float
    input_mode: str
    mpi_ranks: int
    output_frames: int


def normalize_params(params: Mapping[str, object] | None) -> dict[str, object]:
    raw = dict(params or {})

    def as_float(name: str, default: float, *, minimum: float | None = None) -> float:
        if name not in raw:
            return default
        try:
            value = float(raw[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric") from None
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
        if minimum is not None and value < minimum:
            raise ValueError(f"{name} must be at least {minimum}")
        return value

    def as_int(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
        if name not in raw:
            return default
        try:
            parsed = float(raw[name])
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be an integer") from None
        if not math.isfinite(parsed) or not parsed.is_integer():
            raise ValueError(f"{name} must be an integer")
        value = int(parsed)
        if value < minimum or (maximum is not None and value > maximum):
            if maximum is None:
                raise ValueError(f"{name} must be at least {minimum}")
            raise ValueError(f"{name} must be between {minimum} and {maximum}")
        return value

    return {
        "mpi_ranks": as_int("mpi_ranks", 4, minimum=1, maximum=16),
        "wave_height": as_float("wave_height", DEFAULT_WAVE_HEIGHT, minimum=0.0),
        "wave_period": as_float("wave_period", DEFAULT_WAVE_PERIOD, minimum=0.1),
        "wave_direction": as_float("wave_direction", 0.0),
        "output_frames": as_int("output_frames", DEFAULT_OUTPUT_FRAMES, minimum=1, maximum=500),
        "output_interval": as_float("output_interval", DEFAULT_OUTPUT_INTERVAL, minimum=0.01),
    }


def _read_config(path: Path) -> dict[str, object]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON config: {path.name}") from exc
    if not isinstance(config, dict):
        raise ValueError("config.json must contain a JSON object")
    return config


def _grid_from_config(config: Mapping[str, object]) -> tuple[int, int, float, float, float]:
    try:
        width = int(config["WIDTH"])
        height = int(config["HEIGHT"])
        dx = float(config["dx"])
        dy = float(config["dy"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("config.json must include numeric WIDTH, HEIGHT, dx, and dy") from exc
    sea_level = float(config.get("seaLevel", config.get("sea_level", 0.0)))
    validate_grid(width, height, dx, dy)
    return width, height, dx, dy, sea_level


def validate_grid(width: int, height: int, dx: float, dy: float) -> None:
    if width < MIN_GRID_SIZE or height < MIN_GRID_SIZE:
        raise ValueError(f"Grid must be at least {MIN_GRID_SIZE}x{MIN_GRID_SIZE}")
    if width > MAX_GRID_WIDTH or height > MAX_GRID_HEIGHT:
        raise ValueError(f"Grid {width}x{height} exceeds the {MAX_GRID_WIDTH}x{MAX_GRID_HEIGHT} RECE REEF3D axis limit")
    if width * height > MAX_GRID_CELLS:
        raise ValueError(f"Grid {width}x{height} exceeds the {MAX_GRID_CELLS} cell RECE REEF3D limit")
    if dx <= 0.0 or dy <= 0.0:
        raise ValueError("dx and dy must be positive")


def load_bathy(path: Path, width: int, height: int) -> np.ndarray:
    try:
        bathy = np.loadtxt(path, dtype=np.float32)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Could not parse bathymetry file: {path.name}") from exc
    if bathy.shape != (height, width):
        raise ValueError(f"Bathymetry shape {bathy.shape} does not match config grid {(height, width)}")
    if not np.isfinite(bathy).all():
        raise ValueError("Bathymetry contains non-finite values")
    return bathy


def infer_base_depth(config: Mapping[str, object], bathy: np.ndarray) -> float:
    try:
        base_depth = float(config.get("base_depth", 0.0))
    except (TypeError, ValueError):
        base_depth = 0.0
    if base_depth > 0.0:
        return base_depth
    wet = -bathy[bathy < 0.0]
    if wet.size == 0:
        return 1.0
    return float(np.clip(np.percentile(wet, 95), 1.0, 1000.0))


def write_geo_dat(path: Path, bathy: np.ndarray, dx: float, dy: float) -> None:
    lines: list[str] = []
    height, width = bathy.shape
    for y in range(height):
        yy = (y + 0.5) * dy
        for x in range(width):
            xx = (x + 0.5) * dx
            lines.append(f"{xx:.6f} {yy:.6f} {float(bathy[y, x]):.6f}")
    write_text_rece(path, "\n".join(lines) + "\n")


def default_waves_text(params: Mapping[str, object]) -> str:
    wave_height = float(params["wave_height"])
    wave_period = float(params["wave_period"])
    direction = float(params["wave_direction"])
    return (
        "NumberOfWaves 1\n"
        "amplitude period direction phase\n"
        f"{0.5 * wave_height:.6f} {wave_period:.6f} {direction:.6f} 0.0\n"
    )


def default_divemesh_control(
    width: int,
    height: int,
    dx: float,
    dy: float,
    bathy: np.ndarray,
    base_depth: float,
    mpi_ranks: int,
) -> str:
    lx = width * dx
    ly = height * dy
    min_z = min(float(bathy.min()) - max(dx, dy), -base_depth - max(dx, dy))
    max_z = max(float(bathy.max()) + max(dx, dy), 2.0)
    cell_size = min(dx, dy)
    return f"""C 11 6
C 12 3
C 13 3
C 14 7
C 15 21
C 16 3

B 1 {cell_size:.6f}
B 2 {width} {height} 4
B 10 0.0 {lx:.6f} 0.0 {ly:.6f} {min_z:.6f} {max_z:.6f}
B 103 5
B 113 {0.05 * cell_size:.6f}
B 116 1.0

G 9 1
G 10 1
G 15 2
G 39 1
G 51 1
G 52 {-base_depth:.6f}
G 53 {2.5 * cell_size:.6f}

M 10 {mpi_ranks}
M 20 2
"""


def default_reef3d_ctrl(
    width: int,
    dx: float,
    sea_level: float,
    base_depth: float,
    params: Mapping[str, object],
) -> str:
    lx = width * dx
    frames = int(params["output_frames"])
    output_interval = float(params["output_interval"])
    simulation_time = output_simulation_time(frames, output_interval)
    wave_height = float(params["wave_height"])
    wave_period = float(params["wave_period"])
    relax_a = max(dx, lx / 12.0)
    relax_b = max(2.0 * dx, lx / 6.0)
    p50_a = max(2.0 * dx, lx / 6.0)
    p50_b = max(4.0 * dx, lx / 3.0)
    mpi_ranks = int(params["mpi_ranks"])
    return f"""A 10 5
B 90 1
B 92 {DEFAULT_REEF3D_WAVE_TYPE}
B 93 {wave_height:.6f} {wave_period:.6f}
B 94 {base_depth:.6f}
B 96 {relax_a:.6f} {relax_b:.6f}
B 98 2
B 99 1
F 60 {sea_level:.6f}
I 12 1
N 41 {simulation_time:.6f}
N 47 1.0
M 10 {mpi_ranks}
P 10 1
P 30 1.0
P 50 {p50_a:.6f} {p50_b:.6f}
P 52 {p50_b:.6f}
P 53 1
P 55 1.0
P 180 1
P 182 {output_interval:.6f}
W 22 -9.81
"""


def output_simulation_time(frames: int, output_interval: float) -> float:
    return max(output_interval, frames * output_interval)


def external_celeris_config(
    run_id: str,
    config: Mapping[str, object],
    *,
    width: int,
    height: int,
    dx: float,
    dy: float,
    sea_level: float,
    base_depth: float,
    has_overlay: bool,
) -> dict[str, object]:
    merged = dict(config)
    merged.update(
        {
            "WIDTH": width,
            "HEIGHT": height,
            "dx": dx,
            "dy": dy,
            "seaLevel": sea_level,
            "base_depth": round(base_depth, 6),
            "run_example": -1,
            "externalSolver": "reef3d",
            "externalFrameManifest": f"/api/runs/{run_id}/manifest",
            "externalFrameStride": 1,
            "render_step": 1,
            "setRenderStep": 1,
            "useBreakingModel": 0,
            "useSedTransModel": 0,
            "ShowLogos": 1,
            "GoogleMapOverlay": 2 if has_overlay else 0,
        }
    )
    return merged


def prepare_from_celeris_files(
    run_id: str,
    uploads: Mapping[str, Path],
    params: Mapping[str, object],
    *,
    control_override: str | None = None,
    ctrl_override: str | None = None,
) -> PreparedCase:
    if "config" not in uploads or "bathy" not in uploads:
        raise ValueError("Celeris file mode requires config.json and bathy.txt")
    run_dir, case_dir, assets_dir = _fresh_run_dirs(run_id)
    config = _read_config(uploads["config"])
    width, height, dx, dy, sea_level = _grid_from_config(config)
    bathy = load_bathy(uploads["bathy"], width, height)
    base_depth = infer_base_depth(config, bathy)
    normalized = normalize_params(params)

    bathy_path = assets_dir / "bathy.txt"
    shutil.copy2(uploads["bathy"], ensure_rece_write(bathy_path))
    if "waves" in uploads:
        shutil.copy2(uploads["waves"], ensure_rece_write(assets_dir / "waves.txt"))
    else:
        write_text_rece(assets_dir / "waves.txt", default_waves_text(normalized))

    overlay_path = uploads.get("overlay")
    has_overlay = False
    if overlay_path is not None:
        suffix = overlay_path.suffix.lower() or ".png"
        shutil.copy2(overlay_path, ensure_rece_write(assets_dir / f"overlay{suffix}"))
        has_overlay = True

    out_config = external_celeris_config(
        run_id,
        config,
        width=width,
        height=height,
        dx=dx,
        dy=dy,
        sea_level=sea_level,
        base_depth=base_depth,
        has_overlay=has_overlay,
    )
    config_path = assets_dir / "config.json"
    write_text_rece(config_path, json.dumps(out_config, indent=2) + "\n")
    write_geo_dat(case_dir / "geo.dat", bathy, dx, dy)
    write_text_rece(
        case_dir / "control.txt",
        _clean_override(control_override) or default_divemesh_control(width, height, dx, dy, bathy, base_depth, int(normalized["mpi_ranks"])),
        crlf=True,
    )
    write_text_rece(
        case_dir / "ctrl.txt",
        _clean_override(ctrl_override) or default_reef3d_ctrl(width, dx, sea_level, base_depth, normalized),
        crlf=True,
    )
    validate_mpi_partition_files(case_dir, int(normalized["mpi_ranks"]))
    _write_prepare_manifest(run_id, run_dir, "celeris_files", out_config, normalized, has_overlay)
    return PreparedCase(
        run_id,
        run_dir,
        case_dir,
        assets_dir,
        bathy_path,
        config_path,
        width,
        height,
        dx,
        dy,
        sea_level,
        "celeris_files",
        int(normalized["mpi_ranks"]),
        int(normalized["output_frames"]),
    )


def safe_extract_zip(zip_path: Path, target_dir: Path) -> None:
    target_dir = mkdir_rece(target_dir)
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or name.startswith("../") or "/../" in name or name in {".", ".."}:
                raise ValueError(f"Unsafe zip member path: {info.filename}")
            if info.file_size > 100 * 1024 * 1024:
                raise ValueError(f"Zip member exceeds 100 MB limit: {info.filename}")
            destination = ensure_rece_write(target_dir / name)
            if not str(destination).startswith(str(target_dir.resolve())):
                raise ValueError(f"Unsafe zip member path: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, destination.open("wb") as dst:
                shutil.copyfileobj(src, dst)


def prepare_from_reef3d_zip(
    run_id: str,
    uploads: Mapping[str, Path],
    params: Mapping[str, object],
    *,
    control_override: str | None = None,
    ctrl_override: str | None = None,
) -> PreparedCase:
    if "reef3d_zip" not in uploads:
        raise ValueError("REEF3D zip mode requires a case zip")
    run_dir, case_dir, assets_dir = _fresh_run_dirs(run_id)
    extract_dir = mkdir_rece(run_dir / "uploaded_case")
    safe_extract_zip(uploads["reef3d_zip"], extract_dir)
    source_case = _find_case_root(extract_dir)
    _copy_tree_contents(source_case, case_dir)

    config_path_in = _find_named_file(source_case, "config.json")
    metadata_path = _find_named_file(source_case, "rece_metadata.json")
    bathy_path_in = _find_named_file(source_case, "bathy.txt")
    if bathy_path_in is None:
        raise ValueError("REEF3D zip mode requires bathy.txt for Celeris frame conversion")

    if config_path_in is not None:
        config = _read_config(config_path_in)
        width, height, dx, dy, sea_level = _grid_from_config(config)
    elif metadata_path is not None:
        metadata = _read_config(metadata_path)
        width, height, dx, dy, sea_level = _grid_from_config(metadata)
        config = {
            "WIDTH": width,
            "HEIGHT": height,
            "dx": dx,
            "dy": dy,
            "seaLevel": sea_level,
            "Courant_num": 0.2,
            "timeScheme": 2,
            "NLSW_or_Bous": 0,
            "g": 9.81,
        }
    else:
        raise ValueError("REEF3D zip mode requires config.json or rece_metadata.json")

    bathy = load_bathy(bathy_path_in, width, height)
    base_depth = infer_base_depth(config, bathy)
    normalized = normalize_params(params)
    bathy_path = assets_dir / "bathy.txt"
    shutil.copy2(bathy_path_in, ensure_rece_write(bathy_path))
    write_text_rece(assets_dir / "waves.txt", default_waves_text(normalized))

    overlay_path = _find_overlay(source_case)
    has_overlay = False
    if overlay_path is not None:
        shutil.copy2(overlay_path, ensure_rece_write(assets_dir / f"overlay{overlay_path.suffix.lower()}"))
        has_overlay = True

    if _clean_override(control_override):
        write_text_rece(case_dir / "control.txt", control_override or "", crlf=True)
    if _clean_override(ctrl_override):
        write_text_rece(case_dir / "ctrl.txt", ctrl_override or "", crlf=True)
    _apply_native_case_params(case_dir, normalized, params)
    if int(normalized["mpi_ranks"]) == 1:
        raise ValueError(
            "Native REEF3D zip cases with M 10=1 are blocked because the bundled REEF3D runtime can crash before "
            "producing frames. Use MPI ranks 2 or higher, or update both control.txt and ctrl.txt M 10 values to 2 "
            "or higher."
        )
    validate_mpi_partition_files(case_dir, int(normalized["mpi_ranks"]))

    out_config = external_celeris_config(
        run_id,
        config,
        width=width,
        height=height,
        dx=dx,
        dy=dy,
        sea_level=sea_level,
        base_depth=base_depth,
        has_overlay=has_overlay,
    )
    config_path = assets_dir / "config.json"
    write_text_rece(config_path, json.dumps(out_config, indent=2) + "\n")
    _write_prepare_manifest(run_id, run_dir, "reef3d_zip", out_config, normalized, has_overlay)
    return PreparedCase(
        run_id,
        run_dir,
        case_dir,
        assets_dir,
        bathy_path,
        config_path,
        width,
        height,
        dx,
        dy,
        sea_level,
        "reef3d_zip",
        int(normalized["mpi_ranks"]),
        int(normalized["output_frames"]),
    )


def _apply_native_case_params(case_dir: Path, normalized: dict[str, object], raw_params: Mapping[str, object]) -> None:
    raw = dict(raw_params or {})
    case_mpi_ranks = infer_case_mpi_ranks(case_dir)
    if (_truthy(raw.get("mpi_ranks_auto")) or "mpi_ranks" not in raw) and case_mpi_ranks is not None:
        normalized["mpi_ranks"] = case_mpi_ranks

    mpi_ranks = int(normalized["mpi_ranks"])
    output_interval = float(normalized["output_interval"])
    output_frames = int(normalized["output_frames"])
    simulation_time = output_simulation_time(output_frames, output_interval)

    control_path = case_dir / "control.txt"
    ctrl_path = case_dir / "ctrl.txt"
    if control_path.exists():
        control_text = _rewrite_directives(control_path.read_text(encoding="utf-8", errors="replace"), {("M", "10"): [str(mpi_ranks)]})
        write_text_rece(control_path, control_text, crlf=True)
    if ctrl_path.exists():
        ctrl_text = _rewrite_directives(
            ctrl_path.read_text(encoding="utf-8", errors="replace"),
            {
                ("B", "93"): [f"{float(normalized['wave_height']):.6f}", f"{float(normalized['wave_period']):.6f}"],
                ("N", "41"): [f"{simulation_time:.6f}"],
                ("M", "10"): [str(mpi_ranks)],
                ("P", "180"): ["1"],
                ("P", "182"): [f"{output_interval:.6f}"],
                ("P", "183"): ["-1.0"],
            },
        )
        write_text_rece(ctrl_path, ctrl_text, crlf=True)


def _rewrite_directives(text: str, updates: Mapping[tuple[str, str], list[str]]) -> str:
    normalized_updates = {(family.upper(), code): values for (family, code), values in updates.items()}
    seen: set[tuple[str, str]] = set()
    lines: list[str] = []
    for raw_line in text.splitlines():
        content = raw_line.split("#", 1)[0].strip()
        parts = content.split()
        key = (parts[0].upper(), parts[1]) if len(parts) >= 2 else None
        if key in normalized_updates:
            lines.append(f"{key[0]} {key[1]} {' '.join(normalized_updates[key])}")
            seen.add(key)
        else:
            lines.append(raw_line.rstrip())
    for key, values in normalized_updates.items():
        if key not in seen:
            lines.append(f"{key[0]} {key[1]} {' '.join(values)}")
    return "\n".join(lines).rstrip() + "\n"


def _truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "auto"}
    return bool(value)


def infer_case_mpi_ranks(case_dir: Path) -> int | None:
    values: list[tuple[str, int]] = []
    for file_name in ["control.txt", "ctrl.txt"]:
        path = case_dir / file_name
        if path.exists():
            value = read_m10_partition(path)
            if value is not None:
                values.append((file_name, value))
    if not values:
        return None
    first = values[0][1]
    mismatches = [(file_name, value) for file_name, value in values if value != first]
    if mismatches:
        details = "; ".join(f"{file_name} M 10={value}" for file_name, value in values)
        raise ValueError(f"Native REEF3D zip has inconsistent M 10 partition values: {details}")
    return first


def read_m10_partition(path: Path) -> int | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 3 and parts[0].upper() == "M" and parts[1] == "10":
            try:
                return int(float(parts[2]))
            except ValueError as exc:
                raise ValueError(f"{path.name} contains invalid M 10 value: {parts[2]}") from exc
    return None


def validate_mpi_partition_files(case_dir: Path, mpi_ranks: int) -> None:
    values: list[tuple[str, int]] = []
    for file_name in ["control.txt", "ctrl.txt"]:
        path = case_dir / file_name
        value = read_m10_partition(path)
        if value is not None:
            values.append((file_name, value))
    mismatches = [(file_name, value) for file_name, value in values if value != mpi_ranks]
    if mismatches:
        details = "; ".join(f"{file_name} M 10={value}" for file_name, value in values)
        raise ValueError(
            f"MPI ranks ({mpi_ranks}) must match the REEF3D/DIVEMesh M 10 partition value. "
            f"{details}. Change MPI ranks to match the case files or update control.txt and ctrl.txt."
        )


def _fresh_run_dirs(run_id: str) -> tuple[Path, Path, Path]:
    run_dir = mkdir_rece(CUSTOM_RUNS_ROOT / run_id)
    case_dir = mkdir_rece(run_dir / "reef3d_case")
    assets_dir = mkdir_rece(run_dir / "assets")
    mkdir_rece(run_dir / "frames")
    return run_dir, case_dir, assets_dir


def _clean_override(text: str | None) -> str | None:
    if text is None:
        return None
    cleaned = text.strip()
    return cleaned + "\n" if cleaned else None


def _copy_tree_contents(source: Path, destination: Path) -> None:
    for item in source.iterdir():
        target = ensure_rece_write(destination / item.name)
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def _find_case_root(root: Path) -> Path:
    candidates = [root, *[p for p in root.rglob("*") if p.is_dir()]]
    for candidate in candidates:
        if all((candidate / name).exists() for name in ["geo.dat", "control.txt", "ctrl.txt"]):
            return candidate
    raise ValueError("REEF3D zip must contain geo.dat, control.txt, and ctrl.txt in the same directory")


def _find_named_file(root: Path, name: str) -> Path | None:
    direct = root / name
    if direct.exists() and direct.is_file():
        return direct
    matches = [p for p in root.rglob(name) if p.is_file()]
    return matches[0] if matches else None


def _find_overlay(root: Path) -> Path | None:
    for suffix in [".jpg", ".jpeg", ".png", ".bmp", ".gif"]:
        path = _find_named_file(root, f"overlay{suffix}")
        if path is not None:
            return path
    return None


def _write_prepare_manifest(
    run_id: str,
    run_dir: Path,
    input_mode: str,
    config: Mapping[str, object],
    params: Mapping[str, object],
    has_overlay: bool,
) -> None:
    payload = {
        "run_id": run_id,
        "input_mode": input_mode,
        "paths": {
            "run_dir": rel_to_rece(run_dir),
            "case_dir": rel_to_rece(run_dir / "reef3d_case"),
            "assets_dir": rel_to_rece(run_dir / "assets"),
        },
        "grid": {
            "width": int(config["WIDTH"]),
            "height": int(config["HEIGHT"]),
            "dx": float(config["dx"]),
            "dy": float(config["dy"]),
            "sea_level": float(config.get("seaLevel", 0.0)),
        },
        "params": dict(params),
        "has_overlay": has_overlay,
    }
    write_text_rece(run_dir / "prepare_manifest.json", json.dumps(payload, indent=2) + "\n")
