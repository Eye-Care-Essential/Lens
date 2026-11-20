# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_all, copy_metadata


ROOT = Path(SPECPATH).resolve()
datas = []
binaries = []
hiddenimports = [
    "app.ai.anthropic_provider",
    "app.ai.gemini_provider",
    "app.ai.openai_provider",
]

# Let PyInstaller's Qt and OpenCV hooks collect the imported modules, camera
# plugins, and native barcode dependencies. Collecting all of PySide6 would
# also ship unused components such as Qt WebEngine, QML, and PDF.
for package in ("google.genai", "anthropic", "openai"):
    package_datas, package_binaries, package_hiddenimports = collect_all(
        package,
        include_py_files=False,
    )
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
