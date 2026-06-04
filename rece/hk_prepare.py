from __future__ import annotations

import hashlib
import json
import math
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.request import urlopen

import numpy as np
from PIL import Image, ImageDraw
from scipy.spatial import cKDTree

from .paths import (
    DATA_ROOT,
    HK_SCENARIO,
    RECE_ROOT,
    SCENARIOS_ROOT,
    WEB_ROOT,
    ensure_allowed_read,
    ensure_rece_write,
    mkdir_rece,
    rel_to_rece,
    write_text_rece,
)


FULL_MIN_E = 832_000.0
FULL_MAX_E = 838_000.0
FULL_MIN_N = 816_000.0
FULL_MAX_N = 820_000.0
FULL_WIDTH = 600
FULL_HEIGHT = 400
FULL_DX = 10.0
FULL_DY = 10.0
SMOKE_SCALE = 5
SMOKE_WIDTH = FULL_WIDTH // SMOKE_SCALE
SMOKE_HEIGHT = FULL_HEIGHT // SMOKE_SCALE
SMOKE_DX = FULL_DX * SMOKE_SCALE
SMOKE_DY = FULL_DY * SMOKE_SCALE
SEA_LEVEL = 0.0


@dataclass(frozen=True)
class Tile:
    tile_name: str
    filename: str
    url: str
    center_e: float
    center_n: float
    sort_distance: float


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def find_one(pattern: str) -> Path:
    matches = sorted(DATA_ROOT.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected one file matching {pattern!r} in {DATA_ROOT}, found {len(matches)}")
    return ensure_allowed_read(matches[0])


def parse_tile_center(filename: str) -> tuple[float, float] | None:
    match = re.search(r"e(\d+)n(\d+),e(\d+)n(\d+)", filename, flags=re.IGNORECASE)
    if not match:
        return None
    e1, n1, e2, n2 = (float(value) * 1000.0 for value in match.groups())
    center_e = (e1 + e2) / 2.0
    center_n = (n1 + n2) / 2.0
    if e1 == e2:
        center_e = e1 + 250.0
    if n1 == n2:
        center_n = n1 + 250.0
    return center_e, center_n


def select_dtm_tiles(geojson_path: Path, max_tiles: int | None = None) -> list[Tile]:
    with ensure_allowed_read(geojson_path).open("r", encoding="utf-8") as f:
        geojson = json.load(f)
    domain_center_e = 0.5 * (FULL_MIN_E + FULL_MAX_E)
    domain_center_n = 0.5 * (FULL_MIN_N + FULL_MAX_N)
    tiles: list[Tile] = []
    for feature in geojson.get("features", []):
        props = feature.get("properties", {})
        filename = str(props.get("FILENAME", ""))
        center = parse_tile_center(filename)
        if center is None:
            continue
        center_e, center_n = center
        if FULL_MIN_E <= center_e < FULL_MAX_E and FULL_MIN_N <= center_n < FULL_MAX_N:
            tiles.append(
                Tile(
                    tile_name=str(props.get("TILE_NAME", "")),
                    filename=filename,
                    url=str(props.get("URL", "")),
                    center_e=center_e,
                    center_n=center_n,
                    sort_distance=math.hypot(center_e - domain_center_e, center_n - domain_center_n),
                )
            )
    tiles.sort(key=lambda tile: tile.sort_distance)
    selected = tiles[:max_tiles] if max_tiles else tiles
    if not selected:
        raise RuntimeError("No DTM tiles selected from the GeoJSON index for the smoke domain")
    return selected


def full_grid_centers() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    x_centers = FULL_MIN_E + (np.arange(FULL_WIDTH, dtype=np.float32) + 0.5) * FULL_DX
    y_centers = FULL_MIN_N + (np.arange(FULL_HEIGHT, dtype=np.float32) + 0.5) * FULL_DY
    grid_x, grid_y = np.meshgrid(x_centers, y_centers)
    return x_centers, y_centers, grid_x, grid_y


def load_bathy_points(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    data = np.loadtxt(ensure_allowed_read(path), dtype=np.float32, usecols=(0, 1, 2))
    mask = (
        (data[:, 0] >= FULL_MIN_E - 100.0)
        & (data[:, 0] <= FULL_MAX_E + 100.0)
        & (data[:, 1] >= FULL_MIN_N - 100.0)
        & (data[:, 1] <= FULL_MAX_N + 100.0)
        & np.isfinite(data[:, 2])
        & (data[:, 2] > 0.0)
    )
    subset = data[mask]
    if subset.size == 0:
        raise RuntimeError("No positive-depth bathymetry points found in the smoke domain")
    return subset[:, 0], subset[:, 1], subset[:, 2]


def interpolate_bathymetry(point_e: np.ndarray, point_n: np.ndarray, depths: np.ndarray, grid_x: np.ndarray, grid_y: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    tree = cKDTree(np.column_stack([point_e, point_n]))
    query_points = np.column_stack([grid_x.ravel(), grid_y.ravel()])
    distances, indices = tree.query(query_points, k=1)
    water_mask = np.isfinite(distances) & (distances <= 150.0)
    bathy = np.full((FULL_HEIGHT, FULL_WIDTH), np.nan, dtype=np.float32)
    bathy.ravel()[water_mask] = -depths[indices[water_mask]]
    base_depth = float(np.clip(np.percentile(depths, 95), 5.0, 60.0))
    bathy = np.where(np.isfinite(bathy), bathy, -base_depth).astype(np.float32)
    return bathy, water_mask.reshape((FULL_HEIGHT, FULL_WIDTH)), base_depth


def geotiff_metadata(image: Image.Image) -> tuple[float, float, float, float, float | None]:
    tags = image.tag_v2
    pixel_scale = tags.get(33550)
    tiepoint = tags.get(33922)
    nodata_raw = tags.get(42113)
    if not pixel_scale or not tiepoint:
        raise RuntimeError("GeoTIFF is missing ModelPixelScale or ModelTiepoint tags")
    nodata = None
    if nodata_raw is not None:
        try:
            nodata = float(str(nodata_raw).strip())
        except ValueError:
            nodata = None
    return float(pixel_scale[0]), float(pixel_scale[1]), float(tiepoint[3]), float(tiepoint[4]), nodata


def cached_or_downloaded_tifs(tiles: list[Tile], scenario_dir: Path) -> list[Path]:
    existing = sorted((DATA_ROOT / "celeris_hk_demo" / "extracted").glob("*.tif"))
    existing_by_name = {path.name.lower(): ensure_allowed_read(path) for path in existing}
    download_dir = mkdir_rece(scenario_dir / "downloads")
    extract_dir = mkdir_rece(scenario_dir / "extracted")
    tif_paths: list[Path] = []
    for tile in tiles:
        tif_name = Path(tile.filename).with_suffix(".tif").name
        if tif_name.lower() in existing_by_name:
            tif_paths.append(existing_by_name[tif_name.lower()])
            continue
        zip_path = download_dir / Path(tile.filename).with_suffix(".zip").name
        if not zip_path.exists():
            if not tile.url:
                raise RuntimeError(f"DTM tile {tile.filename} has no download URL")
            with urlopen(tile.url, timeout=120) as response, ensure_rece_write(zip_path).open("wb") as f:
                shutil.copyfileobj(response, f, length=1024 * 1024)
        with zipfile.ZipFile(zip_path, "r") as zf:
            tif_members = [name for name in zf.namelist() if name.lower().endswith(".tif")]
            if not tif_members:
                raise RuntimeError(f"No GeoTIFF found in {zip_path}")
            member = tif_members[0]
            out_path = ensure_rece_write(extract_dir / Path(member).name)
            with zf.open(member, "r") as src, out_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
            tif_paths.append(out_path)
    return tif_paths


def merge_dtm(bathy: np.ndarray, x_centers: np.ndarray, y_centers: np.ndarray, tif_paths: list[Path]) -> tuple[np.ndarray, np.ndarray, list[dict[str, object]]]:
    land_mask = np.zeros_like(bathy, dtype=bool)
    records: list[dict[str, object]] = []
    for tif_path in tif_paths:
        with Image.open(ensure_allowed_read(tif_path)) as image:
            arr = np.array(image, dtype=np.float32)
            scale_x, scale_y, tie_x, tie_y, nodata = geotiff_metadata(image)
        height, width = arr.shape
        min_x = tie_x
        max_x = tie_x + width * scale_x
        min_y = tie_y - height * scale_y
        max_y = tie_y
        x_idx = np.where((x_centers >= min_x) & (x_centers < max_x))[0]
        y_idx = np.where((y_centers >= min_y) & (y_centers < max_y))[0]
        if len(x_idx) == 0 or len(y_idx) == 0:
            records.append({"tif": tif_path.name, "used_cells": 0})
            continue
        cols = np.floor((x_centers[x_idx] - tie_x) / scale_x).astype(np.int64)
        rows = np.floor((tie_y - y_centers[y_idx]) / scale_y).astype(np.int64)
        valid_cols = (cols >= 0) & (cols < width)
        valid_rows = (rows >= 0) & (rows < height)
        cols = cols[valid_cols]
        rows = rows[valid_rows]
        x_idx = x_idx[valid_cols]
        y_idx = y_idx[valid_rows]
        sampled = arr[np.ix_(rows, cols)]
        valid = np.isfinite(sampled)
        if nodata is not None:
            valid &= sampled != nodata
        valid &= sampled > -1000.0
        merged = np.maximum(sampled, 0.5)
        sub = bathy[np.ix_(y_idx, x_idx)]
        sub_land = land_mask[np.ix_(y_idx, x_idx)]
        sub[valid] = merged[valid]
        sub_land[valid] = True
        bathy[np.ix_(y_idx, x_idx)] = sub
        land_mask[np.ix_(y_idx, x_idx)] = sub_land
        records.append({"tif": tif_path.name, "used_cells": int(valid.sum())})
    return bathy, land_mask, records


def load_or_build_full_bathy(scenario_dir: Path) -> tuple[np.ndarray, np.ndarray, float, dict[str, object]]:
    cached = DATA_ROOT / "celeris_hk_demo" / "hk_victoria_demo_bathy.txt"
    if cached.exists():
        grid = np.loadtxt(ensure_allowed_read(cached), dtype=np.float32)
        if grid.shape != (FULL_HEIGHT, FULL_WIDTH):
            raise RuntimeError(f"Cached HK bathy has shape {grid.shape}, expected {(FULL_HEIGHT, FULL_WIDTH)}")
        land_mask = grid > 0.0
        water = -grid[grid < 0.0]
        base_depth = float(np.clip(np.percentile(water, 95), 5.0, 60.0))
        return grid, land_mask, base_depth, {"full_bathy_source": str(cached), "full_bathy_sha256": sha256_file(cached)}

    source_bathy = find_one("GeoENC_all_b_withlabel*84*.txt")
    source_geojson = find_one("Hong_Kong_Digital_Terrain_Model_from_2020_LiDAR_Survey_*.geojson")
    x_centers, y_centers, grid_x, grid_y = full_grid_centers()
    point_e, point_n, depths = load_bathy_points(source_bathy)
    bathy, water_mask, base_depth = interpolate_bathymetry(point_e, point_n, depths, grid_x, grid_y)
    tiles = select_dtm_tiles(source_geojson)
    tif_paths = cached_or_downloaded_tifs(tiles, scenario_dir)
    bathy, land_mask, tile_records = merge_dtm(bathy, x_centers, y_centers, tif_paths)
    return bathy, land_mask, base_depth, {
        "full_bathy_source": "rebuilt_from_raw_sources",
        "bathymetry_points": str(source_bathy),
        "dtm_tile_index": str(source_geojson),
        "dtm_tiles": len(tiles),
        "tile_records": tile_records,
        "raw_water_cells": int(water_mask.sum()),
    }


def downsample_for_smoke(full_bathy: np.ndarray, full_land_mask: np.ndarray, base_depth: float) -> tuple[np.ndarray, np.ndarray]:
    blocks = full_bathy.reshape(SMOKE_HEIGHT, SMOKE_SCALE, SMOKE_WIDTH, SMOKE_SCALE)
    land_blocks = full_land_mask.reshape(SMOKE_HEIGHT, SMOKE_SCALE, SMOKE_WIDTH, SMOKE_SCALE)
    smoke = np.empty((SMOKE_HEIGHT, SMOKE_WIDTH), dtype=np.float32)
    smoke_land = np.zeros((SMOKE_HEIGHT, SMOKE_WIDTH), dtype=bool)
    for y in range(SMOKE_HEIGHT):
        for x in range(SMOKE_WIDTH):
            block = blocks[y, :, x, :].reshape(-1)
            land = land_blocks[y, :, x, :].reshape(-1)
            positives = block[block > 0.0]
            negatives = block[block <= 0.0]
            if positives.size and land.mean() >= 0.20:
                smoke[y, x] = float(np.percentile(positives, 75))
                smoke_land[y, x] = True
            elif negatives.size:
                smoke[y, x] = float(np.mean(negatives))
            else:
                smoke[y, x] = -base_depth
    smoke[:, :2] = np.minimum(smoke[:, :2], -base_depth)
    smoke_land[:, :2] = False
    smoke = np.clip(smoke, -35.0, 8.0).astype(np.float32)
    return smoke, smoke_land


def write_bathy(path: Path, bathy: np.ndarray) -> None:
    lines = [" ".join(f"{float(v):.3f}" for v in row) for row in bathy]
    write_text_rece(path, "\n".join(lines) + "\n")


def write_geo_dat(path: Path, bathy: np.ndarray) -> None:
    lines: list[str] = []
    for y in range(bathy.shape[0]):
        yy = (y + 0.5) * SMOKE_DY
        for x in range(bathy.shape[1]):
            xx = (x + 0.5) * SMOKE_DX
            lines.append(f"{xx:.3f} {yy:.3f} {float(bathy[y, x]):.3f}")
    write_text_rece(path, "\n".join(lines) + "\n")


def make_overlay(path: Path, bathy: np.ndarray, land_mask: np.ndarray, base_depth: float) -> None:
    rgb = np.zeros((SMOKE_HEIGHT, SMOKE_WIDTH, 3), dtype=np.uint8)
    water_depth = np.clip(-bathy, 0.0, base_depth)
    rgb[..., 0] = np.where(bathy <= 0.0, 20, 70)
    rgb[..., 1] = np.where(bathy <= 0.0, 80 + 90 * (1.0 - water_depth / max(base_depth, 1.0)), 120)
    rgb[..., 2] = np.where(bathy <= 0.0, 150 + 70 * (water_depth / max(base_depth, 1.0)), 60)
    land_elev = np.clip(bathy, 0.0, 8.0)
    rgb[land_mask, 0] = (90 + 120 * land_elev[land_mask] / 8.0).astype(np.uint8)
    rgb[land_mask, 1] = (120 + 80 * land_elev[land_mask] / 8.0).astype(np.uint8)
    rgb[land_mask, 2] = 70
    image = Image.fromarray(rgb, mode="RGB")
    image = image.resize((SMOKE_WIDTH * 4, SMOKE_HEIGHT * 4), Image.Resampling.BILINEAR)
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, image.width - 1, image.height - 1), outline=(255, 255, 255), width=2)
    resolved = ensure_rece_write(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    image.save(resolved)


def celeris_config(base_depth: float) -> dict[str, object]:
    return {
        "WIDTH": SMOKE_WIDTH,
        "HEIGHT": SMOKE_HEIGHT,
        "dx": SMOKE_DX,
        "dy": SMOKE_DY,
        "Courant_num": 0.2,
        "timeScheme": 2,
        "NLSW_or_Bous": 0,
        "g": 9.81,
        "seaLevel": SEA_LEVEL,
        "base_depth": round(base_depth, 3),
        "friction": 0.0025,
        "useBreakingModel": 0,
        "useSedTransModel": 0,
        "west_boundary_type": 1,
        "east_boundary_type": 1,
        "south_boundary_type": 1,
        "north_boundary_type": 1,
        "BoundaryWidth": 8,
        "incident_wave_type": -1,
        "numberOfWaves": 1,
        "render_step": 1,
        "externalSolver": "reef3d",
        "externalFrameManifest": "/api/scenarios/hk_victoria_smoke/manifest",
        "externalFrameStride": 1,
        "colorVal_max": 0.8,
        "colorVal_min": -0.8,
        "surfaceToPlot": 0,
        "GoogleMapOverlay": 2,
        "GMapImageWidth": SMOKE_WIDTH * 4,
        "GMapImageHeight": SMOKE_HEIGHT * 4,
        "GMscaleX": 1.0,
        "GMscaleY": -1.0,
        "GMoffsetX": 0.0,
        "GMoffsetY": 1.0,
        "ShowLogos": 1,
        "ShowArrows": 1,
        "arrow_density": 1.5,
        "arrow_scale": 1.0,
        "write_eta": 1,
        "write_u": 1,
        "write_v": 1,
    }


def divemesh_control(base_depth: float) -> str:
    lx = SMOKE_WIDTH * SMOKE_DX
    ly = SMOKE_HEIGHT * SMOKE_DY
    return f"""C 11 6
C 12 3
C 13 3
C 14 7
C 15 21
C 16 3

B 1 {SMOKE_DX:.3f}
B 2 {SMOKE_WIDTH} {SMOKE_HEIGHT} 4
B 10 0.0 {lx:.3f} 0.0 {ly:.3f} -35.0 8.0
B 103 5
B 113 2.5
B 116 1.0

G 9 1
G 10 1
G 15 2
G 39 1
G 51 1
G 52 {-base_depth:.3f}
G 53 {SMOKE_DX * 2.5:.3f}

M 10 4
M 20 2
"""


def reef3d_ctrl(base_depth: float) -> str:
    return f"""A 10 5
B 90 1
B 92 5
B 93 0.4 10.0
B 94 {base_depth:.3f}
B 96 500.0 1000.0
B 98 2
B 99 1
F 60 {SEA_LEVEL:.3f}
I 12 1
N 41 5.0
N 47 1.0
M 10 4
P 10 1
P 30 1.0
P 50 1000.0 2000.0
P 52 2000.0
P 53 1
P 55 1.0
P 180 1
P 182 1.0
W 22 -9.81
"""


def prepare_hk_smoke() -> dict[str, object]:
    scenario_dir = mkdir_rece(SCENARIOS_ROOT / HK_SCENARIO)
    case_dir = mkdir_rece(scenario_dir / "reef3d_case")
    web_example_dir = mkdir_rece(WEB_ROOT / "examples" / HK_SCENARIO)
    frames_dir = mkdir_rece(scenario_dir / "frames")

    full_bathy, full_land_mask, base_depth, source_info = load_or_build_full_bathy(scenario_dir)
    bathy, land_mask = downsample_for_smoke(full_bathy, full_land_mask, base_depth)
    base_depth = float(np.clip(np.percentile(-bathy[bathy < 0.0], 95), 5.0, 35.0))

    write_bathy(web_example_dir / "bathy.txt", bathy)
    write_bathy(scenario_dir / "bathy.txt", bathy)
    write_geo_dat(case_dir / "geo.dat", bathy)
    make_overlay(web_example_dir / "overlay.jpg", bathy, land_mask, base_depth)
    write_text_rece(
        web_example_dir / "waves.txt",
        "NumberOfWaves 1\n"
        "amplitude period direction phase\n"
        "0.2 10.0 0.0 0.0\n",
    )
    write_text_rece(web_example_dir / "config.json", json.dumps(celeris_config(base_depth), indent=2) + "\n")
    write_text_rece(case_dir / "control.txt", divemesh_control(base_depth), crlf=True)
    write_text_rece(case_dir / "ctrl.txt", reef3d_ctrl(base_depth), crlf=True)

    manifest = {
        "scenario": HK_SCENARIO,
        "rece_root": str(RECE_ROOT),
        "source_data_root": str(DATA_ROOT),
        "origin_hk1980": {"easting": FULL_MIN_E, "northing": FULL_MIN_N},
        "domain_hk1980": {"min_e": FULL_MIN_E, "max_e": FULL_MAX_E, "min_n": FULL_MIN_N, "max_n": FULL_MAX_N},
        "grid": {"width": SMOKE_WIDTH, "height": SMOKE_HEIGHT, "dx": SMOKE_DX, "dy": SMOKE_DY, "sea_level": SEA_LEVEL},
        "base_depth": base_depth,
        "paths": {
            "scenario_dir": rel_to_rece(scenario_dir),
            "case_dir": rel_to_rece(case_dir),
            "web_example_dir": rel_to_rece(web_example_dir),
            "frames_dir": rel_to_rece(frames_dir),
        },
        "stats": {
            "bathy_min": float(bathy.min()),
            "bathy_max": float(bathy.max()),
            "bathy_mean": float(bathy.mean()),
            "land_cells": int(land_mask.sum()),
            "water_cells": int((bathy <= 0.0).sum()),
        },
        "source_info": source_info,
    }
    write_text_rece(scenario_dir / "prepare_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest
