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
        ('assets', 'assets'),
        # GITHASH is written by build-macos-app.sh before PyInstaller runs.
        # Conditional so a bare `pyinstaller SimGUI.spec` still works without it.
        *([('GITHASH', '.')] if os.path.exists('GITHASH') else []),
    ],
    hiddenimports=[
        'smartcard',
        'smartcard.scard',
        'smartcard.scard._scard',
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
    [],
    exclude_binaries=True,
    name='SimGUI',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Disable UPX to avoid bytecode issues
    upx_exclude=[],
    console=False,  # No console window on macOS
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SimGUI',
)

app = BUNDLE(
    coll,
    name='SimGUI.app',
    icon=None,  # Set icon path if available: 'assets/icon.icns'
    bundle_identifier='com.fiskarheden.simgui',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
    },
)
