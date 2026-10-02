# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from importlib.util import find_spec
import sys
sys.path.insert(0, SPECPATH)
from check_runtime import check
check()
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [(str(Path(SPECPATH) / 'assets'), 'assets')]
binaries = []
hiddenimports = []
datas += collect_data_files('certifi')
datas += collect_data_files('tkinterdnd2')
if find_spec('kaldi_native_fbank'):
    optional_data, optional_bins, optional_imports = collect_all('kaldi_native_fbank')
    datas += optional_data
    binaries += optional_bins
    hiddenimports += optional_imports
datas += copy_metadata('tqdm')
datas += copy_metadata('huggingface-hub')
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('av')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


for package in ('torch', 'transformers'):
    package_data, package_bins, package_imports = collect_all(package)
    datas += package_data
    binaries += package_bins
    hiddenimports += package_imports
for distribution in ('torch', 'transformers'):
    datas += copy_metadata(distribution, recursive=True)

a = Analysis(
    [str(Path(SPECPATH) / 'prepis.py')],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tensorflow'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ND TranskripThor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    version=str(Path(SPECPATH) / 'version_info.txt'),
    icon=str(Path(SPECPATH) / 'assets/transkripthor.ico'),
    manifest=str(Path(SPECPATH) / 'transkripthor.manifest'),
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
    name='ND TranskripThor',
)

