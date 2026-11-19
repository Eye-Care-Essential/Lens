# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve()
datas = []
binaries = []
hiddenimports = collect_submodules("app")

# Provider clients are loaded lazily by app.ai.factory. Collect their modules and
# package data explicitly so the frozen build contains every provider's SDK.
for package in ("PySide6", "google.genai", "anthropic", "openai", "cv2"):
    package_datas, package_binaries, package_hiddenimports = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hiddenimports += package_hiddenimports

for distribution in (
    "PySide6",
    "google-genai",
    "anthropic",
    "openai",
    "numpy",
    "opencv-contrib-python-headless",
):
    datas += copy_metadata(distribution)

a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tkinter"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PriceLens",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ROOT / "assets" / "icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="PriceLens",
)
