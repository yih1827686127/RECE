# RECE

RECE is the HKUST-GZ / MHRF integration of Celeris-WebGPU, REEF3D, DIVEMesh, and a Python bridge service.

Workspace layout:

```powershell
D:\AAA\RECE              # integrated RECE project and build outputs
D:\AAA\Celeris-WebGPU    # original Celeris-WebGPU source, treated as read-only
D:\AAA\REEF3D            # original REEF3D / DIVEMesh source, treated as read-only
D:\AAA\hk_dtm_example    # Hong Kong open data, treated as read-only
```

## Windows Installer

### Install from GitHub / 从 GitHub 安装

**中文**：打开 GitHub Releases，下载 `RECE_Setup.exe`，双击运行安装程序。安装完成后，从桌面快捷方式或开始菜单启动 `RECE.exe`。如果启动器提示缺少 WebView2 Runtime 或 Microsoft MPI，请按提示安装对应运行时后重新打开 `RECE.exe`。

**English**: Open GitHub Releases, download `RECE_Setup.exe`, and run the installer. After installation, launch `RECE.exe` from the Desktop shortcut or the Start Menu. If the launcher reports that WebView2 Runtime or Microsoft MPI is missing, install the prompted runtime and start `RECE.exe` again.

The Windows installer produced by this repo is:

```powershell
D:\AAA\RECE\dist\installer\RECE_Setup.exe
```

After installation, users start RECE from the desktop or Start Menu shortcut:

```text
RECE.exe
```

`RECE.exe` starts the local Python RECE service, opens an independent WebView2 desktop window, and shuts down the service and active REEF3D jobs when the window closes. It does not require or open an external browser for normal use.

Installer policy:

- Includes Celeris-WebGPU runtime assets, REEF3D/DIVEMesh runtime binaries, RECE Python code, licenses, notices, and `source\RECE_corresponding_source.zip`.
- Does not include web example cases, REEF3D simulations, Hong Kong example data, precomputed frames, screenshots, browser profiles, or demo caches.
- Installed program resources are read-only. Logs, uploads, temporary files, custom runs, converted frames, and WebView2 profile data go under `%LOCALAPPDATA%\RECE`.
- The packaged UI hides fixed example workflows and exposes upload-based Celeris file / REEF3D case zip entry points.
- `RECE.exe` and `RECE_Setup.exe` use the current `art\icon0.png` as the application icon. The in-app top-left identity panel stacks the current `art\icon1.png` above the HKUST-GZ unit logo from `art\logo.png`, with responsive scaling and HKUST-GZ / MHRF rights text below.

Build the installer:

```powershell
cd D:\AAA\RECE
powershell -ExecutionPolicy Bypass -File packaging\build_installer.ps1
```

The build script uses `D:\AAA\tools\rece-build-venv` for the PyInstaller Python environment, `D:\AAA\tools\InnoSetup` for Inno Setup, and `D:\AAA\RECE\packaging\vendor` for WebView2 / MS-MPI prerequisite installers.

## Development Web App

For development, start the local web service:

```powershell
cd D:\AAA\RECE
python -m rece.server --host 127.0.0.1 --port 8787
```

Open:

```text
http://127.0.0.1:8787/
```

Development mode keeps the fixed Hong Kong smoke workflow and Celeris examples available. Package mode hides them.

## Runtime Modes

`rece.paths` selects paths by runtime mode:

- Development: resources and writes stay under `D:\AAA\RECE`.
- Package/frozen: resources are loaded from the install directory; writes go to `%LOCALAPPDATA%\RECE`.

Runtime status is available at:

```text
GET /api/runtime
```

Packaged exe self-check:

```powershell
D:\AAA\RECE\dist\RECE\RECE.exe --print-runtime
```

## Language And Solver Controls

The UI supports English and Chinese through the `Language` switch. The REEF3D runner panel, REEF3D job status messages, and REEF3D validation hints are translated with the rest of the app.

When `Solver Mode` is `REEF3D backend job`, Celeris-WebGPU is used as the renderer/player for external frames. Internal Celeris solver controls that no longer affect the REEF3D backend job are gray-locked with `aria-disabled="true"`. Clicking a locked control shows a bilingual hint telling the user to change REEF3D parameters in the REEF3D runner and submit a new backend job.

## REEF3D Upload Workflows

### Celeris-Style Custom Input

Upload:

- `config.json`
- `bathy.txt`
- optional `waves.txt`
- optional overlay image

Then set solver mode to `REEF3D backend job`, choose the Celeris upload mode, tune MPI/output/wave parameters, and run `Run Custom REEF3D Job`.

### Native REEF3D Case Zip

The zip must contain:

- `geo.dat`
- `control.txt`
- `ctrl.txt`
- `bathy.txt`
- either `config.json` or `rece_metadata.json`

`config.json` or `rece_metadata.json` must include at least `WIDTH`, `HEIGHT`, `dx`, `dy`, and `seaLevel`.

## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Local service health check. |
| `GET` | `/api/runtime` | Runtime mode, resource roots, package status, solver binary checks. |
| `POST` | `/api/runs` | Create a REEF3D job from uploaded Celeris files or a native REEF3D zip. |
| `GET` | `/api/runs/{id}/status` | Read phase, progress, frame count, logs, manifest/config URLs, and errors. |
| `GET` | `/api/runs/{id}/manifest` | Read the growing external-frame manifest. |
| `GET` | `/api/runs/{id}/frames/{name}` | Stream converted `state_*.bin` and `velocity_*.bin` frames. |
| `GET` | `/api/runs/{id}/assets/{name}` | Read generated `config.json`, `bathy.txt`, `waves.txt`, and overlay assets. |
| `POST` | `/api/runs/{id}/cancel` | Cancel a still-running custom REEF3D job. |

## Validation

Latest validation run on 2026-06-04:

```powershell
python -m unittest tests.test_rece -v
python -m rece.workflow validate
node --check web\js\main.js
node --check web\js\i18n.js
node --check web\js\Model_Loaders.js
node --check web\js\rece_runtime_mode.js
node --check automation\run_rece_packaged_runtime_cdp.mjs
node --check automation\run_rece_solver_modes_cdp.mjs
node --check automation\run_rece_core_matrix_cdp.mjs
node automation\run_rece_packaged_runtime_cdp.mjs
node automation\run_rece_solver_modes_cdp.mjs
node automation\run_rece_core_matrix_cdp.mjs
$env:RECE_CDP_WINDOW_SIZE='390,844'; node automation\run_rece_core_matrix_cdp.mjs; Remove-Item Env:\RECE_CDP_WINDOW_SIZE
D:\AAA\RECE\dist\RECE\RECE.exe --print-runtime
```

Results:

- Python unit tests: 18/18 passed.
- `python -m rece.workflow validate`: status `ok`, 5 Hong Kong smoke frames, expected frame bytes `153600`.
- Package-mode UI CDP test: passed.
- Solver-mode UI CDP test: passed, including CN REEF3D labels/status, REEF3D-mode Celeris control locks and hint toast, plus responsive stacked `art\icon1.png` / `art\logo.png` / HKUST-GZ-MHRF rights branding.
- Core matrix desktop viewport: 18/18 passed.
- Core matrix narrow viewport `390x844`: 18/18 passed.
- Packaged `RECE.exe --print-runtime`: package mode, resource root `dist\RECE\_internal`, examples unavailable, `reef3d.exe` and `DiveMESH.exe` found.
- Installer smoke: installed the rebuilt `RECE_Setup.exe` to `D:\AAA\RECE_test_install`, verified installed `_internal\scipy\_lib\_ccallback_c.cp312-win_amd64.pyd` plus the latest `rece-app.ico`, `rece-panel-logo.png`, and `hkust-gz-logo.png`, launched installed `RECE.exe --port 8793 --debug`, and passed package-mode UI CDP test with the final responsive stacked branding.
- The previous installed-startup SciPy `_ccallback_c` popup was fixed by lazy-loading the REEF3D converter from the job runner and by explicitly freezing SciPy's `scipy._lib._ccallback_c`, `_fpumode`, `messagestream`, and `scipy.spatial._ckdtree` modules.

The current global development Python environment still warns that SciPy expects `numpy<2.3` because it has NumPy `2.4.6`. The installer build uses the dedicated pinned environment at `D:\AAA\tools\rece-build-venv`, which installs NumPy `2.2.6` and avoids that freeze-time issue.

## License And Notices

RECE is distributed as a GPL-3.0 combined work because it includes and dispatches GPL-3.0-or-later REEF3D and DIVEMesh components. Celeris-WebGPU remains MIT licensed. See `LICENSE`, `THIRD_PARTY_NOTICES.md`, and the bundled corresponding source archive.
