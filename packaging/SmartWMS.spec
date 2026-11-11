# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec（macOS 专用，Windows 用 packaging/build_windows.bat）。

输出：dist/SmartWMS.app
"""

import os

project_root = os.path.abspath(os.path.join(SPECPATH, ".."))

datas = [
    (os.path.join(project_root, "data", "sample"), "data/sample"),
    (os.path.join(project_root, "assets"), "assets"),
]

hiddenimports = [
    "matplotlib.backends.backend_qtagg",
    "PySide6.QtSvg",
]

a = Analysis(
    [os.path.join(project_root, "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas",
        "tkinter",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebEngineQuick",
        "PySide6.QtQuick",
        "PySide6.QtQml",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="SmartWMS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="SmartWMS",
)

app = BUNDLE(
    coll,
    name="SmartWMS.app",
    icon=os.path.join(project_root, "assets", "icon.icns"),
    bundle_identifier="com.sbtstudio.smartwms",
    info_plist={
        "CFBundleName": "SmartWMS",
        "CFBundleDisplayName": "智能仓储管理系统",
        "CFBundleShortVersionString": "1.0.2",
        "CFBundleVersion": "1.0.2",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Copyright © 2026 SBTstudio",
    },
)
