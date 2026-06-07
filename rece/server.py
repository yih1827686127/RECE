from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from .imports import IMPORT_MANAGER
from .jobs import MANAGER
from .paths import HK_SCENARIO, PACKAGE_MODE, SCENARIOS_ROOT, TMP_ROOT, UPLOAD_LIMIT_BYTES, WEB_ROOT, ensure_rece_write, is_under, local_import_supported, mkdir_rece, runtime_info


RUNS: dict[str, dict[str, object]] = {}
MAX_UPLOAD_BYTES = UPLOAD_LIMIT_BYTES


def _json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, object]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _safe_child(root: Path, relative_path: str) -> Path | None:
    if "\x00" in relative_path:
        return None
    relative_path = relative_path.replace("\\", "/").lstrip("/")
    path = (root / relative_path).resolve()
    return path if is_under(path, root) else None


def _serve_file(handler: BaseHTTPRequestHandler, path: Path) -> None:
    if not path.exists() or not path.is_file():
        _json(handler, 404, {"error": f"not found: {path.name}"})
        return
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    size = path.stat().st_size
    handler.send_response(200)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Length", str(size))
    handler.end_headers()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            handler.wfile.write(chunk)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, object]:
    try:
        length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("invalid Content-Length") from None
    if length > MAX_UPLOAD_BYTES:
        raise ValueError("Request body exceeds 1 GiB limit")
    body = handler.rfile.read(length)
    payload = json.loads(body.decode("utf-8") or "{}")
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


def _parse_multipart(handler: BaseHTTPRequestHandler) -> tuple[dict[str, str], dict[str, Path]]:
    content_type = handler.headers.get("Content-Type", "")
    if not content_type.startswith("multipart/form-data"):
        raise ValueError("POST /api/runs requires multipart/form-data")
    try:
        content_length = int(handler.headers.get("Content-Length", "0"))
    except ValueError:
        raise ValueError("invalid Content-Length") from None
    if content_length > MAX_UPLOAD_BYTES:
        raise ValueError("Multipart upload exceeds 1 GiB limit")
    upload_dir = mkdir_rece(TMP_ROOT / "uploads" / uuid.uuid4().hex)
    form = cgi.FieldStorage(
        fp=handler.rfile,
        headers=handler.headers,
        environ={
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": content_type,
            "CONTENT_LENGTH": handler.headers.get("Content-Length", "0"),
        },
    )
    fields: dict[str, str] = {}
    uploads: dict[str, Path] = {}
    file_key_map = {
        "celeris_config": "config",
        "celeris_bathy": "bathy",
        "celeris_waves": "waves",
        "celeris_overlay": "overlay",
        "reef3d_zip": "reef3d_zip",
    }
    for key in form.keys():
        item = form[key]
        if isinstance(item, list):
            item = item[0]
        filename = getattr(item, "filename", None)
        if filename:
            mapped = file_key_map.get(key, key)
            safe_name = Path(filename).name or mapped
            target = ensure_rece_write(upload_dir / f"{mapped}_{safe_name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 0
            with target.open("wb") as f:
                while True:
                    chunk = item.file.read(1024 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise ValueError(f"Uploaded file exceeds 1 GiB limit: {safe_name}")
                    f.write(chunk)
            uploads[mapped] = target
        else:
            value = item.value
            fields[key] = value if isinstance(value, str) else str(value)
    return fields, uploads


def _run_background(run_id: str, mpi_ranks: int) -> None:
    from .workflow import run_workflow

    RUNS[run_id].update({"status": "running", "started_at": time.time()})
    try:
        result = run_workflow(mpi_ranks=mpi_ranks)
        RUNS[run_id].update({"status": "complete", "completed_at": time.time(), "result": result})
    except Exception as exc:  # noqa: BLE001
        RUNS[run_id].update({"status": "failed", "completed_at": time.time(), "error": str(exc)})


class RECEHandler(BaseHTTPRequestHandler):
    server_version = "RECE/0.1"

    def log_message(self, fmt: str, *args) -> None:
        print(f"[RECE] {self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/health":
            _json(self, 200, {"status": "ok", "scenario": HK_SCENARIO})
            return
        if path == "/api/runtime":
            _json(self, 200, runtime_info())
            return
        if path.startswith("/api/imports/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3:
                import_id = parts[2]
                if len(parts) == 4 and parts[3] == "status":
                    status = IMPORT_MANAGER.public_status(import_id)
                    if status is None:
                        _json(self, 404, {"error": "unknown import id"})
                    else:
                        _json(self, 200, status)
                    return
                if len(parts) == 4 and parts[3] == "result_index":
                    result_index = IMPORT_MANAGER.result_index(import_id)
                    if result_index is None:
                        _json(self, 404, {"error": "unknown import id or result index is not ready"})
                    else:
                        _json(self, 200, result_index)
                    return
                if len(parts) == 5 and parts[3] == "files":
                    local_file = IMPORT_MANAGER.file_path(import_id, parts[4])
                    if local_file is None:
                        _json(self, 404, {"error": "unknown import file"})
                    else:
                        _serve_file(self, local_file)
                    return
                if len(parts) == 5 and parts[3] == "lod" and parts[4] == "manifest":
                    manifest = IMPORT_MANAGER.manifest_path(import_id)
                    if manifest is None:
                        _json(self, 404, {"error": "unknown import id or LOD manifest is not ready"})
                    else:
                        _serve_file(self, manifest)
                    return
                if len(parts) == 6 and parts[3] == "lod" and parts[5] == "manifest":
                    try:
                        factor = int(parts[4])
                    except ValueError:
                        _json(self, 404, {"error": "invalid LOD factor"})
                        return
                    manifest = IMPORT_MANAGER.manifest_path(import_id, factor)
                    if manifest is None:
                        _json(self, 404, {"error": "unknown import id or LOD factor"})
                    else:
                        _serve_file(self, manifest)
                    return
        if path == f"/api/scenarios/{HK_SCENARIO}/manifest":
            manifest = SCENARIOS_ROOT / HK_SCENARIO / "frames_manifest.json"
            if not manifest.exists():
                _json(self, 404, {"error": "frames manifest not found; run the workflow first"})
                return
            _serve_file(self, manifest)
            return
        frame_prefix = f"/api/scenarios/{HK_SCENARIO}/"
        if path.startswith(frame_prefix):
            rel = path[len(frame_prefix) :]
            if rel.startswith("frames/"):
                frame_path = _safe_child(SCENARIOS_ROOT / HK_SCENARIO / "frames", rel[len("frames/") :])
                if frame_path is None:
                    _json(self, 404, {"error": "frame path is outside the scenario frames directory"})
                    return
                _serve_file(self, frame_path)
                return
        if path.startswith("/api/runs/") and path.endswith("/status"):
            run_id = path.split("/")[3]
            custom_run = MANAGER.public_status(run_id)
            if custom_run is not None:
                _json(self, 200, custom_run)
                return
            run = RUNS.get(run_id)
            if run is None:
                _json(self, 404, {"error": "unknown run id"})
                return
            _json(self, 200, run)
            return

        if path.startswith("/api/runs/"):
            parts = path.strip("/").split("/")
            if len(parts) >= 3:
                run_id = parts[2]
                if len(parts) == 3 and parts[-1] == run_id:
                    status = MANAGER.public_status(run_id)
                    if status is None:
                        _json(self, 404, {"error": "unknown run id"})
                    else:
                        _json(self, 200, status)
                    return
                if len(parts) == 4 and parts[3] == "manifest":
                    manifest = MANAGER.manifest_path(run_id)
                    if manifest is None:
                        _json(self, 404, {"error": "unknown run id"})
                    else:
                        _serve_file(self, manifest)
                    return
                if len(parts) >= 5 and parts[3] == "frames":
                    name = "/".join(parts[4:])
                    frame = MANAGER.frame_path(run_id, name)
                    if frame is None:
                        _json(self, 404, {"error": "unknown run id or unsafe frame path"})
                    else:
                        _serve_file(self, frame)
                    return
                if len(parts) >= 5 and parts[3] == "assets":
                    name = "/".join(parts[4:])
                    asset = MANAGER.asset_path(run_id, name)
                    if asset is None:
                        _json(self, 404, {"error": "unknown run id or unsafe asset path"})
                    else:
                        _serve_file(self, asset)
                    return

        static_path = _safe_child(WEB_ROOT, path.lstrip("/") or "index.html")
        if static_path is None:
            _json(self, 404, {"error": "static path is outside the web directory"})
            return
        if static_path.is_dir():
            static_path = static_path / "index.html"
        _serve_file(self, static_path)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        if path == "/api/runs":
            try:
                content_type = self.headers.get("Content-Type", "")
                if content_type.startswith("application/json"):
                    payload = _read_json_body(self)
                    import_id = str(payload.get("import_id") or "").strip()
                    if not import_id:
                        _json(self, 400, {"error": "JSON POST /api/runs requires import_id"})
                        return
                    mode = str(payload.get("mode") or "view").strip().lower()
                    lod_factor_raw = payload.get("lod_factor")
                    lod_factor = int(lod_factor_raw) if lod_factor_raw not in {None, ""} else None
                    if mode == "view":
                        job = MANAGER.create_import_viewer_job(import_id=import_id, lod_factor=lod_factor)
                    elif mode == "solve":
                        params = payload.get("params") or {}
                        if not isinstance(params, dict):
                            raise ValueError("params must be a JSON object")
                        output_path = str(payload.get("output_path") or "")
                        output_token = str(payload.get("output_token") or "")
                        if not output_path or not output_token:
                            _json(self, 400, {"error": "Local import solve mode requires output_path and output_token"})
                            return
                        job = MANAGER.create_import_solve_job(
                            import_id=import_id,
                            output_path=output_path,
                            output_token=output_token,
                            params=params,
                        )
                    else:
                        _json(self, 400, {"error": "JSON POST /api/runs mode must be view or solve"})
                        return
                    _json(self, 202, job)
                    return
                fields, uploads = _parse_multipart(self)
                solver = fields.get("solver", "reef3d")
                if solver != "reef3d":
                    _json(self, 400, {"error": "Only solver=reef3d is supported by POST /api/runs"})
                    return
                params = json.loads(fields.get("params", "{}"))
                if not isinstance(params, dict):
                    raise ValueError("params must be a JSON object")
                job = MANAGER.create_reef3d_job(
                    input_mode=fields.get("input_mode", "celeris_files"),
                    uploads=uploads,
                    params=params,
                    control_override=fields.get("control_text"),
                    ctrl_override=fields.get("ctrl_text"),
                )
            except RuntimeError as exc:
                _json(self, 409, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _json(self, 400, {"error": str(exc)})
                return
            _json(self, 202, job)
            return

        if path == "/api/imports":
            try:
                if not local_import_supported():
                    _json(self, 403, {"error": "Local directory import is disabled for this runtime"})
                    return
                payload = _read_json_body(self)
                source_path = str(payload.get("path") or "")
                token = str(payload.get("token") or "")
                if not source_path or not token:
                    _json(self, 400, {"error": "path and token are required"})
                    return
                job = IMPORT_MANAGER.create_import_from_authorized(source_path, token)
            except PermissionError as exc:
                _json(self, 403, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                _json(self, 400, {"error": str(exc)})
                return
            _json(self, 202, job)
            return

        if path.startswith("/api/imports/") and path.endswith("/cancel"):
            import_id = path.split("/")[3]
            status = IMPORT_MANAGER.cancel(import_id)
            if status is None:
                _json(self, 404, {"error": "unknown import id"})
            else:
                _json(self, 202, status)
            return

        if path.startswith("/api/runs/") and path.endswith("/cancel"):
            run_id = path.split("/")[3]
            status = MANAGER.cancel(run_id)
            if status is None:
                _json(self, 404, {"error": "unknown run id"})
            else:
                _json(self, 202, status)
            return

        if path == f"/api/scenarios/{HK_SCENARIO}/run":
            if PACKAGE_MODE:
                _json(self, 404, {"error": "packaged RECE runtime does not include fixed example workflows"})
                return
            run_id = uuid.uuid4().hex
            RUNS[run_id] = {"id": run_id, "status": "queued", "scenario": HK_SCENARIO}
            thread = threading.Thread(target=_run_background, args=(run_id, 4), daemon=True)
            thread.start()
            _json(self, 202, {"run_id": run_id, "status_url": f"/api/runs/{run_id}/status"})
            return
        _json(self, 404, {"error": "unknown endpoint"})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rece.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), RECEHandler)
    print(f"RECE server listening at http://{args.host}:{args.port}")
    print(f"Serving web root: {WEB_ROOT}")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
