from __future__ import annotations

import http.client
import json
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
    prepare_from_celeris_files,
    prepare_from_reef3d_zip,
    safe_extract_zip,
)
from rece.hk_prepare import Tile, cached_or_downloaded_tifs, find_one, prepare_hk_smoke, select_dtm_tiles
from rece.paths import DATA_ROOT, RECE_ROOT, ensure_allowed_read, ensure_rece_write
from rece.server import RECEHandler
from rece.workflow import convert_meander_for_test


class RECEPathTests(unittest.TestCase):
    def test_write_guard_accepts_rece(self) -> None:
        self.assertTrue(str(ensure_rece_write(RECE_ROOT / "tmp" / "guard.txt")).endswith("guard.txt"))

    def test_write_guard_rejects_outside(self) -> None:
        with self.assertRaises(ValueError):
            ensure_rece_write(DATA_ROOT / "not-a-write-target.txt")

    def test_read_guard_accepts_data(self) -> None:
        self.assertEqual(ensure_allowed_read(DATA_ROOT), DATA_ROOT.resolve())


class RECEPrepareTests(unittest.TestCase):
    def test_prepare_hk_smoke_outputs_core_files(self) -> None:
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

    def test_prepare_from_celeris_files_rejects_oversized_grid(self) -> None:
        run_id = f"unit_big_{uuid.uuid4().hex}"
        root = RECE_ROOT / "tmp" / run_id
        uploads = self.make_small_celeris_uploads(root)
        config = json.loads(uploads["config"].read_text(encoding="utf-8"))
        config["WIDTH"] = 513
        uploads["config"].write_text(json.dumps(config), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            prepare_from_celeris_files(run_id, uploads, {})

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
        (source / "control.txt").write_text("C 11 6\n", encoding="utf-8")
        (source / "ctrl.txt").write_text("A 10 5\n", encoding="utf-8")
        zip_path = root / "case.zip"
        with zipfile.ZipFile(zip_path, "w") as zf:
            for path in [source / "geo.dat", source / "control.txt", source / "ctrl.txt", uploads["config"], uploads["bathy"]]:
                zf.write(path, arcname=path.name)
        prepared = prepare_from_reef3d_zip(run_id, {"reef3d_zip": zip_path}, {})
        self.assertTrue((prepared.case_dir / "geo.dat").exists())
        self.assertTrue((prepared.assets_dir / "config.json").exists())


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
        status, _ = self.request_status("/api/scenarios/hk_victoria_smoke/manifest")
        self.assertEqual(status, 200)
        status, body = self.request_status("/api/scenarios/hk_victoria_smoke/frames/state_000000.bin")
        self.assertEqual(status, 200)
        self.assertEqual(len(body), 120 * 80 * 4 * 4)


if __name__ == "__main__":
    unittest.main()
