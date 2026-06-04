from __future__ import annotations

import os
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


def _user_data_root() -> Path:
    explicit = os.environ.get("RECE_USER_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit).resolve()
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        return (Path(base) / "RECE").resolve()
    return (Path.home() / "AppData" / "Local" / "RECE").resolve()


RESOURCE_ROOT = _resource_root()
RUNTIME_MODE = _runtime_mode()
PACKAGE_MODE = RUNTIME_MODE in {"package", "runtime", "installed", "frozen"}
RECE_ROOT = _user_data_root() if PACKAGE_MODE else RESOURCE_ROOT
AAA_ROOT = RESOURCE_ROOT.parent
DATA_ROOT = Path(os.environ.get("RECE_SOURCE_DATA_ROOT", AAA_ROOT / "hk_dtm_example")).resolve()
WEB_ROOT = RESOURCE_ROOT / "web"
SCENARIOS_ROOT = RECE_ROOT / "examples"
LOG_ROOT = RECE_ROOT / "logs"
TMP_ROOT = RECE_ROOT / "tmp"
THIRD_PARTY_ROOT = RESOURCE_ROOT / "third_party"
REEF3D_ROOT = THIRD_PARTY_ROOT / "REEF3D"
REEF3D_BIN = REEF3D_ROOT / "bin" / "reef3d.exe"
DIVEMESH_BIN = REEF3D_ROOT / "bin" / "DiveMESH.exe"
HK_SCENARIO = "hk_victoria_smoke"


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
    return {
        "runtime_mode": RUNTIME_MODE,
        "package_mode": PACKAGE_MODE,
        "resource_root": str(RESOURCE_ROOT),
        "user_data_root": str(RECE_ROOT),
        "web_root": str(WEB_ROOT),
        "examples_available": (WEB_ROOT / "examples").exists(),
        "reef3d_bin_exists": REEF3D_BIN.exists(),
        "divemesh_bin_exists": DIVEMESH_BIN.exists(),
    }
