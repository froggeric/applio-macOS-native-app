# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['models_installer.py'],
    pathex=[],
    binaries=[],
    datas=[('rvc/models', 'rvc/models')],
    hiddenimports=['Foundation', 'AppKit', 'requests', 'tqdm'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ApplioModelsInstaller',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=None,
    entitlements_file=None,
    icon=['assets/ICON.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ApplioModelsInstaller',
)
app = BUNDLE(
    coll,
    name='ApplioModelsInstaller.app',
    icon='assets/ICON.ico',
    bundle_identifier='com.iahispano.applio.models-installer',
)
