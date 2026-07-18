# -*- mode: python ; coding: utf-8 -*-
import os
import sys
from pathlib import Path

os.environ.setdefault('PYTHONNOUSERSITE', '1')

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT / 'src'))

from xml_to_usda.qt_ui.release_build import PYINSTALLER_EXCLUDES, build_release_data_tree

STAGING_ROOT = REPO_ROOT / 'build-next' / 'qt_ui_data'
build_release_data_tree(
    source_ui_root=REPO_ROOT / 'src' / 'xml_to_usda' / 'qt_ui',
    staging_root=STAGING_ROOT,
    jpeg_quality=85,
)

datas = [(str(STAGING_ROOT), 'xml_to_usda/qt_ui')]


a = Analysis(
    ['D:\\3D Personal\\VibeCode\\XMLtoUSDAconverter\\scripts\\launch_qt_gui.py'],
    pathex=['D:\\3D Personal\\VibeCode\\XMLtoUSDAconverter\\src'],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=['D:\\3D Personal\\VibeCode\\XMLtoUSDAconverter\\hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=list(PYINSTALLER_EXCLUDES),
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpeedAssembly',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='D:\\3D Personal\\VibeCode\\XMLtoUSDAconverter\\src\\xml_to_usda\\qt_ui\\assets\\Icon.ico',
)
