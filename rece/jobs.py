from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Mapping

from .custom_case import (
    PreparedCase,
    prepare_from_celeris_files,
    prepare_from_reef3d_zip,
)
from .paths import DIVEMESH_BIN, LOG_ROOT, REEF3D_BIN, RESOURCE_ROOT, ensure_rece_write, mkdir_rece, rel_to_rece, require_mpiexec, write_text_rece


ACTIVE_STATUSES = {"queued", "running"}
CUSTOM_LOG_ROOT = LOG_ROOT / "custom_runs"


def _find_mpiexec() -> str:
    return require_mpiexec()


def _external_solver_env() -> dict[str, str]:
    env = os.environ.copy()
    resource_root = RESOURCE_ROOT.resolve()
    path_entries: list[str] = []
    for entry in env.get("PATH", "").split(os.pathsep):
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            path_entries.append(entry)
            continue
        if resolved == resource_root or resource_root in resolved.parents:
            continue
        path_entries.append(entry)
    env["PATH"] = os.pathsep.join(path_entries)
    return env


class JobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._jobs: dict[str, dict[str, object]] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}

    def create_reef3d_job(
        self,
        *,
        input_mode: str,
        uploads: Mapping[str, Path],
        params: Mapping[str, object],
        control_override: str | None = None,
        ctrl_override: str | None = None,
    ) -> dict[str, object]:
        self._ensure_no_active_solver()

        run_id = uuid.uuid4().hex
        if input_mode == "celeris_files":
            prepared = prepare_from_celeris_files(
                run_id,
                uploads,
                params,
                control_override=control_override,
                ctrl_override=ctrl_override,
            )
        elif input_mode == "reef3d_zip":
            prepared = prepare_from_reef3d_zip(
                run_id,
                uploads,
                params,
                control_override=control_override,
                ctrl_override=ctrl_override,
            )
        else:
            raise ValueError("input_mode must be celeris_files or reef3d_zip")

        log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
        overlay = next(prepared.assets_dir.glob("overlay*"), None)
        job = {
            "id": run_id,
            "solver": "reef3d",
            "input_mode": input_mode,
            "status": "queued",
            "phase": "queued",
            "progress": 0.0,
            "frame_count": 0,
            "mpi_ranks": prepared.mpi_ranks,
            "output_frames": prepared.output_frames,
            "status_url": f"/api/runs/{run_id}/status",
            "manifest_url": f"/api/runs/{run_id}/manifest",
            "config_url": f"/api/runs/{run_id}/assets/config.json",
            "overlay_url": f"/api/runs/{run_id}/assets/{overlay.name}" if overlay is not None else "",
            "cancel_url": f"/api/runs/{run_id}/cancel",
            "created_at": time.time(),
            "run_dir": str(prepared.run_dir),
            "case_dir": str(prepared.case_dir),
            "assets_dir": str(prepared.assets_dir),
            "logs_dir": str(log_dir),
            "logs_tail": "",
            "last_conversion_error": "",
        }
        self._write_empty_manifest(prepared, complete=False)
        with self._lock:
            self._jobs[run_id] = job
        thread = threading.Thread(target=self._run_reef3d_job, args=(prepared, prepared.mpi_ranks), daemon=True)
        thread.start()
        return self.public_status(run_id) or job

    def create_import_viewer_job(self, *, import_id: str, lod_factor: int | None = None) -> dict[str, object]:
        from .imports import IMPORT_MANAGER

        run_id = uuid.uuid4().hex
        prepared = IMPORT_MANAGER.prepare_viewer_run(import_id, run_id, lod_factor=lod_factor)
        log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
        job = {
            "id": run_id,
            "solver": "reef3d",
            "input_mode": "local_import",
            "status": "complete",
            "phase": "complete",
            "progress": 1.0,
            "frame_count": int(prepared["frame_count"]),
            "status_url": f"/api/runs/{run_id}/status",
            "manifest_url": f"/api/runs/{run_id}/manifest",
            "config_url": f"/api/runs/{run_id}/assets/config.json",
            "overlay_url": "",
            "cancel_url": "",
            "created_at": time.time(),
            "completed_at": time.time(),
            "run_dir": str(prepared["run_dir"]),
            "case_dir": "",
            "assets_dir": str(prepared["assets_dir"]),
            "logs_dir": str(log_dir),
            "frames_dir": str(prepared["frames_dir"]),
            "manifest_path": str(prepared["manifest_path"]),
            "import_id": import_id,
            "lod_factor": int(prepared["lod_factor"]),
            "lod_manifest_url": str(prepared["lod_manifest_url"]),
            "native_results_url": f"/api/imports/{import_id}/result_index",
            "source_grid": prepared.get("source_grid"),
            "visualization_grid": prepared.get("visualization_grid"),
            "logs_tail": "",
            "last_conversion_error": "",
        }
        with self._lock:
            self._jobs[run_id] = job
        return self.public_status(run_id) or job

    def create_import_solve_job(
        self,
        *,
        import_id: str,
        output_path: str,
        output_token: str,
        params: Mapping[str, object],
    ) -> dict[str, object]:
        from .imports import IMPORT_MANAGER

        self._ensure_no_active_solver()
        run_id = uuid.uuid4().hex
        prepared = IMPORT_MANAGER.prepare_solver_run(
            import_id,
            run_id,
            output_path=output_path,
            output_token=output_token,
            params=params,
        )
        log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
        job = {
            "id": run_id,
            "solver": "reef3d",
            "input_mode": "local_import_solve",
            "status": "queued",
            "phase": "queued",
            "progress": 0.0,
            "frame_count": 0,
            "mpi_ranks": prepared.mpi_ranks,
            "output_frames": prepared.output_frames,
            "status_url": f"/api/runs/{run_id}/status",
            "manifest_url": f"/api/runs/{run_id}/manifest",
            "config_url": f"/api/runs/{run_id}/assets/config.json",
            "overlay_url": "",
            "cancel_url": f"/api/runs/{run_id}/cancel",
            "created_at": time.time(),
            "run_dir": str(prepared.run_dir),
            "case_dir": str(prepared.case_dir),
            "assets_dir": str(prepared.assets_dir),
            "logs_dir": str(log_dir),
            "external_output_dir": str(prepared.external_output_dir or ""),
            "source_grid": prepared.source_grid,
            "visualization_grid": None,
            "warnings": list(prepared.warnings),
            "logs_tail": "",
            "last_conversion_error": "",
        }
        self._write_empty_manifest(prepared, complete=False)
        with self._lock:
            self._jobs[run_id] = job
        thread = threading.Thread(target=self._run_reef3d_job, args=(prepared, prepared.mpi_ranks), daemon=True)
        thread.start()
        return self.public_status(run_id) or job

    def _ensure_no_active_solver(self) -> None:
        with self._lock:
            active = [job for job in self._jobs.values() if job.get("status") in ACTIVE_STATUSES]
            if active:
                raise RuntimeError("A REEF3D job is already running. Cancel it or wait for it to finish.")

    def get_job(self, run_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(run_id)
            return dict(job) if job is not None else None

    def public_status(self, run_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            public = {
                key: value
                for key, value in job.items()
                if key not in {"run_dir", "case_dir", "assets_dir", "logs_dir", "frames_dir", "manifest_path"}
            }
            public["paths"] = {
                "run_dir": rel_to_rece(job["run_dir"]),
                "case_dir": rel_to_rece(job["case_dir"]) if job.get("case_dir") else "",
                "assets_dir": rel_to_rece(job["assets_dir"]),
                "logs_dir": rel_to_rece(job["logs_dir"]),
            }
            return public

    def cancel(self, run_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            job["cancel_requested"] = True
            job["phase"] = "cancel_requested"
            process = self._processes.get(run_id)
        if process is not None and process.poll() is None:
            process.terminate()
        return self.public_status(run_id)

    def cancel_all(self) -> None:
        with self._lock:
            run_ids = list(self._jobs)
        for run_id in run_ids:
            self.cancel(run_id)

    def _run_reef3d_job(self, prepared: PreparedCase, mpi_ranks: int) -> None:
        run_id = prepared.run_id
        try:
            if prepared.input_mode == "local_import_solve":
                self._run_local_import_solve_job(prepared, mpi_ranks)
                return
            self._update(run_id, status="running", phase="divemesh", started_at=time.time(), progress=0.05)
            self._run_process(run_id, [str(DIVEMESH_BIN)], prepared.case_dir, "divemesh", timeout=900)

            self._update(run_id, phase="reef3d", progress=0.15)
            reef_args = self._reef3d_args(mpi_ranks, prepared.input_mode)
            log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            stdout_file = (log_dir / "reef3d_stdout.log").open("w", encoding="utf-8")
            stderr_file = (log_dir / "reef3d_stderr.log").open("w", encoding="utf-8")
            process = subprocess.Popen(
                reef_args,
                cwd=prepared.case_dir,
                text=True,
                stdout=stdout_file,
                stderr=stderr_file,
                creationflags=creationflags,
                env=_external_solver_env(),
            )
            with self._lock:
                self._processes[run_id] = process
            try:
                while process.poll() is None:
                    if self._cancel_requested(run_id):
                        process.terminate()
                        self._update(run_id, status="cancelled", phase="cancelled", completed_at=time.time())
                        return
                    self._convert_available(prepared, complete=False)
                    self._update_logs_tail(run_id)
                    time.sleep(1.5)
            finally:
                stdout_file.close()
                stderr_file.close()

            return_code = process.returncode
            self._convert_available(prepared, complete=return_code == 0)
            self._update_logs_tail(run_id)
            if return_code != 0:
                raise RuntimeError(f"reef3d failed with exit code {return_code}")
            frame_count = int((self.get_job(run_id) or {}).get("frame_count", 0))
            if frame_count <= 0:
                raise RuntimeError("REEF3D completed but no free-surface frames were converted")
            if frame_count < prepared.output_frames:
                raise RuntimeError(f"REEF3D completed with {frame_count} converted frames; expected {prepared.output_frames}")
            self._update(run_id, status="complete", phase="complete", progress=1.0, completed_at=time.time())
        except InterruptedError:
            self._update_logs_tail(run_id)
            self._update(run_id, status="cancelled", phase="cancelled", completed_at=time.time())
        except Exception as exc:  # noqa: BLE001
            self._update_logs_tail(run_id)
            self._update(run_id, status="failed", phase="failed", error=str(exc), completed_at=time.time())
        finally:
            with self._lock:
                self._processes.pop(run_id, None)

    def _run_local_import_solve_job(self, prepared: PreparedCase, mpi_ranks: int) -> None:
        run_id = prepared.run_id
        self._update(run_id, status="running", phase="divemesh", started_at=time.time(), progress=0.05)
        self._run_process(run_id, [str(DIVEMESH_BIN)], prepared.case_dir, "divemesh", timeout=900)

        self._update(run_id, phase="reef3d", progress=0.15)
        reef_args = self._reef3d_args(mpi_ranks, prepared.input_mode)
        log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        stdout_file = (log_dir / "reef3d_stdout.log").open("w", encoding="utf-8")
        stderr_file = (log_dir / "reef3d_stderr.log").open("w", encoding="utf-8")
        process = subprocess.Popen(
            reef_args,
            cwd=prepared.case_dir,
            text=True,
            stdout=stdout_file,
            stderr=stderr_file,
            creationflags=creationflags,
            env=_external_solver_env(),
        )
        with self._lock:
            self._processes[run_id] = process
        try:
            while process.poll() is None:
                if self._cancel_requested(run_id):
                    process.terminate()
                    self._update(run_id, status="cancelled", phase="cancelled", completed_at=time.time())
                    return
                self._update_logs_tail(run_id)
                time.sleep(1.5)
        finally:
            stdout_file.close()
            stderr_file.close()

        return_code = process.returncode
        self._update_logs_tail(run_id)
        if return_code != 0:
            raise RuntimeError(f"reef3d failed with exit code {return_code}")
        self._finalize_local_import_lod(prepared)

    def _finalize_local_import_lod(self, prepared: PreparedCase) -> None:
        from .lod import build_lod_cache, selected_lod_level
        from .result_index import scan_reef3d_directory

        run_id = prepared.run_id
        cancel_event = threading.Event()

        def check_cancel() -> None:
            if self._cancel_requested(run_id):
                cancel_event.set()

        def scan_progress(payload: dict[str, object]) -> None:
            check_cancel()
            self._update(
                run_id,
                phase="indexing_results",
                progress=0.60,
                files_scanned=int(payload.get("files_scanned", 0)),
                bytes_scanned=int(payload.get("bytes_scanned", 0)),
                estimated_total_bytes=int(payload.get("estimated_total_bytes", 0)),
            )

        self._update(run_id, phase="indexing_results", progress=0.55)
        index = scan_reef3d_directory(prepared.case_dir, cancel_event=cancel_event, progress_callback=scan_progress)
        if cancel_event.is_set():
            raise InterruptedError("run cancelled")
        index.pop("all_files", None)
        write_text_rece(prepared.run_dir / "result_index.json", json.dumps(index, indent=2) + "\n")
        self._update(run_id, phase="lod_generating", progress=0.65)

        def lod_progress(payload: dict[str, object]) -> None:
            check_cancel()
            progress = max(0.65, float(payload.get("progress", 0.65)))
            self._update(run_id, phase=str(payload.get("phase", "lod_generating")), progress=min(0.96, progress))

        lod_manifest = build_lod_cache(
            run_id,
            prepared.case_dir,
            prepared.run_dir,
            index,
            cancel_event=cancel_event,
            progress_callback=lod_progress,
        )
        if cancel_event.is_set():
            raise InterruptedError("run cancelled")
        level = selected_lod_level(lod_manifest)
        if level is None:
            raise RuntimeError("REEF3D completed but no LOD visualization frames could be generated")
        viewer = self._prepare_lod_viewer_assets(prepared, lod_manifest, int(level["factor"]))
        self._update(
            run_id,
            status="complete",
            phase="complete",
            progress=1.0,
            frame_count=int(viewer["frame_count"]),
            lod_factor=int(viewer["lod_factor"]),
            lod_manifest_url=f"/api/runs/{run_id}/lod/manifest",
            frames_dir=str(viewer["frames_dir"]),
            manifest_path=str(viewer["manifest_path"]),
            assets_dir=str(viewer["assets_dir"]),
            source_grid=viewer.get("source_grid"),
            visualization_grid=viewer.get("visualization_grid"),
            completed_at=time.time(),
        )

    def _prepare_lod_viewer_assets(self, prepared: PreparedCase, master: dict[str, object], factor: int) -> dict[str, object]:
        import shutil

        import numpy as np

        from .lod import selected_lod_level

        level = selected_lod_level(master, factor)
        if level is None:
            raise ValueError("selected LOD factor is not available")
        level_dir = prepared.run_dir / "lod" / f"factor_{factor}"
        frame_manifest_path = level_dir / "frames_manifest.json"
        frame_manifest = json.loads(frame_manifest_path.read_text(encoding="utf-8"))
        assets_dir = mkdir_rece(prepared.assets_dir)
        bathy_src = level_dir / f"bathy_lod_{factor}.txt"
        bathy_dst = ensure_rece_write(assets_dir / "bathy.txt")
        shutil.copy2(bathy_src, bathy_dst)
        write_text_rece(assets_dir / "waves.txt", "NumberOfWaves 0\n")
        grid = frame_manifest.get("visualization_grid") or {
            "width": frame_manifest["width"],
            "height": frame_manifest["height"],
            "dx": frame_manifest["dx"],
            "dy": frame_manifest["dy"],
            "lod_factor": factor,
        }
        bathy = np.loadtxt(bathy_dst, dtype=np.float32)
        base_depth = float(np.clip(np.percentile(-bathy[bathy < 0.0], 95), 1.0, 1000.0)) if np.any(bathy < 0.0) else 1.0
        config = {
            "WIDTH": int(grid["width"]),
            "HEIGHT": int(grid["height"]),
            "dx": float(grid["dx"]),
            "dy": float(grid["dy"]),
            "seaLevel": float(frame_manifest.get("sea_level", 0.0)),
            "base_depth": base_depth,
            "run_example": -1,
            "externalSolver": "reef3d",
            "externalFrameManifest": f"/api/runs/{prepared.run_id}/manifest",
            "externalFrameStride": 1,
            "render_step": 1,
            "setRenderStep": 1,
            "useBreakingModel": 0,
            "useSedTransModel": 0,
            "ShowLogos": 1,
            "GoogleMapOverlay": 0,
            "receSourceType": "raw REEF3D output",
            "receVisualizationType": "Celeris LOD visualization cache",
            "sourceGrid": frame_manifest.get("source_grid") or frame_manifest.get("original_grid"),
            "visualizationGrid": frame_manifest.get("visualization_grid"),
            "lod": frame_manifest.get("lod"),
        }
        write_text_rece(assets_dir / "config.json", json.dumps(config, indent=2) + "\n")
        return {
            "lod_factor": factor,
            "frames_dir": level_dir / "frames",
            "manifest_path": frame_manifest_path,
            "assets_dir": assets_dir,
            "frame_count": len(frame_manifest.get("frames", [])),
            "source_grid": frame_manifest.get("source_grid") or frame_manifest.get("original_grid"),
            "visualization_grid": frame_manifest.get("visualization_grid"),
        }

    def _reef3d_args(self, mpi_ranks: int, input_mode: str = "celeris_files") -> list[str]:
        if not REEF3D_BIN.exists():
            raise FileNotFoundError(REEF3D_BIN)
        if mpi_ranks < 1:
            raise ValueError("mpi_ranks must be at least 1")
        if mpi_ranks == 1 and input_mode == "celeris_files":
            return [str(REEF3D_BIN)]
        return [_find_mpiexec(), "-n", str(mpi_ranks), str(REEF3D_BIN)]

    def _run_process(self, run_id: str, args: list[str], cwd: Path, name: str, *, timeout: int) -> None:
        if not Path(args[0]).exists():
            raise FileNotFoundError(args[0])
        log_dir = mkdir_rece(CUSTOM_LOG_ROOT / run_id)
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        proc = subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
            creationflags=creationflags,
            env=_external_solver_env(),
        )
        write_text_rece(log_dir / f"{name}_stdout.log", proc.stdout)
        write_text_rece(log_dir / f"{name}_stderr.log", proc.stderr)
        self._update_logs_tail(run_id)
        if proc.returncode != 0:
            raise RuntimeError(f"{name} failed with exit code {proc.returncode}")

    def _convert_available(self, prepared: PreparedCase, *, complete: bool) -> None:
        from .converter import convert_reef3d_outputs

        files = self._stable_fsf_files(prepared.case_dir)
        if not files:
            self._write_empty_manifest(prepared, complete=complete)
            return
        files = files[: prepared.output_frames]
        existing = int((self.get_job(prepared.run_id) or {}).get("frame_count", 0))
        if not complete and len(files) <= existing:
            return
        last_error: Exception | None = None
        for count in range(len(files), 0, -1):
            try:
                manifest = convert_reef3d_outputs(
                    prepared.case_dir,
                    prepared.run_dir,
                    bathy_path=prepared.bathy_path,
                    width=prepared.width,
                    height=prepared.height,
                    dx=prepared.dx,
                    dy=prepared.dy,
                    sea_level=prepared.sea_level,
                    scenario=f"custom_{prepared.run_id}",
                    source_files=files[:count],
                    complete=complete and count == len(files),
                )
                frame_count = int(manifest["stats"]["frame_count"])
                progress = min(0.95, 0.15 + 0.8 * max(frame_count, 1) / max(prepared.output_frames, 1))
                self._update(
                    prepared.run_id,
                    phase="converting" if not complete else "finalizing",
                    frame_count=frame_count,
                    progress=progress if not complete else 0.98,
                    last_conversion_error="",
                )
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        if last_error is not None:
            self._update(prepared.run_id, last_conversion_error=str(last_error))
            if complete:
                raise last_error

    def _stable_fsf_files(self, case_dir: Path) -> list[Path]:
        fsf_dir = case_dir / "REEF3D_NHFLOW_VTP_FSF"
        files = sorted(fsf_dir.glob("*.pvtp"))
        if not files:
            files = sorted(fsf_dir.glob("*.vtp"))
        if not files:
            return []
        sizes = {path: path.stat().st_size for path in files if path.exists()}
        time.sleep(0.15)
        stable: list[Path] = []
        for path, size in sizes.items():
            if path.exists() and path.stat().st_size == size and size > 0:
                stable.append(path)
        return stable

    def _write_empty_manifest(self, prepared: PreparedCase, *, complete: bool) -> None:
        manifest = {
            "scenario": f"custom_{prepared.run_id}",
            "width": prepared.width,
            "height": prepared.height,
            "dx": prepared.dx,
            "dy": prepared.dy,
            "sea_level": prepared.sea_level,
            "state_format": "little-endian float32 rgba row-major [eta, hu, hv, foam]",
            "velocity_format": "little-endian float32 rgba row-major [u, v, eta, depth]",
            "frames": [],
            "complete": complete,
            "paths": {
                "output_dir": rel_to_rece(prepared.run_dir),
                "frames_dir": rel_to_rece(prepared.run_dir / "frames"),
            },
            "stats": {"frame_count": 0},
        }
        write_text_rece(prepared.run_dir / "frames_manifest.json", json.dumps(manifest, indent=2) + "\n")

    def _cancel_requested(self, run_id: str) -> bool:
        with self._lock:
            return bool(self._jobs.get(run_id, {}).get("cancel_requested"))

    def _update(self, run_id: str, **updates: object) -> None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is not None:
                job.update(updates)

    def _update_logs_tail(self, run_id: str) -> None:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return
            log_dir = Path(str(job["logs_dir"]))
        chunks: list[str] = []
        for name in ["divemesh_stderr.log", "divemesh_stdout.log", "reef3d_stderr.log", "reef3d_stdout.log"]:
            path = log_dir / name
            if path.exists():
                text = path.read_text(encoding="utf-8", errors="replace")
                if text.strip():
                    chunks.append(f"--- {name} ---\n{text[-1800:]}")
        self._update(run_id, logs_tail="\n".join(chunks)[-4000:])

    def asset_path(self, run_id: str, name: str) -> Path | None:
        job = self.get_job(run_id)
        if job is None:
            return None
        path = ensure_rece_write(Path(str(job["assets_dir"])) / name)
        assets = Path(str(job["assets_dir"])).resolve()
        return path if assets == path.resolve().parent or assets in path.resolve().parents else None

    def frame_path(self, run_id: str, name: str) -> Path | None:
        job = self.get_job(run_id)
        if job is None:
            return None
        if "\x00" in name or "\\" in name:
            return None
        name = name.lstrip("/")
        if name.startswith("frames/"):
            name = name[len("frames/") :]
        parts = name.split("/")
        if any(part in {"", ".", ".."} for part in parts) or ":" in name:
            return None
        frames_root = Path(str(job.get("frames_dir") or (Path(str(job["run_dir"])) / "frames"))).resolve()
        path = ensure_rece_write(frames_root / name)
        frames = frames_root.resolve()
        return path if frames == path.resolve().parent or frames in path.resolve().parents else None

    def manifest_path(self, run_id: str) -> Path | None:
        job = self.get_job(run_id)
        if job is None:
            return None
        if job.get("manifest_path"):
            return ensure_rece_write(Path(str(job["manifest_path"])))
        return ensure_rece_write(Path(str(job["run_dir"])) / "frames_manifest.json")


MANAGER = JobManager()
