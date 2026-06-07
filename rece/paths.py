from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _resource_root() -> Path:
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[1]


def _runtime_mode() -> str:
    explicit = os.environ.get("RECE_RUNTIME_MODE", "").strip().lower()
    if explicit:
        return explicit
    return "package" if _is_frozen() else "development"


def _platform_key() -> str:
    if os.name == "nt":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "macos"
    return sys.platform


def _user_data_root() -> Path:
    explicit = os.environ.get("RECE_USER_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return (Path(base) / "RECE").resolve()
        return (Path.home() / "AppData" / "Local" / "RECE").resolve()
    if sys.platform.startswith("linux"):
        base = os.environ.get("XDG_DATA_HOME")
        if base:
            return (Path(base) / "RECE").resolve()
        return (Path.home() / ".local" / "share" / "RECE").resolve()
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" / "RECE").resolve()
    return (Path.home() / ".rece").resolve()


RESOURCE_ROOT = _resource_root()
RUNTIME_MODE = _runtime_mode()
PLATFORM = _platform_key()
PACKAGE_MODE = RUNTIME_MODE in {"package", "runtime", "installed", "frozen"}
DESKTOP_CONTEXT = os.environ.get("RECE_DESKTOP_CONTEXT", "").strip().lower() in {"1", "true", "yes", "on"}
RECE_ROOT = _user_data_root() if PACKAGE_MODE else RESOURCE_ROOT
AAA_ROOT = RESOURCE_ROOT.parent
DATA_ROOT = Path(os.environ.get("RECE_SOURCE_DATA_ROOT", AAA_ROOT / "hk_dtm_example")).resolve()
WEB_ROOT = RESOURCE_ROOT / "web"
SCENARIOS_ROOT = RECE_ROOT / "examples"
LOG_ROOT = RECE_ROOT / "logs"
TMP_ROOT = RECE_ROOT / "tmp"
THIRD_PARTY_ROOT = RESOURCE_ROOT / "third_party"
REEF3D_ROOT = THIRD_PARTY_ROOT / "REEF3D"
HK_SCENARIO = "hk_victoria_smoke"
UPLOAD_LIMIT_BYTES = 1024**3
MAX_DEFAULT_LOD_CELLS = int(os.environ.get("RECE_MAX_DEFAULT_LOD_CELLS", "4000000"))


def local_import_supported() -> bool:
    return DESKTOP_CONTEXT or os.environ.get("RECE_ENABLE_LOCAL_IMPORT", "").strip().lower() in {"1", "true", "yes", "on"}


def desktop_directory_picker_supported() -> bool:
    return local_import_supported() and os.name == "nt"


def _solver_bin_dir() -> Path:
    explicit = os.environ.get("RECE_SOLVER_BIN_DIR", "").strip()
    if explicit:
        return Path(explicit).resolve()
    default = REEF3D_ROOT / "bin"
    if sys.platform.startswith("linux"):
        platform_dir = default / "linux-x86_64"
        return platform_dir if platform_dir.exists() else default
    return default


def _solver_binary(env_name: str, default_name: str) -> Path:
    explicit = os.environ.get(env_name, "").strip()
    if explicit:
        return Path(explicit).resolve()
    return (_solver_bin_dir() / default_name).resolve()


def _windows_mpiexec_fallback() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft MPI" / "Bin" / "mpiexec.exe"


def find_mpiexec() -> Path | None:
    explicit = os.environ.get("RECE_MPIEXEC", "").strip()
    if explicit:
        path = Path(explicit).resolve()
        return path if path.exists() else None
    found = shutil.which("mpiexec")
    if found:
        return Path(found).resolve()
    if os.name == "nt":
        fallback = _windows_mpiexec_fallback()
        if fallback.exists():
            return fallback.resolve()
    return None


def require_mpiexec() -> str:
    mpiexec = find_mpiexec()
    if mpiexec is not None:
        return str(mpiexec)
    if os.name == "nt":
        raise FileNotFoundError("Microsoft MPI mpiexec.exe was not found. Install Microsoft MPI Runtime and restart RECE.")
    raise FileNotFoundError("mpiexec was not found. Install OpenMPI on Ubuntu and restart RECE.")


REEF3D_BIN = _solver_binary("RECE_REEF3D_BIN", "reef3d.exe" if os.name == "nt" else "reef3d")
DIVEMESH_BIN = _solver_binary("RECE_DIVEMESH_BIN", "DiveMESH.exe" if os.name == "nt" else "DiveMESH")


def is_under(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    base = root.resolve()
    return resolved == base or base in resolved.parents


def ensure_under(path: Path | str, root: Path, *, label: str) -> Path:
    resolved = Path(path).resolve()
    if not is_under(resolved, root):
        raise ValueError(f"{label} must stay under {root}: {resolved}")
    return resolved


def ensure_rece_write(path: Path | str) -> Path:
    return ensure_under(path, RECE_ROOT, label="write path")


def ensure_allowed_read(path: Path | str) -> Path:
    resolved = Path(path).resolve()
    allowed_roots = [RECE_ROOT, RESOURCE_ROOT, DATA_ROOT]
    if any(is_under(resolved, root) for root in allowed_roots):
        return resolved
    roots = ", ".join(str(root) for root in allowed_roots)
    raise ValueError(f"read path must stay under an allowed RECE root ({roots}): {resolved}")


def mkdir_rece(path: Path | str) -> Path:
    resolved = ensure_rece_write(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def write_text_rece(path: Path | str, text: str, *, crlf: bool = False) -> Path:
    resolved = ensure_rece_write(path)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    newline = "\r\n" if crlf else "\n"
    with resolved.open("w", encoding="utf-8", newline=newline) as f:
        f.write(text)
    return resolved


def rel_to_rece(path: Path | str) -> str:
    resolved = Path(path).resolve()
    for root in [RECE_ROOT, RESOURCE_ROOT, DATA_ROOT]:
        root = root.resolve()
        if is_under(resolved, root):
            rel = str(resolved.relative_to(root))
            if root == RECE_ROOT.resolve():
                return rel
            if root == RESOURCE_ROOT.resolve():
                return str(Path("<resources>") / rel)
            return str(Path("<source_data>") / rel)
    return str(resolved)


def runtime_info() -> dict[str, object]:
    mpiexec = find_mpiexec()
    return {
        "platform": PLATFORM,
        "system": platform.system(),
        "runtime_mode": RUNTIME_MODE,
        "package_mode": PACKAGE_MODE,
        "resource_root": str(RESOURCE_ROOT),
        "user_data_root": str(RECE_ROOT),
        "web_root": str(WEB_ROOT),
        "examples_available": (WEB_ROOT / "examples").exists(),
        "solver_bin_dir": str(_solver_bin_dir()),
        "reef3d_bin": str(REEF3D_BIN),
        "reef3d_bin_exists": REEF3D_BIN.exists(),
        "divemesh_bin": str(DIVEMESH_BIN),
        "divemesh_bin_exists": DIVEMESH_BIN.exists(),
        "mpiexec": str(mpiexec) if mpiexec is not None else "",
        "mpiexec_exists": mpiexec is not None,
        "upload_limit_bytes": UPLOAD_LIMIT_BYTES,
        "local_import_supported": local_import_supported(),
        "max_default_lod_cells": MAX_DEFAULT_LOD_CELLS,
        "desktop_directory_picker_supported": desktop_directory_picker_supported(),
    }
