from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .converter import convert_hk_smoke, convert_reef3d_outputs
from .hk_prepare import prepare_hk_smoke
from .paths import (
    DIVEMESH_BIN,
    HK_SCENARIO,
    LOG_ROOT,
    RECE_ROOT,
    REEF3D_BIN,
    RESOURCE_ROOT,
    SCENARIOS_ROOT,
    ensure_rece_write,
    find_mpiexec,
    mkdir_rece,
    rel_to_rece,
    require_mpiexec,
    write_text_rece,
)


def check_environment() -> dict[str, object]:
    packages: dict[str, object] = {}
    for name in ["numpy", "scipy", "PIL", "requests", "vtkmodules"]:
        try:
            module = __import__(name)
            packages[name] = getattr(module, "__version__", "available")
        except Exception as exc:  # noqa: BLE001
            packages[name] = f"missing: {exc}"
    mpiexec = find_mpiexec()
    report = {
        "rece_root": str(RECE_ROOT),
        "divemesh": {"path": str(DIVEMESH_BIN), "exists": DIVEMESH_BIN.exists()},
        "reef3d": {"path": str(REEF3D_BIN), "exists": REEF3D_BIN.exists()},
        "mpiexec": {"path": str(mpiexec) if mpiexec is not None else "", "exists": mpiexec is not None},
        "python": sys.version,
        "packages": packages,
    }
    write_text_rece(RECE_ROOT / "ENVIRONMENT_REPORT.json", json.dumps(report, indent=2) + "\n")
    return report


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


def _run_process(args: list[str], cwd: Path, *, log_prefix: str, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    cwd = ensure_rece_write(cwd)
    log_dir = mkdir_rece(LOG_ROOT / HK_SCENARIO)
    started = time.strftime("%Y%m%d_%H%M%S")
    proc = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout, check=False, env=_external_solver_env())
    write_text_rece(log_dir / f"{started}_{log_prefix}_stdout.log", proc.stdout)
    write_text_rece(log_dir / f"{started}_{log_prefix}_stderr.log", proc.stderr)
    if proc.returncode != 0:
        raise RuntimeError(f"{log_prefix} failed with exit code {proc.returncode}; logs: {rel_to_rece(log_dir)}")
    return proc


def run_divemesh() -> None:
    if not DIVEMESH_BIN.exists():
        raise FileNotFoundError(DIVEMESH_BIN)
    case_dir = SCENARIOS_ROOT / HK_SCENARIO / "reef3d_case"
    for required in ["control.txt", "geo.dat"]:
        if not (case_dir / required).exists():
            raise FileNotFoundError(case_dir / required)
    _run_process([str(DIVEMESH_BIN)], case_dir, log_prefix="divemesh")


def run_reef3d(mpi_ranks: int = 4) -> None:
    if not REEF3D_BIN.exists():
        raise FileNotFoundError(REEF3D_BIN)
    if mpi_ranks < 1:
        raise ValueError("mpi_ranks must be at least 1")
    case_dir = SCENARIOS_ROOT / HK_SCENARIO / "reef3d_case"
    if not (case_dir / "ctrl.txt").exists():
        raise FileNotFoundError(case_dir / "ctrl.txt")
    if mpi_ranks == 1:
        args = [str(REEF3D_BIN)]
    else:
        args = [_find_mpiexec(), "-n", str(mpi_ranks), str(REEF3D_BIN)]
    _run_process(args, case_dir, log_prefix="reef3d", timeout=1800)


def validate_hk_smoke() -> dict[str, object]:
    scenario_dir = SCENARIOS_ROOT / HK_SCENARIO
    prep = scenario_dir / "prepare_manifest.json"
    frames_manifest = scenario_dir / "frames_manifest.json"
    if not prep.exists():
        raise FileNotFoundError(prep)
    if not frames_manifest.exists():
        raise FileNotFoundError(frames_manifest)
    manifest = json.loads(frames_manifest.read_text(encoding="utf-8"))
    frames = manifest.get("frames", [])
    if len(frames) < 3:
        raise RuntimeError(f"Expected at least 3 converted frames, found {len(frames)}")
    width = int(manifest["width"])
    height = int(manifest["height"])
    expected_bytes = width * height * 4 * 4
    for frame in frames[:3]:
        for key in ["state", "velocity"]:
            path = scenario_dir / str(frame[key])
            if not path.exists():
                raise FileNotFoundError(path)
            if path.stat().st_size != expected_bytes:
                raise RuntimeError(f"{path} has {path.stat().st_size} bytes, expected {expected_bytes}")
    report = {
        "scenario": HK_SCENARIO,
        "frame_count": len(frames),
        "expected_frame_bytes": expected_bytes,
        "status": "ok",
    }
    write_text_rece(scenario_dir / "validation_report.json", json.dumps(report, indent=2) + "\n")
    return report


def run_workflow(*, mpi_ranks: int = 4, skip_reef3d: bool = False) -> dict[str, object]:
    env = check_environment()
    prep = prepare_hk_smoke()
    run_divemesh()
    if not skip_reef3d:
        run_reef3d(mpi_ranks=mpi_ranks)
    converted = convert_hk_smoke()
    validation = validate_hk_smoke()
    summary = {"environment": env, "prepare": prep, "convert": converted, "validation": validation}
    write_text_rece(SCENARIOS_ROOT / HK_SCENARIO / "workflow_summary.json", json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    return summary


def convert_meander_for_test(output_dir: Path) -> dict[str, object]:
    case_dir = RECE_ROOT / "third_party" / "REEF3D" / "simulations" / "NHFLOW_Meander"
    bathy_path = case_dir / "REEF3D_NHFLOW_VTP_BED" / "bathy.txt"
    if not bathy_path.exists():
        bathy_path = output_dir / "meander_bathy.txt"
        row = " ".join(["-0.500"] * 160)
        write_text_rece(bathy_path, "\n".join([row] * 80) + "\n")
    return convert_reef3d_outputs(
        case_dir,
        output_dir,
        bathy_path=bathy_path,
        width=160,
        height=80,
        dx=0.25,
        dy=0.25,
        sea_level=4.01,
        scenario="meander_conversion_test",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m rece.workflow")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("env")
    sub.add_parser("prepare")
    sub.add_parser("divemesh")
    reef = sub.add_parser("reef3d")
    reef.add_argument("--mpi-ranks", type=int, default=4)
    sub.add_parser("convert")
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument("--scenario", default=HK_SCENARIO)
    run.add_argument("--mpi-ranks", type=int, default=4)
    run.add_argument("--skip-reef3d", action="store_true", help="For converter debugging only; requires existing REEF3D output.")
    args = parser.parse_args(argv)

    if getattr(args, "scenario", HK_SCENARIO) != HK_SCENARIO:
        raise SystemExit(f"Only {HK_SCENARIO!r} is implemented in this build")

    if args.command == "env":
        result = check_environment()
    elif args.command == "prepare":
        result = prepare_hk_smoke()
    elif args.command == "divemesh":
        run_divemesh()
        result = {"status": "ok"}
    elif args.command == "reef3d":
        run_reef3d(mpi_ranks=args.mpi_ranks)
        result = {"status": "ok"}
    elif args.command == "convert":
        result = convert_hk_smoke()
    elif args.command == "validate":
        result = validate_hk_smoke()
    elif args.command == "run":
        result = run_workflow(mpi_ranks=args.mpi_ranks, skip_reef3d=args.skip_reef3d)
    else:
        raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
