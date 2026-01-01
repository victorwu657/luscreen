# -*- mode: python ; coding: utf-8 -*-
import sys
import os
from PyInstaller.utils.hooks import collect_all
import imageio_ffmpeg

block_cipher = None

# 获取 ffmpeg 路径
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

# 收集 hidden imports
hiddenimports = [
    'pynput.keyboard._win32',
    'pynput.mouse._win32',
    'imageio_ffmpeg',
    'soundcard',
    'mss',
    'cv2',
    'numpy',
    'PIL',
]

# 资源文件
datas = [
    ('assets', 'assets'),
]

# 二进制文件
binaries = [
    (ffmpeg_path, '.'), # 放在根目录
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
    name='LuScreen',
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
    icon='assets/icon.png',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='LuScreen',
)