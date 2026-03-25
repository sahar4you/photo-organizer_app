# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Photo Organizer scanner.
Bundles scanner.py + duplicate_detector.py with all dependencies
into a single portable executable.

Build command: pyinstaller scanner.spec
"""

import sys
import os

block_cipher = None

# Collect data files needed by OpenCV (Haar cascades)
from PyInstaller.utils.hooks import collect_data_files
cv2_data = collect_data_files('cv2')

a = Analysis(
    ['scanner.py'],
    pathex=[],
    binaries=[],
    datas=cv2_data,
    hiddenimports=[
        'duplicate_detector',
        'PIL',
        'PIL.Image',
        'PIL.ExifTags',
        'cv2',
        'numpy',
        'sklearn',
        'sklearn.cluster',
        'sklearn.cluster._agglomerative',
        'imagehash',
        'scipy',
        'scipy.fftpack',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='scanner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
