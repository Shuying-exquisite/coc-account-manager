# -*- mode: python ; coding: utf-8 -*-
import os
import sysconfig

# 自动探测构建环境的 site-packages（可用 COC_BUILD_SITE 环境变量覆盖）
SITE = os.environ.get('COC_BUILD_SITE') or sysconfig.get_paths().get('purelib', '')

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    # pythonnet / clr_loader / clr.py are shipped as REAL files (not frozen into
    # the archive) so their __file__-based lookup of Python.Runtime.dll and
    # ClrLoader.dll resolves to the on-disk folders next to the exe.
    datas=[
        ('appmods', 'appmods'),
        ('templates', 'templates'),
        ('app.ico', '.'),
        (os.path.join(SITE, 'pythonnet'), 'pythonnet'),
        (os.path.join(SITE, 'clr_loader'), 'clr_loader'),
        (os.path.join(SITE, 'clr.py'), '.'),
    ],
    hiddenimports=['flask', 'werkzeug', 'jinja2', 'markupsafe', 'itsdangerous', 'click', 'blinker', 'openpyxl', 'et_xmlfile', 'lxml', 'colorama', 'packaging', 'bottle', 'proxy_tools', 'typing_extensions', 'cffi', 'tkinter', 'tkinter.filedialog', 'tkinter.messagebox', 'tkinter.commondialog', 'tkinter.constants', 'tkinter.ttk'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Exclude from the archive; they are provided as real files via datas above.
    excludes=['pythonnet', 'clr_loader'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='COC_Account_Manager',
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
    contents_directory='.',
    icon='app.ico',
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='COC_Account_Manager',
)
