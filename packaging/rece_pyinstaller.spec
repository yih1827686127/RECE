# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


root = Path(SPECPATH).parent
resources = root / "build" / "package" / "resources"

datas = []
for name in ["web", "third_party", "licenses", "source", "vendor"]:
    path = resources / name
    if path.exists():
        datas.append((str(path), name))

datas += collect_data_files("webview")

hiddenimports = []
webview_excluded_prefixes = (
    "webview.platforms.android",
    "webview.platforms.cef",
    "webview.platforms.cocoa",
    "webview.platforms.gtk",
    "webview.platforms.qt",
)
hiddenimports += [
    name
    for name in collect_submodules("webview")
    if not name.startswith(webview_excluded_prefixes)
]
for package in ["clr_loader", "pythonnet"]:
    hiddenimports += collect_submodules(package)

hiddenimports += [
    "PIL.Image",
    "PIL.ImageDraw",
    "numpy",
    "scipy",
    "scipy._lib._ccallback_c",
    "scipy._lib._fpumode",
    "scipy._lib.messagestream",
    "scipy.spatial._ckdtree",
    "vtkmodules.util.numpy_support",
    "vtkmodules.vtkCommonCore",
    "vtkmodules.vtkCommonDataModel",
    "vtkmodules.vtkCommonExecutionModel",
    "vtkmodules.vtkIOCore",
    "vtkmodules.vtkIOXML",
]

excludes = [
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "IPython",
    "Cython",
    "jax",
    "jaxlib",
    "matplotlib",
    "ml_dtypes",
    "numba",
    "onnxruntime",
    "pandas",
    "sklearn",
    "tensorflow",
    "torch",
    "torchvision",
]


a = Analysis(
    [str(root / "packaging" / "rece_desktop_entry.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RECE",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(root / "web" / "assets" / "rece-app.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="RECE",
)
