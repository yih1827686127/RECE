from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import socket
import sys
import threading
import time
from http.server import ThreadingHTTPServer
from pathlib import Path


if "--package-mode" in sys.argv:
    os.environ.setdefault("RECE_RUNTIME_MODE", "package")

from .jobs import MANAGER  # noqa: E402
from .paths import DIVEMESH_BIN, PACKAGE_MODE, RECE_ROOT, REEF3D_BIN, RESOURCE_ROOT, WEB_ROOT, runtime_info  # noqa: E402
from .server import RECEHandler  # noqa: E402


APP_TITLE = "RECE"
DEFAULT_HOST = "127.0.0.1"


def message_box(title: str, message: str, *, icon: int = 0x40) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(None, message, title, icon)
    else:
        print(f"{title}: {message}", file=sys.stderr)


def choose_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def detect_webview2_runtime() -> bool:
    if os.name != "nt":
        return True
    try:
        import winreg

        keys = [
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}",
        ]
        for root in [winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER]:
            for key in keys:
                try:
                    with winreg.OpenKey(root, key):
                        return True
                except OSError:
                    continue
    except Exception:
        pass
    candidates = [
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Microsoft" / "EdgeWebView" / "Application",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft" / "EdgeWebView" / "Application",
    ]
    return any(path.exists() for path in candidates)


def dependency_report() -> tuple[list[str], list[str]]:
    fatal: list[str] = []
    warnings: list[str] = []
    if not detect_webview2_runtime():
        fatal.append("Microsoft Edge WebView2 Runtime is not installed.")
    if not WEB_ROOT.exists():
        fatal.append(f"Web UI resources were not found: {WEB_ROOT}")
    if not REEF3D_BIN.exists():
        fatal.append(f"REEF3D executable was not found: {REEF3D_BIN}")
    if not DIVEMESH_BIN.exists():
        fatal.append(f"DIVEMesh executable was not found: {DIVEMESH_BIN}")
    if not (shutil.which("mpiexec") or Path(r"C:\Program Files\Microsoft MPI\Bin\mpiexec.exe").exists()):
        warnings.append("Microsoft MPI was not found. Celeris upload mode can open, but REEF3D MPI jobs need MS-MPI.")
    if PACKAGE_MODE:
        RECE_ROOT.mkdir(parents=True, exist_ok=True)
    return fatal, warnings


def start_server(host: str, port: int) -> tuple[ThreadingHTTPServer, threading.Thread]:
    server = ThreadingHTTPServer((host, port), RECEHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def wait_for_server(host: str, port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"RECE server did not start on {host}:{port}")


def run_window(url: str, *, debug: bool) -> None:
    try:
        import webview
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError("pywebview is not installed; rebuild RECE with pywebview included") from exc

    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    if debug:
        webview.settings["REMOTE_DEBUGGING_PORT"] = 9333

    icon_path = RESOURCE_ROOT / "web" / "favicon.ico"
    storage_path = RECE_ROOT / "webview_profile"
    storage_path.mkdir(parents=True, exist_ok=True)
    webview.create_window(
        APP_TITLE,
        url,
        width=1440,
        height=960,
        min_size=(1180, 760),
        background_color="#07111f",
        text_select=True,
    )
    webview.start(
        gui="edgechromium",
        debug=debug,
        private_mode=False,
        storage_path=str(storage_path),
        icon=str(icon_path) if icon_path.exists() else None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="RECE")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--package-mode", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--print-runtime", action="store_true", help="Print runtime paths and exit.")
    args = parser.parse_args(argv)

    if args.print_runtime:
        import json

        print(json.dumps(runtime_info(), indent=2))
        return 0

    fatal, warnings = dependency_report()
    if fatal:
        message_box("RECE cannot start", "\n".join(fatal), icon=0x10)
        return 2
    if warnings and args.debug:
        message_box("RECE dependency warning", "\n".join(warnings), icon=0x30)

    port = args.port or choose_port(args.host)
    server, thread = start_server(args.host, port)
    url = f"http://{args.host}:{port}/"
    try:
        wait_for_server(args.host, port)
        run_window(url, debug=args.debug)
    except Exception as exc:  # noqa: BLE001
        message_box("RECE runtime error", str(exc), icon=0x10)
        return 1
    finally:
        MANAGER.cancel_all()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
