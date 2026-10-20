# -*- mode: python ; coding: utf-8 -*-


from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata
from pathlib import Path
import os
import sys


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

INCLUDE_USER_CONFIG = os.environ.get('TIMERAUTO_INCLUDE_USER_CONFIG', '').lower() in ('1', 'true', 'yes', 'on')
INCLUDE_PLAYER_IMAGES = os.environ.get('TIMERAUTO_INCLUDE_PLAYER_IMAGES', '').lower() in ('1', 'true', 'yes', 'on')

hiddenimports = []
hiddenimports += _try_collect('rapidfuzz')
hiddenimports += _try_collect('pyautogui')
hiddenimports += _try_collect('pyscreeze')
hiddenimports += _try_collect('pygetwindow')
hiddenimports += _try_collect('mouseinfo')
hiddenimports += _try_collect('edge_tts')
hiddenimports += _try_collect('aiohttp')

datas_extra = []
datas_extra += _try_collect_data('rapidfuzz')
datas_extra += _try_collect_data('pyautogui')
datas_extra += _try_collect_data('pyscreeze')
datas_extra += _try_collect_data('pygetwindow')
datas_extra += _try_collect_data('mouseinfo')
datas_extra += _try_collect_data('edge_tts')
datas_extra += _try_collect_data('aiohttp')
datas_extra += _try_collect_data('certifi')
# Preserve dependency identities in diagnostics from frozen builds too.
for line in Path('requirements-release.lock').read_text(encoding='utf-8').splitlines():
    if line.strip() and not line.lstrip().startswith('#'):
        datas_extra += copy_metadata(line.split('==', 1)[0].strip())

datas_base = [
    ('HELP.md', '.'),
    ('timer_ui.qml', '.'),
    ('cinematic_overlay.qml', '.'),
    ('timer_controls.qml', '.'),
    ('assets', 'assets'),
]
if INCLUDE_USER_CONFIG:
    for optional_file in ('config.json', 'profile.json'):
        if Path(optional_file).exists():
            datas_base.append((optional_file, '.'))

if INCLUDE_PLAYER_IMAGES and Path('image/players').exists():
    datas_base.append(('image/players', 'image/players'))

a = Analysis(
    ['timerauto.py'],
    pathex=['.'],
    binaries=[],
    datas=datas_base + datas_extra,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
# Refuse ambient DLL contamination even if another hook expands its search path.
allowed_binary_roots = [Path(sys.prefix).resolve(), Path(sys.base_prefix).resolve(),
                        Path(os.environ['SystemRoot']).resolve(), Path('.').resolve()]
for destination, source, kind in a.binaries:
    source_path = Path(source).resolve()
    if not any(source_path.is_relative_to(root) for root in allowed_binary_roots):
        raise RuntimeError(f'Uncontrolled native dependency: {destination} <- {source}')
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
