from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
import uuid
from pathlib import Path
from typing import Mapping

import numpy as np

from .custom_case import PreparedCase, prepare_from_local_import_case
from .lod import build_lod_cache, selected_lod_level
from .paths import LOG_ROOT, SCENARIOS_ROOT, ensure_rece_write, is_under, local_import_supported, mkdir_rece, rel_to_rece, write_text_rece
from .result_index import scan_reef3d_directory


LOCAL_IMPORTS_ROOT = SCENARIOS_ROOT / "local_imports"
LOCAL_IMPORT_LOG_ROOT = LOG_ROOT / "local_imports"
ACTIVE_IMPORT_STATUSES = {"queued", "running"}


class LocalImportManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._imports: dict[str, dict[str, object]] = {}
        self._tokens: dict[str, Path] = {}
        self._output_tokens: dict[str, Path] = {}
        self._cancel_events: dict[str, threading.Event] = {}

    def authorize_directory(self, path: str | Path) -> dict[str, object]:
        source_dir = Path(path).resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise ValueError(f"Import path is not a directory: {source_dir}")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._tokens[token] = source_dir
        return {"path": str(source_dir), "token": token}

    def create_import_from_authorized(self, path: str | Path, token: str) -> dict[str, object]:
        source_dir = Path(path).resolve()
        with self._lock:
            authorized = self._tokens.pop(token, None)
        dev_token = os.environ.get("RECE_LOCAL_IMPORT_TOKEN", "")
        if authorized is None:
            if not (local_import_supported() and dev_token and secrets.compare_digest(token, dev_token)):
                raise PermissionError("Local import path is not authorized")
        elif authorized != source_dir:
            raise PermissionError("Local import token does not match the requested path")
        return self._create_import(source_dir, source="authorized")

    def create_desktop_import(self, path: str | Path) -> dict[str, object]:
        if not local_import_supported():
            raise PermissionError("Local directory import is only available in RECE desktop or explicit dev mode")
        source_dir = Path(path).resolve()
        if not source_dir.exists() or not source_dir.is_dir():
            raise ValueError(f"Import path is not a directory: {source_dir}")
        return self._create_import(source_dir, source="desktop")

    def authorize_output_directory(self, path: str | Path) -> dict[str, object]:
        if not local_import_supported():
            raise PermissionError("Local REEF3D run output selection is only available in RECE desktop or explicit dev mode")
        output_dir = Path(path).resolve()
        if not output_dir.exists() or not output_dir.is_dir():
            raise ValueError(f"Run output path is not a directory: {output_dir}")
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._output_tokens[token] = output_dir
        return {"path": str(output_dir), "token": token}

    def consume_output_authorization(self, path: str | Path, token: str) -> Path:
        output_dir = Path(path).resolve()
        with self._lock:
            authorized = self._output_tokens.pop(token, None)
        dev_token = os.environ.get("RECE_LOCAL_IMPORT_TOKEN", "")
        if authorized is None:
            if not (local_import_supported() and dev_token and secrets.compare_digest(token, dev_token)):
                raise PermissionError("Run output path is not authorized")
        elif authorized != output_dir:
            raise PermissionError("Run output token does not match the requested path")
        if not output_dir.exists() or not output_dir.is_dir():
            raise ValueError(f"Run output path is not a directory: {output_dir}")
        return output_dir

    def _create_import(self, source_dir: Path, *, source: str) -> dict[str, object]:
        import_id = uuid.uuid4().hex
        import_dir = mkdir_rece(LOCAL_IMPORTS_ROOT / import_id)
        log_dir = mkdir_rece(LOCAL_IMPORT_LOG_ROOT / import_id)
        cancel_event = threading.Event()
        now = time.time()
        job = {
            "id": import_id,
            "source": source,
            "status": "queued",
            "phase": "queued",
            "files_scanned": 0,
            "bytes_scanned": 0,
            "estimated_total_bytes": 0,
            "progress": 0.0,
            "eta_seconds": None,
            "warnings": [],
            "status_url": f"/api/imports/{import_id}/status",
            "cancel_url": f"/api/imports/{import_id}/cancel",
            "result_index_url": f"/api/imports/{import_id}/result_index",
            "lod_manifest_url": f"/api/imports/{import_id}/lod/manifest",
            "created_at": now,
            "started_at": None,
            "completed_at": None,
            "source_dir": str(source_dir),
            "import_dir": str(import_dir),
            "logs_dir": str(log_dir),
            "result_files_by_id": {},
        }
        with self._lock:
            self._imports[import_id] = job
            self._cancel_events[import_id] = cancel_event
        thread = threading.Thread(target=self._run_import, args=(import_id, source_dir, import_dir, cancel_event), daemon=True)
        thread.start()
        return self.public_status(import_id) or job

    def public_status(self, import_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._imports.get(import_id)
            if job is None:
                return None
            public = {
                key: value
                for key, value in job.items()
                if key not in {"source_dir", "import_dir", "logs_dir", "result_files_by_id"}
            }
            public["paths"] = {
                "import_dir": rel_to_rece(job["import_dir"]),
                "logs_dir": rel_to_rece(job["logs_dir"]),
            }
            return public

    def result_index(self, import_id: str) -> dict[str, object] | None:
        job = self.get_import(import_id)
        if job is None:
            return None
        path = Path(str(job["import_dir"])) / "result_index.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def get_import(self, import_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._imports.get(import_id)
            return dict(job) if job is not None else None

    def cancel(self, import_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._imports.get(import_id)
            cancel_event = self._cancel_events.get(import_id)
            if job is None:
                return None
            job["cancel_requested"] = True
            job["phase"] = "cancel_requested"
            if cancel_event is not None:
                cancel_event.set()
        return self.public_status(import_id)

    def manifest_path(self, import_id: str, factor: int | None = None) -> Path | None:
        job = self.get_import(import_id)
        if job is None:
            return None
        if factor is None:
            path = Path(str(job["import_dir"])) / "lod_manifest.json"
            return path if path.exists() else None
        path = Path(str(job["import_dir"])) / "lod" / f"factor_{factor}" / "frames_manifest.json"
        return path if path.exists() else None

    def file_path(self, import_id: str, file_id: str) -> Path | None:
        job = self.get_import(import_id)
        if job is None:
            return None
        mapping = job.get("result_files_by_id")
        if not isinstance(mapping, dict):
            return None
        raw = mapping.get(file_id)
        if not raw:
            return None
        path = Path(str(raw)).resolve()
        source_dir = Path(str(job["source_dir"])).resolve()
        return path if path.exists() and is_under(path, source_dir) else None

    def prepare_viewer_run(self, import_id: str, run_id: str, *, lod_factor: int | None = None) -> dict[str, object]:
        job = self.get_import(import_id)
        if job is None:
            raise ValueError("unknown import id")
        if job.get("status") != "complete":
            raise ValueError("local import is not complete")
        master_path = self.manifest_path(import_id)
        if master_path is None:
            raise ValueError("local import has no LOD manifest")
        master = json.loads(master_path.read_text(encoding="utf-8"))
        level = selected_lod_level(master, lod_factor)
        if level is None:
            raise ValueError("local import has no Celeris LOD frames")
        factor = int(level["factor"])
        level_dir = Path(str(job["import_dir"])) / "lod" / f"factor_{factor}"
        frame_manifest_path = level_dir / "frames_manifest.json"
        frame_manifest = json.loads(frame_manifest_path.read_text(encoding="utf-8"))
        assets_dir = mkdir_rece(Path(str(job["import_dir"])) / "viewer_runs" / run_id / "assets")
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
            "externalFrameManifest": f"/api/runs/{run_id}/manifest",
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
        config_path = write_text_rece(assets_dir / "config.json", json.dumps(config, indent=2) + "\n")
        return {
            "import_id": import_id,
            "lod_factor": factor,
            "run_dir": Path(str(job["import_dir"])),
            "frames_dir": level_dir / "frames",
            "manifest_path": frame_manifest_path,
            "assets_dir": assets_dir,
            "config_path": config_path,
            "bathy_path": bathy_dst,
            "frame_count": len(frame_manifest.get("frames", [])),
            "source_grid": frame_manifest.get("source_grid") or frame_manifest.get("original_grid"),
            "visualization_grid": frame_manifest.get("visualization_grid"),
            "lod_manifest_url": f"/api/imports/{import_id}/lod/manifest",
        }

    def prepare_solver_run(
        self,
        import_id: str,
        run_id: str,
        *,
        output_path: str | Path,
        output_token: str,
        params: Mapping[str, object],
    ) -> PreparedCase:
        job = self.get_import(import_id)
        if job is None:
            raise ValueError("unknown import id")
        if job.get("status") != "complete":
            raise ValueError("local import is not complete")
        result_index = job.get("result_index")
        if not isinstance(result_index, dict):
            result_index = self.result_index(import_id)
        if not isinstance(result_index, dict):
            raise ValueError("local import result index is not ready")
        native = result_index.get("native_case")
        if not isinstance(native, dict) or not native.get("recognized"):
            raise ValueError("local import does not contain a recognized native REEF3D case")
        case_root_rel = str(native.get("case_root") or ".")
        source_dir = Path(str(job["source_dir"])).resolve()
        source_case_dir = (source_dir / case_root_rel).resolve()
        if not is_under(source_case_dir, source_dir):
            raise ValueError("local import native case path is outside the authorized source directory")
        output_root = self.consume_output_authorization(output_path, output_token)
        return prepare_from_local_import_case(
            run_id,
            source_case_dir=source_case_dir,
            source_root=source_dir,
            output_root=output_root,
            params=params,
        )

    def _run_import(self, import_id: str, source_dir: Path, import_dir: Path, cancel_event: threading.Event) -> None:
        started = time.time()
        self._update(import_id, status="running", phase="scanning", started_at=started, progress=0.02)
        try:
            warnings: list[str] = []

            def progress(update: dict[str, object]) -> None:
                if "warning" in update:
                    warnings.append(str(update["warning"]))
                    self._append_warning(import_id, str(update["warning"]))
                    return
                self._update(
                    import_id,
                    phase="scanning",
                    files_scanned=int(update.get("files_scanned", 0)),
                    bytes_scanned=int(update.get("bytes_scanned", 0)),
                    estimated_total_bytes=int(update.get("estimated_total_bytes", 0)),
                    progress=0.08,
                    eta_seconds=None,
                )

            index = scan_reef3d_directory(source_dir, cancel_event=cancel_event, progress_callback=progress)
            if cancel_event.is_set():
                raise InterruptedError("import cancelled")
            summary = index.get("summary", {})
            self._update(
                import_id,
                phase="indexing_results",
                files_scanned=int(summary.get("files_scanned", 0)),
                bytes_scanned=int(summary.get("bytes_scanned", 0)),
                estimated_total_bytes=int(summary.get("bytes_scanned", 0)),
                progress=0.25,
            )
            all_files = index.pop("all_files", {})
            result_map: dict[str, str] = {}
            for item in index.get("result_files", []):
                if isinstance(item, dict):
                    path = all_files.get(str(item.get("relative_path")))
                    if path is not None:
                        result_map[str(item["id"])] = str(Path(path).resolve())
                        item["url"] = f"/api/imports/{import_id}/files/{item['id']}"
            native = index.get("native_case")
            if isinstance(native, dict):
                warnings.extend(str(warning) for warning in native.get("warnings", []) if warning)
            index["warnings"] = warnings
            write_text_rece(import_dir / "result_index.json", json.dumps(index, indent=2) + "\n")
            with self._lock:
                if import_id in self._imports:
                    self._imports[import_id]["result_files_by_id"] = result_map
                    self._imports[import_id]["result_index"] = index
                    self._imports[import_id]["warnings"] = warnings
            self._update(import_id, phase="lod_generating", progress=0.30)
            lod_manifest = build_lod_cache(
                import_id,
                source_dir,
                import_dir,
                index,
                cancel_event=cancel_event,
                progress_callback=lambda payload: self._update_import_lod_progress(import_id, payload, started),
            )
            if cancel_event.is_set():
                raise InterruptedError("import cancelled")
            self._update(
                import_id,
                status="complete",
                phase="complete",
                progress=1.0,
                eta_seconds=0,
                lod_manifest=lod_manifest,
                completed_at=time.time(),
            )
        except InterruptedError:
            self._cleanup_cancelled_import(import_dir)
            self._update(import_id, status="cancelled", phase="cancelled", progress=0.0, completed_at=time.time())
        except Exception as exc:  # noqa: BLE001
            self._update(import_id, status="failed", phase="failed", error=str(exc), completed_at=time.time())
        finally:
            with self._lock:
                self._cancel_events.pop(import_id, None)

    def _update_import_lod_progress(self, import_id: str, payload: dict[str, object], started: float) -> None:
        progress = float(payload.get("progress", 0.30))
        elapsed = max(0.001, time.time() - started)
        eta = max(0.0, elapsed * (1.0 - progress) / progress) if progress > 0 else None
        self._update(import_id, phase=str(payload.get("phase", "lod_generating")), progress=progress, eta_seconds=eta)

    def _append_warning(self, import_id: str, warning: str) -> None:
        with self._lock:
            job = self._imports.get(import_id)
            if job is None:
                return
            warnings = list(job.get("warnings") or [])
            warnings.append(warning)
            job["warnings"] = warnings

    def _cleanup_cancelled_import(self, import_dir: Path) -> None:
        resolved = Path(import_dir).resolve()
        if resolved.exists() and is_under(resolved, LOCAL_IMPORTS_ROOT):
            shutil.rmtree(resolved, ignore_errors=True)

    def _update(self, import_id: str, **updates: object) -> None:
        with self._lock:
            job = self._imports.get(import_id)
            if job is not None:
                job.update(updates)


IMPORT_MANAGER = LocalImportManager()
