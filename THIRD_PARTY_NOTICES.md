# RECE third-party notices

RECE is an integration project by Hong Kong University of Science and Technology (Guangzhou) / HKUST-GZ, Marine Hydrodynamic Research Facility (MHRF), 2026.

The distributable RECE combination is licensed under GPL-3.0 because it includes and orchestrates GPL-licensed REEF3D and DIVEMesh components. See `LICENSE` for the GPL-3.0 text.

## RECE integration

- Copyright (C) 2026 Hong Kong University of Science and Technology (Guangzhou) / HKUST-GZ.
- Unit: MHRF, Marine Hydrodynamic Research Facility.
- License: GPL-3.0 for the integrated RECE distribution.

## Celeris-WebGPU

- Role in RECE: WebGPU visualization, texture/render pipeline, UI controls, time-series plots, and export paths.
- Upstream copyright: Copyright (c) 2023 plynett; Celeris-WebGPU is maintained by Patrick Lynett, University of Southern California.
- Upstream license: MIT License.
- License text preserved at `web/LICENSE`.
- README acknowledgments preserved for the original Celeris project by Sasan Tavakkol under Patrick Lynett, with support from USACE ERDC, ONR, and NSF.

## REEF3D

- Role in RECE: external hydrodynamic solver.
- Upstream copyright: Copyright 2008-2026 Hans Bihs.
- Upstream license: GNU General Public License, version 3 or later.
- License text preserved at `third_party/REEF3D/src/REEF3D/LICENSE`.
- Source headers state that REEF3D is free software under GPL-3.0-or-later and carries no warranty.

## DIVEMesh

- Role in RECE: mesh generation for REEF3D cases.
- Upstream copyright: Copyright 2008-2026 Hans Bihs.
- Upstream license: GNU General Public License, version 3 or later.
- License text preserved at `third_party/REEF3D/src/DIVEMesh/LICENSE`.
- Source headers state that DIVEMesh is free software under GPL-3.0-or-later and carries no warranty.

## Additional bundled third-party code

Some copied upstream trees contain their own third-party dependencies, including Eigen and browser automation binaries. Their license files are retained in-place under the copied upstream directories, including `third_party/REEF3D/src/REEF3D/ThirdParty/` and `web/automation/`.

## Localized web runtime libraries

The packaged UI uses local copies of browser libraries instead of CDN/runtime network dependencies:

- `web/externals/chart.umd.js`: Chart.js, MIT License.
- `web/externals/gif.js` and `web/externals/gif.worker.js`: gif.js, MIT License.
- `web/externals/gl-matrix/`: gl-matrix, MIT License.
- `web/externals/geotiff.js`: geotiff.js, BSD-style license as distributed upstream.

## Python desktop/runtime dependencies

The Windows executable is frozen with PyInstaller from the dedicated build environment under `D:\AAA\tools\rece-build-venv`. The bundled Python runtime includes permissively licensed scientific, networking, and desktop-window libraries used by RECE, including NumPy, SciPy, Pillow, Requests and its dependencies, VTK, pywebview, pythonnet, clr_loader, cffi, bottle, and proxy_tools. Their package metadata and license files are retained in the frozen package where provided by the wheels.

## Runtime prerequisite installers

The installer may include prerequisite installers under `_internal/vendor/`:

- `MicrosoftEdgeWebView2Setup.exe`: Microsoft Edge WebView2 Runtime installer.
- `msmpisetup.exe`: Microsoft MPI Runtime installer.

These prerequisite installers are provided so a target Windows system can launch the WebView2 desktop shell and REEF3D MPI jobs. Their upstream license and redistribution terms remain those of Microsoft.

## Distribution note

If RECE is conveyed outside the original internal workspace, provide the corresponding source for the GPL-covered combination and keep these license notices with the distribution.
