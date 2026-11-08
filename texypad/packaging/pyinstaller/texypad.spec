# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder bundle for Texypad."""

from pathlib import Path

project_root = Path(SPECPATH).resolve().parents[2]
program_root = project_root / "texypad"
source = program_root / "app.py"

datas = [
    (str(program_root / "assets"), "assets"),
    (str(program_root / "docs"), "docs"),
    (str(program_root / "packaging" / "appimage" / "styles"), "packaging/appimage/styles"),
]

hiddenimports = [
    "PyQt6.QtPdf",
    "PyQt6.QtPdfWidgets",
]

a = Analysis(
    [str(source)],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PySide2", "PySide6", "PyQt5"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="texypad",
    icon=str(program_root / "assets" / "icons" / "texypad.png"),
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
    name="texypad",
)
