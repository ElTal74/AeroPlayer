# -*- mode: python ; coding: utf-8 -*-
# Especificación de PyInstaller para AERO Player (modo carpeta: arranque más rápido que un único .exe).
# Uso:  pyinstaller packaging/aero.spec --noconfirm
# Windows: carpeta con AeroPlayer.exe · Linux: carpeta con el ejecutable AeroPlayer · macOS: AeroPlayer.app

import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - SPECPATH lo define PyInstaller
sys.path.insert(0, str(ROOT / "packaging"))
WIN, MAC = sys.platform == "win32", sys.platform == "darwin"
if WIN:
    from version_info import write  # noqa: E402 - información de versión del .exe
sys.path.insert(0, str(ROOT))
from aero import __version__  # noqa: E402

# Módulos de Qt que AERO Player no usa: excluirlos reduce cientos de MB.
QT_EXCLUDES = [
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel",
    "PySide6.QtWebSockets", "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras", "PySide6.QtCharts", "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtQuick3D", "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtPositioning",
    "PySide6.QtLocation", "PySide6.QtSensors", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtSql",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp", "PySide6.QtRemoteObjects", "PySide6.QtScxml",
    "PySide6.QtStateMachine", "PySide6.QtTextToSpeech", "PySide6.QtHttpServer", "PySide6.QtSpatialAudio",
    "PySide6.QtPdfQuick", "PySide6.QtQuickControls2", "PySide6.QtQuickWidgets", "PySide6.QtQml", "PySide6.QtQuick",
    "PySide6.QtOpenGLWidgets", "PySide6.QtUiTools", "PySide6.QtAxContainer", "PySide6.QtCanvasPainter",
    "tkinter", "unittest", "pydoc", "test",
]

a = Analysis(  # noqa: F821
    [str(ROOT / "aero" / "__main__.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "LICENSE"), "."), (str(ROOT / "NOTICE.md"), "."), (str(ROOT / "CHANGELOG.md"), "."), (str(ROOT / "THIRD_PARTY_NOTICES.md"), "."),
           (str(ROOT / "packaging" / "aeroarchive.ico"), "."),
           (str(ROOT / "aero" / "i18n" / "locales"), "aero/i18n/locales"),
           (str(ROOT / "packaging" / "icons"), "icons")],      # iconos .ico de las categorías para el Explorador
    # Módulos que se cargan bajo demanda (editores, OCR, PDF a editable): PyInstaller los encuentra al analizar
    # las importaciones dentro de funciones, pero se listan para que no dependa de ello.
    hiddenimports=["pypdfium2", "pypdfium2_raw", "openpyxl",
                   "docx", "pptx", "odf.opendocument", "PySide6.QtMultimediaWidgets",
                   "py7zr", "pyzipper", "Cryptodome", "pyppmd", "pybcj", "inflate64", "multivolumefile", "brotli",
                   "pycdlib", "aero.torrent.ui", "aero.torrent.engine", "aero.aero_core"]
                  + (["win32com.shell", "pythoncom", "pywintypes", "winrt.windows.media.ocr",
                      "winrt.windows.globalization", "winrt.windows.graphics.imaging", "winrt.windows.storage.streams",
                      "winrt.windows.foundation", "winrt.windows.foundation.collections", "aero.installer.ui",
                      "win32com.propsys"] if WIN else []),
    # pycdlib (LGPL-2.1) se incluye como archivos .py sueltos en _internal\pycdlib: se puede sustituir por otra
    # versión sin recompilar AERO Player, como pide la LGPL.
    module_collection_mode={"pycdlib": "py"},
    excludes=QT_EXCLUDES,
    noarchive=False,
    optimize=1,
)

# Quitar DLL/plugins de Qt pesados que no se usan (WebEngine, QML, Quick 3D...).
DROP = ("Qt6WebEngine", "QtWebEngineProcess", "Qt6Quick3D", "Qt63D", "Qt6Qml", "Qt6Quick", "Qt6Designer",
        "Qt6Charts", "Qt6Graphs", "Qt6DataVisualization", "Qt6Location", "Qt6Pdf Quick", "qtwebengine",
        "resources\\qtwebengine", "translations\\qtwebengine", "Qt6ShaderTools", "opengl32sw")
a.binaries = [b for b in a.binaries if not any(d.lower() in b[0].lower() for d in DROP)]
a.datas = [d for d in a.datas if not any(x.lower() in d[0].lower() for x in DROP)]
# Traducciones de Qt: solo español e inglés.
a.datas = [d for d in a.datas if "translations" not in d[0].lower() or any(t in d[0].lower() for t in ("_es.", "_en."))]
a.binaries = [b for b in a.binaries if "virtualkeyboard" not in b[0].lower()]

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AeroPlayer",
    icon=str(ROOT / "packaging" / ("aero.ico" if WIN else "aero.icns")),
    console=False,
    disable_windowed_traceback=False,
    version=str(write(ROOT / "build" / "version_app.txt", "AERO Player", "AeroPlayer", "AeroPlayer.exe")) if WIN else None,
)

coll = COLLECT(  # noqa: F821
    exe, a.binaries, a.datas,
    strip=False, upx=False,
    name="AeroPlayer",
)

if MAC:
    # Tipos de archivo que AERO Player ofrece abrir («Abrir con» del Finder)
    from aero.core.associations import CATEGORIES  # noqa: E402

    exts = sorted({e.lstrip(".") for c in CATEGORIES for e in c.exts})
    app = BUNDLE(  # noqa: F821
        coll,
        name="AeroPlayer.app",
        icon=str(ROOT / "packaging" / "aero.icns"),
        bundle_identifier="io.github.eltal74.aeroplayer",
        info_plist={
            "CFBundleName": "AERO Player",
            "CFBundleDisplayName": "AERO Player",
            "CFBundleShortVersionString": __version__,
            "CFBundleVersion": __version__,
            "NSHumanReadableCopyright": "© 2026 David Seva Gonzalvez. GPL-3.0-or-later",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "14.0",
            "CFBundleDocumentTypes": [{"CFBundleTypeName": "Archivo multimedia", "CFBundleTypeRole": "Viewer",
                                       "LSHandlerRank": "Alternate", "CFBundleTypeExtensions": exts}],
        },
    )
