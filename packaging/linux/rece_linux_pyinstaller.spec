# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules


root = Path(SPECPATH).parents[1]
resources = root / "build" / "linux-package" / "resources"

datas = []
for name in ["web", "third_party", "licenses", "source"]:
    path = resources / name
    if path.exists():
        datas.append((str(path), name))

datas += collect_data_files("webview")
datas += collect_data_files("gi")


def collect_optional_submodules(*packages):
    collected = []
    for package in packages:
        try:
            collected += collect_submodules(package)
        except Exception:
            pass
    return collected


hiddenimports = []
webview_excluded_prefixes = (
    "webview.platforms.android",
    "webview.platforms.cef",
    "webview.platforms.cocoa",
    "webview.platforms.edgechromium",
    "webview.platforms.mshtml",
    "webview.platforms.qt",
)
hiddenimports += [
    name
    for name in collect_submodules("webview")
    if not name.startswith(webview_excluded_prefixes)
]
hiddenimports += collect_submodules("gi")
hiddenimports += collect_optional_submodules(
    "backports",
    "importlib_metadata",
    "jaraco",
    "more_itertools",
    "packaging",
    "platformdirs",
    "zipp",
)

hiddenimports += [
    "PIL.Image",
    "PIL.ImageDraw",
    "cairo",
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
    "clr_loader",
    "pythonnet",
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
