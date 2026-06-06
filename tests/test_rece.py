from __future__ import annotations

import http.client
import json
import os
import shutil
import threading
import unittest
import uuid
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np

from rece.converter import convert_reef3d_outputs
from rece.custom_case import (
    CUSTOM_RUNS_ROOT,
    normalize_params,
    prepare_from_celeris_files,
    prepare_from_reef3d_zip,
    read_m10_partition,
    safe_extract_zip,
    validate_grid,
)
from rece.jobs import MANAGER, JobManager, _external_solver_env
from rece.hk_prepare import Tile, cached_or_downloaded_tifs, find_one, prepare_hk_smoke, select_dtm_tiles
from rece.paths import DATA_ROOT, DIVEMESH_BIN, PLATFORM, RECE_ROOT, REEF3D_BIN, RESOURCE_ROOT, ensure_allowed_read, ensure_rece_write, runtime_info
from rece.server import RECEHandler
from rece.workflow import convert_meander_for_test


def has_hk_source_data() -> bool:
    return any(DATA_ROOT.glob("Hong_Kong_Digital_Terrain_Model_from_2020_LiDAR_Survey_*.geojson"))


class RECEPathTests(unittest.TestCase):
    def test_write_guard_accepts_rece(self) -> None:
        self.assertTrue(str(ensure_rece_write(RECE_ROOT / "tmp" / "guard.txt")).endswith("guard.txt"))

    def test_write_guard_rejects_outside(self) -> None:
        with self.assertRaises(ValueError):
            ensure_rece_write(DATA_ROOT / "not-a-write-target.txt")

    def test_read_guard_accepts_data(self) -> None:
        self.assertEqual(ensure_allowed_read(DATA_ROOT), DATA_ROOT.resolve())


class RECEPackagingTests(unittest.TestCase):
    def test_installer_always_shows_install_directory_page(self) -> None:
        setup_script = Path(__file__).resolve().parents[1] / "packaging" / "RECE_Setup.iss"
        values: dict[str, str] = {}
        for line in setup_script.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith(";") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip().lower()] = value.strip().lower()

        self.assertEqual(values.get("defaultdirname"), "{autopf}\\rece")
        self.assertEqual(values.get("disabledirpage"), "no")
        self.assertEqual(values.get("privilegesrequiredoverridesallowed"), "dialog commandline")

        text = setup_script.read_text(encoding="utf-8").lower()
        self.assertIn('name: "desktopicon"', text)
        self.assertIn("flags: unchecked", text)

    def test_installer_build_writes_sha256_sidecar(self) -> None:
        build_script = Path(__file__).resolve().parents[1] / "packaging" / "build_installer.ps1"
        text = build_script.read_text(encoding="utf-8")
        self.assertIn("Get-FileHash -Algorithm SHA256", text)
        self.assertIn("RECE_Setup.exe.sha256", text)

    def test_linux_packaging_script_outputs_tarball_deb_and_sha256(self) -> None:
        build_script = Path(__file__).resolve().parents[1] / "packaging" / "linux" / "build_linux_package.sh"
        text = build_script.read_text(encoding="utf-8")
        self.assertIn("RECE-linux-x86_64.tar.gz", text)
        self.assertIn("rece_${DEB_VERSION}_${ARCH}.deb", text)
        self.assertIn("linux-x86_64", text)
        self.assertIn("dpkg-deb --build", text)
        self.assertIn("sha256sum", text)

    def test_linux_desktop_entry_uses_system_launcher(self) -> None:
        desktop = Path(__file__).resolve().parents[1] / "packaging" / "linux" / "rece.desktop"
        text = desktop.read_text(encoding="utf-8")
        self.assertIn("Name=RECE", text)
        self.assertIn("Exec=/usr/bin/rece", text)
        self.assertIn("Icon=rece", text)

    def test_runtime_info_reports_platform_solver_paths(self) -> None:
        info = runtime_info()
        self.assertIn(info["platform"], {"windows", "linux", "macos"})
        self.assertEqual(info["reef3d_bin"], str(REEF3D_BIN))
        self.assertEqual(info["divemesh_bin"], str(DIVEMESH_BIN))
        self.assertIn("mpiexec_exists", info)
        if PLATFORM == "windows":
            self.assertTrue(str(REEF3D_BIN).lower().endswith("reef3d.exe"))
            self.assertTrue(str(DIVEMESH_BIN).lower().endswith("divemesh.exe"))
        elif PLATFORM == "linux":
            self.assertEqual(REEF3D_BIN.name, "reef3d")
            self.assertEqual(DIVEMESH_BIN.name, "DiveMESH")


class RECEPrepareTests(unittest.TestCase):
    def test_prepare_hk_smoke_outputs_core_files(self) -> None:
        if not has_hk_source_data():
            self.skipTest("Hong Kong source data is not available in this checkout")
        manifest = prepare_hk_smoke()
        scenario_dir = RECE_ROOT / manifest["paths"]["scenario_dir"]
        web_dir = RECE_ROOT / manifest["paths"]["web_example_dir"]
        self.assertTrue((scenario_dir / "reef3d_case" / "geo.dat").exists())
        self.assertTrue((scenario_dir / "reef3d_case" / "control.txt").exists())
        self.assertTrue((scenario_dir / "reef3d_case" / "ctrl.txt").exists())
        self.assertTrue((web_dir / "config.json").exists())
        config = json.loads((web_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["externalSolver"], "reef3d")
        self.assertEqual(config["WIDTH"], 120)
        self.assertEqual(config["HEIGHT"], 80)

    def test_raw_hk_tile_selection_uses_expected_domain(self) -> None:
        if not has_hk_source_data():
            self.skipTest("Hong Kong source data is not available in this checkout")
        geojson = find_one("Hong_Kong_Digital_Terrain_Model_from_2020_LiDAR_Survey_*.geojson")
        tiles = select_dtm_tiles(geojson, max_tiles=3)
        self.assertGreaterEqual(len(tiles), 1)
        self.assertLessEqual(len(tiles), 3)
        for tile in tiles:
            self.assertGreaterEqual(tile.center_e, 832_000.0)
            self.assertLess(tile.center_e, 838_000.0)
            self.assertGreaterEqual(tile.center_n, 816_000.0)
            self.assertLess(tile.center_n, 820_000.0)

    def test_empty_dtm_tile_selection_fails_clearly(self) -> None:
        path = RECE_ROOT / "tmp" / "empty_dtm_tiles.geojson"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"type":"FeatureCollection","features":[]}\n', encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "No DTM tiles selected"):
            select_dtm_tiles(path)

    def test_zip_extraction_stays_inside_rece_extract_dir(self) -> None:
        scenario_dir = RECE_ROOT / "tmp" / "test_safe_zip_extract"
        if scenario_dir.exists():
            shutil.rmtree(scenario_dir)
        downloads = scenario_dir / "downloads"
        downloads.mkdir(parents=True, exist_ok=True)
        zip_path = downloads / "unsafe.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../unsafe.tif", b"not-a-real-tif")
        paths = cached_or_downloaded_tifs(
            [
                Tile(
                    tile_name="unsafe",
                    filename="unsafe.tif",
                    url="",
                    center_e=835_000.0,
                    center_n=818_000.0,
                    sort_distance=0.0,
                )
            ],
            scenario_dir,
        )
        self.assertEqual(len(paths), 1)
        self.assertEqual(paths[0].name, "unsafe.tif")
        self.assertTrue(str(paths[0].resolve()).startswith(str((scenario_dir / "extracted").resolve())))


class RECEConversionTests(unittest.TestCase):
    def test_convert_copied_meander_output(self) -> None:
        case_dir = RECE_ROOT / "third_party" / "REEF3D" / "simulations" / "NHFLOW_Meander"
        if not (case_dir / "REEF3D_NHFLOW_VTP_FSF").exists():
            self.skipTest("Copied Meander VTP output is not available")
        output_dir = RECE_ROOT / "tmp" / "test_meander_conversion"
        bathy_path = output_dir / "meander_bathy.txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        np.savetxt(bathy_path, np.full((80, 160), -0.5, dtype=np.float32), fmt="%.3f")
        manifest = convert_reef3d_outputs(
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
        self.assertGreaterEqual(len(manifest["frames"]), 1)
        first_state = output_dir / manifest["frames"][0]["state"]
        self.assertEqual(first_state.stat().st_size, 160 * 80 * 4 * 4)

    def test_non_hk_conversion_does_not_mirror_manifest_to_web_examples(self) -> None:
        case_dir = RECE_ROOT / "third_party" / "REEF3D" / "simulations" / "NHFLOW_Meander"
        if not (case_dir / "REEF3D_NHFLOW_VTP_FSF").exists():
            self.skipTest("Copied Meander VTP output is not available")
        scenario = "meander_conversion_no_web_mirror"
        output_dir = RECE_ROOT / "tmp" / scenario
        bathy_path = output_dir / "meander_bathy.txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        np.savetxt(bathy_path, np.full((80, 160), -0.5, dtype=np.float32), fmt="%.3f")
        manifest = convert_reef3d_outputs(
            case_dir,
            output_dir,
            bathy_path=bathy_path,
            width=160,
            height=80,
            dx=0.25,
            dy=0.25,
            sea_level=4.01,
            scenario=scenario,
        )
        self.assertGreaterEqual(len(manifest["frames"]), 1)
        self.assertFalse((RECE_ROOT / "web" / "examples" / scenario / "frames_manifest.json").exists())

    def test_convert_meander_for_test_uses_rece_copy(self) -> None:
        output_dir = RECE_ROOT / "tmp" / "test_meander_helper"
        manifest = convert_meander_for_test(output_dir)
        self.assertEqual(manifest["scenario"], "meander_conversion_test")
        self.assertGreaterEqual(len(manifest["frames"]), 1)

    def test_incremental_conversion_marks_manifest_complete_state(self) -> None:
        case_dir = RECE_ROOT / "third_party" / "REEF3D" / "simulations" / "NHFLOW_Meander"
        fsf_dir = case_dir / "REEF3D_NHFLOW_VTP_FSF"
        files = sorted(fsf_dir.glob("*.pvtp"))[:2]
        if len(files) < 2:
            self.skipTest("Copied Meander VTP output is not available")
        output_dir = RECE_ROOT / "tmp" / "test_incremental_conversion"
        bathy_path = output_dir / "meander_bathy.txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        np.savetxt(bathy_path, np.full((80, 160), -0.5, dtype=np.float32), fmt="%.3f")
        first = convert_reef3d_outputs(
            case_dir,
            output_dir,
            bathy_path=bathy_path,
            width=160,
            height=80,
            dx=0.25,
            dy=0.25,
            sea_level=4.01,
            scenario="incremental_conversion_test",
            source_files=files[:1],
            complete=False,
        )
        self.assertFalse(first["complete"])
        second = convert_reef3d_outputs(
            case_dir,
            output_dir,
            bathy_path=bathy_path,
            width=160,
            height=80,
            dx=0.25,
            dy=0.25,
            sea_level=4.01,
            scenario="incremental_conversion_test",
            source_files=files,
            complete=True,
        )
        self.assertTrue(second["complete"])
        self.assertEqual(len(second["frames"]), 2)


class RECECustomCaseTests(unittest.TestCase):
    def make_small_celeris_uploads(self, root: Path) -> dict[str, Path]:
        root.mkdir(parents=True, exist_ok=True)
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
        config_path = root / "config.json"
        bathy_path = root / "bathy.txt"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        np.savetxt(bathy_path, np.full((10, 12), -4.0, dtype=np.float32), fmt="%.3f")
        return {"config": config_path, "bathy": bathy_path}

    def test_prepare_from_celeris_files_writes_case_and_external_config(self) -> None:
        run_id = f"unit_celeris_{uuid.uuid4().hex}"
        uploads = self.make_small_celeris_uploads(RECE_ROOT / "tmp" / run_id)
        prepared = prepare_from_celeris_files(run_id, uploads, {"output_frames": 3, "mpi_ranks": 1})
        self.assertTrue((prepared.case_dir / "geo.dat").exists())
        self.assertTrue((prepared.case_dir / "control.txt").exists())
        self.assertTrue((prepared.case_dir / "ctrl.txt").exists())
        config = json.loads((prepared.assets_dir / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(config["externalSolver"], "reef3d")
        self.assertEqual(config["externalFrameManifest"], f"/api/runs/{run_id}/manifest")
        self.assertEqual(config["WIDTH"], 12)
        self.assertEqual(prepared.mpi_ranks, 1)
        self.assertEqual(read_m10_partition(prepared.case_dir / "control.txt"), 1)
        self.assertEqual(read_m10_partition(prepared.case_dir / "ctrl.txt"), 1)
        ctrl_text = (prepared.case_dir / "ctrl.txt").read_text(encoding="utf-8")
        self.assertIn("B 92 2", ctrl_text)
        self.assertIn("N 41 3.000000", ctrl_text)
        self.assertIn("P 182 1.000000", ctrl_text)

    def test_prepare_from_celeris_files_syncs_m10_to_mpi_ranks(self) -> None:
        run_id = f"unit_celeris_mpi_{uuid.uuid4().hex}"
        uploads = self.make_small_celeris_uploads(RECE_ROOT / "tmp" / run_id)
        prepared = prepare_from_celeris_files(run_id, uploads, {"output_frames": 3, "mpi_ranks": 2})
        self.assertEqual(prepared.mpi_ranks, 2)
        self.assertEqual(read_m10_partition(prepared.case_dir / "control.txt"), 2)
        self.assertEqual(read_m10_partition(prepared.case_dir / "ctrl.txt"), 2)

    def test_prepare_from_celeris_files_accepts_full_hk_demo_grid_size(self) -> None:
        validate_grid(600, 400, 10.0, 10.0)

    def test_prepare_from_celeris_files_rejects_oversized_grid(self) -> None:
        run_id = f"unit_big_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        uploads = self.make_small_celeris_uploads(root)
        config = json.loads(uploads["config"].read_text(encoding="utf-8"))
        config["WIDTH"] = 1025
        uploads["config"].write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            prepare_from_celeris_files(run_id, uploads, {})

    def test_normalize_params_rejects_invalid_values(self) -> None:
        invalid_cases = [
            {"output_frames": 0},
            {"output_frames": 501},
            {"output_frames": "nan"},
            {"output_frames": 1.5},
            {"mpi_ranks": 0},
            {"mpi_ranks": 17},
            {"mpi_ranks": "abc"},
            {"wave_height": -0.1},
            {"wave_period": 0.0},
            {"output_interval": "bad"},
            {"wave_direction": float("inf")},
        ]
        for params in invalid_cases:
            with self.subTest(params=params):
                with self.assertRaises(ValueError):
                    normalize_params(params)

    def test_reef3d_args_select_single_rank_launcher_by_input_mode(self) -> None:
        celeris_args = JobManager()._reef3d_args(1, "celeris_files")
        self.assertEqual(Path(celeris_args[0]).name.lower(), "reef3d.exe" if PLATFORM == "windows" else "reef3d")
        native_args = JobManager()._reef3d_args(1, "reef3d_zip")
        self.assertIn("mpiexec", Path(native_args[0]).name.lower())
        self.assertEqual(native_args[1:3], ["-n", "1"])
        self.assertEqual(Path(native_args[3]).name.lower(), "reef3d.exe" if PLATFORM == "windows" else "reef3d")

    def test_reef3d_args_use_mpiexec_for_multi_rank(self) -> None:
        args = JobManager()._reef3d_args(2, "celeris_files")
        self.assertIn("mpiexec", Path(args[0]).name.lower())
        self.assertEqual(args[1:3], ["-n", "2"])
        self.assertEqual(Path(args[3]).name.lower(), "reef3d.exe" if PLATFORM == "windows" else "reef3d")

    def test_external_solver_env_filters_package_internal_path(self) -> None:
        internal = str(RESOURCE_ROOT)
        external = r"C:\Program Files\Microsoft MPI\Bin"
        original_path = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = os.pathsep.join([internal, str(RESOURCE_ROOT / "scipy"), external])
            env = _external_solver_env()
        finally:
            os.environ["PATH"] = original_path
        self.assertNotIn(internal, env["PATH"])
        self.assertNotIn(str(RESOURCE_ROOT / "scipy"), env["PATH"])
        self.assertIn(external, env["PATH"])

    def test_safe_extract_zip_rejects_traversal(self) -> None:
        root = RECE_ROOT / "tmp" / f"unit_zip_{uuid.uuid4().hex}"
        root.mkdir(parents=True, exist_ok=True)
        zip_path = root / "unsafe.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            zf.writestr("../geo.dat", "bad")
        with self.assertRaisesRegex(ValueError, "Unsafe zip member"):
            safe_extract_zip(zip_path, root / "extract")

    def test_prepare_from_reef3d_zip_accepts_case_package(self) -> None:
        run_id = f"unit_zip_case_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        source = root / "source_case"
        source.mkdir(parents=True, exist_ok=True)
        uploads = self.make_small_celeris_uploads(source)
        (source / "geo.dat").write_text("0 0 -4\n", encoding="utf-8")
        (source / "control.txt").write_text("C 11 6\nM 10 4\n", encoding="utf-8")
        (source / "ctrl.txt").write_text("A 10 5\nM 10 4\n", encoding="utf-8")
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        prepared = prepare_from_reef3d_zip(run_id, {"reef3d_zip": zip_path}, {})
        self.assertTrue((prepared.case_dir / "geo.dat").exists())
        self.assertTrue((prepared.assets_dir / "config.json").exists())
        self.assertEqual(prepared.mpi_ranks, 4)

    def test_prepare_from_reef3d_zip_rewrites_mpi_m10_when_requested(self) -> None:
        run_id = f"unit_zip_mpi_rewrite_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        source = root / "source_case"
        source.mkdir(parents=True, exist_ok=True)
        uploads = self.make_small_celeris_uploads(source)
        (source / "geo.dat").write_text("0 0 -4\n", encoding="utf-8")
        (source / "control.txt").write_text("C 11 6\nM 10 4\n", encoding="utf-8")
        (source / "ctrl.txt").write_text("A 10 5\nM 10 4\n", encoding="utf-8")
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        prepared = prepare_from_reef3d_zip(run_id, {"reef3d_zip": zip_path}, {"mpi_ranks": 2})
        self.assertEqual(prepared.mpi_ranks, 2)
        self.assertEqual(read_m10_partition(prepared.case_dir / "control.txt"), 2)
        self.assertEqual(read_m10_partition(prepared.case_dir / "ctrl.txt"), 2)

    def test_prepare_from_reef3d_zip_auto_mpi_rejects_m10_one(self) -> None:
        run_id = f"unit_zip_auto_mpi_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        source = root / "source_case"
        source.mkdir(parents=True, exist_ok=True)
        uploads = self.make_small_celeris_uploads(source)
        (source / "geo.dat").write_text("0 0 -4\n", encoding="utf-8")
        (source / "control.txt").write_text("C 11 6\nM 10 1\n", encoding="utf-8")
        (source / "ctrl.txt").write_text("A 10 5\nM 10 1\n", encoding="utf-8")
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        with self.assertRaisesRegex(ValueError, "M 10=1"):
            prepare_from_reef3d_zip(run_id, {"reef3d_zip": zip_path}, {"mpi_ranks": 4, "mpi_ranks_auto": True})

    def test_prepare_from_reef3d_zip_explicit_mpi_one_is_rejected(self) -> None:
        run_id = f"unit_zip_mpi_one_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        source = root / "source_case"
        source.mkdir(parents=True, exist_ok=True)
        uploads = self.make_small_celeris_uploads(source)
        (source / "geo.dat").write_text("0 0 -4\n", encoding="utf-8")
        (source / "control.txt").write_text("C 11 6\nM 10 4\n", encoding="utf-8")
        (source / "ctrl.txt").write_text("A 10 5\nM 10 4\n", encoding="utf-8")
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        with self.assertRaisesRegex(ValueError, "M 10=1"):
            prepare_from_reef3d_zip(run_id, {"reef3d_zip": zip_path}, {"mpi_ranks": 1})

    def test_prepare_from_reef3d_zip_rewrites_wave_and_output_params(self) -> None:
        run_id = f"unit_zip_params_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        source = root / "source_case"
        source.mkdir(parents=True, exist_ok=True)
        uploads = self.make_small_celeris_uploads(source)
        (source / "geo.dat").write_text("0 0 -4\n", encoding="utf-8")
        (source / "control.txt").write_text("C 11 6\nM 10 2\n", encoding="utf-8")
        (source / "ctrl.txt").write_text(
            "A 10 5\nB 90 1\nB 92 2\nB 93 0.200000 6.000000\nN 41 1.000000\nM 10 2\nP 180 1\nP 182 1.0\n",
            encoding="utf-8",
        )
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        prepared = prepare_from_reef3d_zip(
            run_id,
            {"reef3d_zip": zip_path},
            {"mpi_ranks": 2, "output_frames": 3, "output_interval": 1.0, "wave_height": 0.3, "wave_period": 8.0},
        )
        ctrl_text = (prepared.case_dir / "ctrl.txt").read_text(encoding="utf-8")
        self.assertIn("B 93 0.300000 8.000000", ctrl_text)
        self.assertIn("N 41 3.000000", ctrl_text)
        self.assertIn("P 182 1.000000", ctrl_text)
        waves_text = (prepared.assets_dir / "waves.txt").read_text(encoding="utf-8")
        self.assertIn("0.150000 8.000000", waves_text)


class RECEServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), RECEHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request_status(self, path: str) -> tuple[int, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path)
            response = conn.getresponse()
            body = response.read()
            return response.status, body
        finally:
            conn.close()

    def test_static_file_path_traversal_is_rejected(self) -> None:
        for path in ["/../README.md", "/%2e%2e/README.md"]:
            status, body = self.request_status(path)
            self.assertEqual(status, 404, body[:120])

    def test_frame_path_traversal_is_rejected(self) -> None:
        for path in [
            "/api/scenarios/hk_victoria_smoke/frames/../validation_report.json",
            "/api/scenarios/hk_victoria_smoke/frames/%2e%2e/validation_report.json",
        ]:
            status, body = self.request_status(path)
            self.assertEqual(status, 404, body[:120])

    def test_valid_manifest_and_frame_are_served(self) -> None:
        if not (RECE_ROOT / "examples" / "hk_victoria_smoke" / "frames_manifest.json").exists():
            self.skipTest("Precomputed Hong Kong smoke frames are not available in this checkout")
        status, _ = self.request_status("/api/scenarios/hk_victoria_smoke/manifest")
        self.assertEqual(status, 200)
        status, body = self.request_status("/api/scenarios/hk_victoria_smoke/frames/state_000000.bin")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 120 * 80 * 4 * 4)

    def test_run_frame_endpoint_accepts_manifest_relative_paths(self) -> None:
        run_id = f"unit_frame_{uuid.uuid4().hex}"
        run_dir = ensure_rece_write(CUSTOM_RUNS_ROOT / run_id)
        frames_dir = run_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        (frames_dir / "state_000000.bin").write_bytes(b"frame")
        job = {
            "id": run_id,
            "run_dir": str(run_dir),
            "assets_dir": str(run_dir / "assets"),
            "logs_dir": str(run_dir / "logs"),
            "status": "complete",
        }
        with MANAGER._lock:
            MANAGER._jobs[run_id] = job
        try:
            for frame_name in ["state_000000.bin", "frames/state_000000.bin"]:
                status, body = self.request_status(f"/api/runs/{run_id}/frames/{frame_name}")
                self.assertEqual(status, 200, frame_name)
                self.assertEqual(body, b"frame")
            for unsafe in ["frames/../state_000000.bin", "frames/C:/state_000000.bin"]:
                status, _ = self.request_status(f"/api/runs/{run_id}/frames/{unsafe}")
                self.assertEqual(status, 404, unsafe)
        finally:
            with MANAGER._lock:
                MANAGER._jobs.pop(run_id, None)


if __name__ == "__main__":
    unittest.main()
