# -*- mode: python ; coding: utf-8 -*-
# Instalador propio de AERO Player: un único .exe con la interfaz de cristal y el programa comprimido dentro.
# Requiere antes:  pyinstaller packaging/aero.spec  y  python packaging/make_payload.py
# Uso:  pyinstaller packaging/setup.spec --noconfirm --distpath dist --workpath build

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH lo define PyInstaller
sys.path.insert(0, str(ROOT / "packaging"))
from version_info import app_version, write  # noqa: E402

VERSION = app_version()
PAYLOAD = ROOT / "build" / "payload"
if not (PAYLOAD / "payload.tar.xz").is_file():
    raise SystemExit("Falta build/payload/payload.tar.xz: ejecuta packaging/make_payload.py")

# El instalador solo necesita Qt Core/Gui/Widgets/Svg/Network: todo lo demás fuera.
EXCLUDES = [
    "numpy", "PIL", "py7zr", "pyzipper", "Cryptodome", "Crypto", "openpyxl", "docx", "pptx", "odf", "pypdfium2",
    "pypdfium2_raw", "winrt", "brotli", "pyppmd", "pybcj", "inflate64", "multivolumefile", "lxml", "tkinter",
    "unittest", "pydoc", "test", "xmlrpc", "sqlite3", "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtOpenGL", "PySide6.QtOpenGLWidgets", "PySide6.QtCharts",
    "PySide6.QtSql", "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.Qt3DCore",
    "PySide6.QtConcurrent", "PySide6.QtPrintSupport", "PySide6.QtXml", "PySide6.QtDBus", "PySide6.QtHelp",
    "PySide6.QtSpatialAudio", "PySide6.QtTextToSpeech", "PySide6.QtQuickWidgets", "PySide6.QtCanvasPainter",
    "aero.player", "aero.editors", "aero.archive", "aero.files", "aero.ui.pages.converter_page",
    "pillow_heif", "python_calamine", "ssl", "_ssl", "_hashlib", "win32ui", "pythonwin", "win32uiole", "dde",
    "_decimal", "decimal", "_zstd", "compression.zstd", "http", "urllib.request", "email", "xml", "pyexpat",
    "mutagen", "psutil", "comtypes", "asyncio", "multiprocessing", "concurrent", "ctypes.test",
]
KEEP_QT = ("qt6core", "qt6gui", "qt6widgets", "qt6svg", "qt6network", "qwindows", "qsvg", "qico", "pyside6",
           "shiboken6", "msvcp", "vcruntime", "concrt", "ucrt", "api-ms-win",
           "qtcore.", "qtgui.", "qtwidgets.", "qtsvg.", "qtnetwork.")  # módulos de PySide6 (.pyd)

a = Analysis(  # noqa: F821
    [str(ROOT / "packaging" / "setup_main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(PAYLOAD / "payload.tar.xz"), "payload"), (str(PAYLOAD / "manifest.json"), "payload"),
           (str(ROOT / "LICENSE"), "."), (str(ROOT / "aero" / "i18n" / "locales"), "aero/i18n/locales")],
    hiddenimports=["win32com.shell", "win32com.propsys", "pythoncom", "pywintypes", "PySide6.QtNetwork",
                   "PySide6.QtSvg"],
    excludes=EXCLUDES,
    noarchive=False,
    optimize=1,
)


def _keep(name: str) -> bool:
    n = name.lower().replace("\\", "/")
    if "pyside6" not in n and "qt6" not in n and "/plugins/" not in n:
        return True
    base = n.rsplit("/", 1)[-1]
    if "/translations/" in n:
        return base.endswith("_es.qm")
    return any(k in base for k in KEEP_QT)


# OpenSSL: QtNetwork solo se usa para el socket local con AERO Player (sin TLS).
a.binaries = [b for b in a.binaries if _keep(b[0]) and not b[0].lower().startswith(("libcrypto", "libssl"))]
a.datas = [d for d in a.datas if _keep(d[0]) or d[0].replace("\\", "/").startswith(("payload", "LICENSE",
                                                                                     "aero/i18n"))]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=f"AeroPlayer-{VERSION}-setup",
    icon=str(ROOT / "packaging" / "aero.ico"),
    console=False,
    disable_windowed_traceback=False,
    upx=False,
    runtime_tmpdir=None,
    version=str(write(ROOT / "build" / "version_setup.txt", "Instalador de AERO Player", "AeroPlayerSetup",
                      f"AeroPlayer-{VERSION}-setup.exe")),
)
