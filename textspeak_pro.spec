# PyInstaller spec for TextSpeak Pro.  (C) 2026 JojoLapin Inc.
# Build with: `pyinstaller --noconfirm textspeak_pro.spec`  (or use build_exe.py).

# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_dynamic_libs

import glob
import importlib.util

# SPECPATH is injected by PyInstaller and always points at the folder holding
# this spec file, regardless of where pyinstaller was invoked from.
try:
    ROOT = Path(SPECPATH)  # type: ignore[name-defined]
except NameError:  # when the spec is imported for static analysis
    ROOT = Path(os.getcwd())

ICON_ICO = ROOT / 'resources' / 'icon.ico'
ICON_PNG = ROOT / 'resources' / 'icon.png'
VERSION_FILE = ROOT / 'resources' / 'version_info.txt'

# ---------------------------------------------------------------------------
# Native dependencies that PyInstaller cannot discover by following imports.
#
# * piper 1.3+ ships:
#     - espeakbridge.pyd            (native phonemizer extension)
#     - espeak-ng-data/*            (~119 linguistic data files, loaded via
#                                    Path(__file__).parent / 'espeak-ng-data')
#     - tashkeel/model.onnx + maps  (Arabic diacritizer)
#     - train/__main__.py           (Python-only but imports from dynamic paths)
#   Without all of these bundled next to piper/__init__.py, calling
#   PiperVoice.load(...) succeeds but synthesize() crashes the moment a voice
#   tries to phonemize text.
#
# * onnxruntime has native DLLs under onnxruntime/capi/*.dll that PyInstaller
#   only picks up via its hook - collect_all() guarantees they travel.
# ---------------------------------------------------------------------------
piper_datas, piper_binaries, piper_hidden = collect_all('piper')
onnx_datas, onnx_binaries, onnx_hidden = collect_all('onnxruntime')

# collect_all() uses collect_dynamic_libs() internally, which on Windows only
# picks up '.dll' files - but piper's native extension is espeakbridge.pyd.
# We add it explicitly so it lands next to piper/__init__.py in the frozen app.
_piper_spec = importlib.util.find_spec('piper')
if _piper_spec and _piper_spec.origin:
    _piper_dir = os.path.dirname(_piper_spec.origin)
    for _pyd in glob.glob(os.path.join(_piper_dir, 'espeakbridge*.pyd')) + \
                glob.glob(os.path.join(_piper_dir, 'espeakbridge*.so')) + \
                glob.glob(os.path.join(_piper_dir, 'espeakbridge*.dylib')):
        piper_binaries.append((_pyd, 'piper'))
    # Make sure PyInstaller treats it as imported even though the import is
    # lazy ("from . import espeakbridge" inside a method)
    piper_hidden.extend(['piper.espeakbridge', 'piper.phonemize_espeak',
                         'piper.phonemize_chinese', 'piper.voice', 'piper.tashkeel'])

# ---------------------------------------------------------------------------
# Bundled app resources.
# ---------------------------------------------------------------------------
datas = [
    (str(ROOT / 'ui' / 'index.html'),           'ui'),
    (str(ROOT / 'ui' / 'app.js'),               'ui'),
    (str(ROOT / 'ui' / 'i18n.js'),              'ui'),
    (str(ROOT / 'ui' / 'lib' / 'text-chunker.js'), 'ui/lib'),
    (str(ROOT / 'ui' / 'lib' / 'piper-reader.js'), 'ui/lib'),
    (str(ROOT / 'ui' / 'lib' / 'tabs.js'),         'ui/lib'),
    (str(ROOT / 'voice_catalog.json'),          '.'),
    (str(ROOT / 'resources' / 'icon.png'),      'resources'),
]
if ICON_ICO.exists():
    datas.append((str(ICON_ICO), 'resources'))

datas += piper_datas + onnx_datas
binaries = piper_binaries + onnx_binaries

hiddenimports = [
    'PySide6.QtCore',
    'PySide6.QtGui',
    'PySide6.QtWidgets',
    'PySide6.QtWebChannel',
    'PySide6.QtWebEngineCore',
    'PySide6.QtWebEngineWidgets',
    'mutagen.easyid3',
    'mutagen.id3',
    'mutagen.mp3',
    'lameenc',
    'requests',
    'pypdf',
] + piper_hidden + onnx_hidden

block_cipher = None

a = Analysis(
    [str(ROOT / 'main.py')],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'PyQt5', 'PyQt6', 'matplotlib', 'numpy.testing'],
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
    name='TextSpeakPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_ICO) if ICON_ICO.exists() else str(ICON_PNG) if ICON_PNG.exists() else None,
    version=str(VERSION_FILE) if VERSION_FILE.exists() else None,
)
