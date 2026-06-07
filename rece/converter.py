from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree
from vtkmodules.util.numpy_support import vtk_to_numpy
from vtkmodules.vtkIOXML import vtkXMLPPolyDataReader, vtkXMLPolyDataReader

from .paths import HK_SCENARIO, SCENARIOS_ROOT, WEB_ROOT, ensure_allowed_read, ensure_rece_write, is_under, mkdir_rece, rel_to_rece, write_text_rece


def _ensure_source_read(path: Path, allowed_source_root: Path | None = None) -> Path:
    resolved = Path(path).resolve()
    if allowed_source_root is not None and is_under(resolved, allowed_source_root):
        return resolved
    return ensure_allowed_read(resolved)


def _read_polydata(path: Path, allowed_source_root: Path | None = None):
    reader = vtkXMLPPolyDataReader() if path.suffix.lower() == ".pvtp" else vtkXMLPolyDataReader()
    reader.SetFileName(str(_ensure_source_read(path, allowed_source_root)))
    reader.Update()
    return reader.GetOutput()


def _point_array(polydata, name: str) -> np.ndarray | None:
    arr = polydata.GetPointData().GetArray(name)
    if arr is None:
        return None
    return vtk_to_numpy(arr)


def _frame_time(path: Path, index: int) -> float:
    matches = re.findall(r"(\d+(?:\.\d+)?)", path.stem)
    if not matches:
        return float(index)
    raw = float(matches[-1])
    return raw if raw < 10_000 else float(index)


def _load_bathy(path: Path, width: int, height: int, allowed_source_root: Path | None = None) -> np.ndarray:
    bathy = np.loadtxt(_ensure_source_read(path, allowed_source_root), dtype=np.float32)
    if bathy.shape == () and width == 1 and height == 1:
        bathy = bathy.reshape((1, 1))
    if bathy.shape != (height, width):
        raise RuntimeError(f"Bathymetry shape {bathy.shape} does not match {(height, width)}")
    return bathy


def _nearest_to_grid(points_xy: np.ndarray, values: np.ndarray, width: int, height: int, dx: float, dy: float) -> np.ndarray:
    grid_x = (np.arange(width, dtype=np.float32) + 0.5) * dx
    grid_y = (np.arange(height, dtype=np.float32) + 0.5) * dy
    xx, yy = np.meshgrid(grid_x, grid_y)
    tree = cKDTree(points_xy)
    _, indices = tree.query(np.column_stack([xx.ravel(), yy.ravel()]), k=1)
    return values[indices].reshape((height, width, -1))


def convert_reef3d_outputs(
    case_dir: Path,
    output_dir: Path,
    *,
    bathy_path: Path,
    width: int,
    height: int,
    dx: float,
    dy: float,
    sea_level: float = 0.0,
    scenario: str = HK_SCENARIO,
    source_files: list[Path] | None = None,
    complete: bool | None = None,
    allowed_source_root: Path | None = None,
    manifest_extras: dict[str, object] | None = None,
) -> dict[str, object]:
    case_dir = _ensure_source_read(case_dir, allowed_source_root)
    output_dir = mkdir_rece(output_dir)
    frames_dir = mkdir_rece(output_dir / "frames")
    bathy = _load_bathy(bathy_path, width, height, allowed_source_root)

    if source_files is None:
        fsf_dir = case_dir / "REEF3D_NHFLOW_VTP_FSF"
        files = sorted(fsf_dir.glob("*.pvtp"))
        if not files:
            files = sorted(fsf_dir.glob("*.vtp"))
    else:
        files = [_ensure_source_read(path, allowed_source_root) for path in source_files]
    if not files:
        raise FileNotFoundError(f"No REEF3D free-surface VTP/PVTP files found under {case_dir}")

    frames: list[dict[str, object]] = []
    for index, path in enumerate(files):
        poly = _read_polydata(path, allowed_source_root)
        points = vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float32)
        if points.size == 0:
            raise RuntimeError(f"Frame has no points: {path}")
        eta = _point_array(poly, "eta")
        if eta is None:
            eta = points[:, 2] - sea_level
        eta = np.asarray(eta, dtype=np.float32).reshape((-1, 1))
        velocity = _point_array(poly, "velocity")
        if velocity is None:
            velocity = np.zeros((points.shape[0], 3), dtype=np.float32)
        velocity = np.asarray(velocity, dtype=np.float32)
        breaking = _point_array(poly, "breaking")
        if breaking is None:
            breaking = np.zeros((points.shape[0], 1), dtype=np.float32)
        breaking = np.asarray(breaking, dtype=np.float32).reshape((-1, 1))

        values = np.column_stack([eta[:, 0], velocity[:, 0], velocity[:, 1], breaking[:, 0]])
        grid = _nearest_to_grid(points[:, :2], values.astype(np.float32), width, height, dx, dy)
        eta_abs = sea_level + grid[..., 0]
        u = grid[..., 1]
        v = grid[..., 2]
        foam = np.clip(grid[..., 3], 0.0, 1.0)
        depth = np.maximum(eta_abs - bathy, 0.0)
        state = np.stack([eta_abs, depth * u, depth * v, foam], axis=-1).astype("<f4")
        vel = np.stack([u, v, eta_abs, depth], axis=-1).astype("<f4")

        if not np.isfinite(state).all() or not np.isfinite(vel).all():
            raise RuntimeError(f"Non-finite values found while converting {path}")

        state_name = f"state_{index:06d}.bin"
        velocity_name = f"velocity_{index:06d}.bin"
        state.tofile(ensure_rece_write(frames_dir / state_name))
        vel.tofile(ensure_rece_write(frames_dir / velocity_name))
        frames.append(
            {
                "index": index,
                "time": _frame_time(path, index),
                "state": f"frames/{state_name}",
                "velocity": f"frames/{velocity_name}",
                "source": path.name,
            }
        )

    manifest = {
        "scenario": scenario,
        "width": width,
        "height": height,
        "dx": dx,
        "dy": dy,
        "sea_level": sea_level,
        "origin_hk1980": {"easting": 832000.0, "northing": 816000.0},
        "state_format": "little-endian float32 rgba row-major [eta, hu, hv, foam]",
        "velocity_format": "little-endian float32 rgba row-major [u, v, eta, depth]",
        "frames": frames,
        "paths": {"output_dir": rel_to_rece(output_dir), "frames_dir": rel_to_rece(frames_dir)},
        "stats": {
            "frame_count": len(frames),
            "bathy_min": float(bathy.min()),
            "bathy_max": float(bathy.max()),
        },
    }
    if complete is not None:
        manifest["complete"] = bool(complete)
    if manifest_extras:
        manifest.update(manifest_extras)
    _write_manifest_atomic(output_dir / "frames_manifest.json", manifest)
    if scenario == HK_SCENARIO:
        web_manifest = WEB_ROOT / "examples" / scenario / "frames_manifest.json"
        _write_manifest_atomic(web_manifest, manifest)
    return manifest


def _write_manifest_atomic(path: Path, manifest: dict[str, object]) -> None:
    path = ensure_rece_write(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(manifest, indent=2) + "\n"
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as tmp:
        tmp.write(body)
        tmp_path = Path(tmp.name)
    ensure_rece_write(tmp_path).replace(path)


def convert_hk_smoke() -> dict[str, object]:
    scenario_dir = SCENARIOS_ROOT / HK_SCENARIO
    prep = json.loads((scenario_dir / "prepare_manifest.json").read_text(encoding="utf-8"))
    grid = prep["grid"]
    return convert_reef3d_outputs(
        scenario_dir / "reef3d_case",
        scenario_dir,
        bathy_path=scenario_dir / "bathy.txt",
        width=int(grid["width"]),
        height=int(grid["height"]),
        dx=float(grid["dx"]),
        dy=float(grid["dy"]),
        sea_level=float(grid["sea_level"]),
        scenario=HK_SCENARIO,
    )
