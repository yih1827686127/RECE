from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    os.environ.setdefault("RECE_RUNTIME_MODE", "package")
    os.environ.setdefault("RECE_USER_DATA_DIR", str(Path.cwd() / "tmp" / "linux_solver_smoke_user"))

    from rece.jobs import MANAGER
    from rece.paths import RECE_ROOT, runtime_info

    root = RECE_ROOT / "tmp" / f"linux_solver_smoke_{uuid.uuid4().hex}"
    uploads_dir = root / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)

    config = {
        "WIDTH": 12,
        "HEIGHT": 10,
        "dx": 2.0,
        "dy": 2.0,
        "Courant_num": 0.2,
        "timeScheme": 2,
        "NLSW_or_Bous": 0,
        "g": 9.81,
        "seaLevel": 0.0,
        "base_depth": 4.0,
    }
    config_path = uploads_dir / "config.json"
    bathy_path = uploads_dir / "bathy.txt"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    np.savetxt(bathy_path, np.full((10, 12), -4.0, dtype=np.float32), fmt="%.3f")

    job = MANAGER.create_reef3d_job(
        input_mode="celeris_files",
        uploads={"config": config_path, "bathy": bathy_path},
        params={"output_frames": 1, "mpi_ranks": 1, "output_interval": 1.0},
    )
    smoke_run_id = str(job["id"])
    deadline = time.time() + 300
    status = job
    while time.time() < deadline:
        current = MANAGER.public_status(smoke_run_id)
        if current is not None:
            status = current
        if status.get("status") in {"complete", "failed", "cancelled"}:
            break
        time.sleep(1.0)
    else:
        MANAGER.cancel(smoke_run_id)
        raise TimeoutError("Timed out waiting for Linux REEF3D smoke job")

    result = {
        "runtime": runtime_info(),
        "job": status,
    }
    print(json.dumps(result, indent=2))
    if status.get("status") != "complete" or int(status.get("frame_count", 0)) < 1:
        raise RuntimeError(f"Linux solver smoke failed: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
