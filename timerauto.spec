# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import collect_submodules, collect_data_files, collect_dynamic_libs
from pathlib import Path


def _try_collect(name):
    try:
        return collect_submodules(name)
    except Exception:
        return []

def _try_collect_data(name):
    try:
        return collect_data_files(name)
    except Exception:
        return []

def _try_collect_libs(name):
    try:
        return collect_dynamic_libs(name)
    except Exception:
        return []


hiddenimports = []
hiddenimports += _try_collect('easyocr')
hiddenimports += _try_collect('torch')
hiddenimports += _try_collect('torchvision')
hiddenimports += _try_collect('rapidfuzz')
hiddenimports += _try_collect('pyautogui')
hiddenimports += _try_collect('pyscreeze')
hiddenimports += _try_collect('pygetwindow')
hiddenimports += _try_collect('mouseinfo')
hiddenimports += _try_collect('edge_tts')
hiddenimports += _try_collect('aiohttp')

datas_extra = []
datas_extra += _try_collect_data('easyocr')
datas_extra += _try_collect_data('torch')
datas_extra += _try_collect_data('torchvision')
datas_extra += _try_collect_data('rapidfuzz')
datas_extra += _try_collect_data('pyautogui')
datas_extra += _try_collect_data('pyscreeze')
datas_extra += _try_collect_data('pygetwindow')
datas_extra += _try_collect_data('mouseinfo')
datas_extra += _try_collect_data('edge_tts')
datas_extra += _try_collect_data('aiohttp')
datas_extra += _try_collect_data('certifi')

binaries_extra = []
binaries_extra += _try_collect_libs('torch')
binaries_extra += _try_collect_libs('torchvision')

datas_base = [
    ('HELP.md', '.'),
    ('timer_ui.qml', '.'),
    ('cinematic_overlay.qml', '.'),
    ('timer_controls.qml', '.'),
    ('image', 'image'),
]
for optional_file in ('config.json', 'profile.json'):
    if Path(optional_file).exists():
        datas_base.append((optional_file, '.'))

a = Analysis(
    ['timerauto.py'],
    pathex=['.'],
    binaries=binaries_extra,
    datas=datas_base + datas_extra,
    hiddenimports=hiddenimports,
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
    name='timerauto',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name='timerauto',
)
