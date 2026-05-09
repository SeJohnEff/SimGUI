# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for SimGUI macOS .app bundle

import sys
import os

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[os.getcwd()],
    binaries=[],
    datas=[
        ('simulator/data', 'simulator/data'),
        ('assets', 'assets'),
    ],
    hiddenimports=[
        'smartcard',
        'smartcard.scard',
        '_smartcard',
        'tkinter',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludedimports=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='SimGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX to avoid bytecode issues
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # No console window on macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name='SimGUI.app',
    icon=None,  # Set icon path if available: 'assets/icon.icns'
    bundle_identifier='com.fiskarheden.simgui',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
    },
)
