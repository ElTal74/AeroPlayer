"""Punto de entrada: instancia única, preferencias, tema y selección del modo de ventana."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

os.environ.setdefault("QT_LOGGING_RULES", "qt.multimedia.*=false")
os.environ.setdefault("QT_FFMPEG_DEBUG", "0")

from PySide6.QtCore import QDir, QLockFile, Qt  # noqa: E402
from PySide6.QtGui import QFont, QIcon  # noqa: E402
from PySide6.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from aero import APP_ID, APP_NAME, __version__  # noqa: E402

# AERO_INSTANCE solo lo usan las pruebas para no hablar con la instancia real del usuario
SERVER_NAME = f"{APP_ID}-{getpass.getuser()}{os.environ.get('AERO_INSTANCE', '')}"


def _send_to_running(msg: dict) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(300):
        return False
    sock.write(json.dumps(msg).encode("utf-8"))
    sock.flush()
    sock.waitForBytesWritten(1000)
    sock.disconnectFromServer()
    return True


def _diagnostico(path: str) -> int:
    """Estado de la instalación para soporte y pruebas del paquete compilado (no abre ventanas)."""
    import json
    import platform

    from aero.core import native
    from aero.ui import icon_export

    nc = native.core()
    icons = icon_export.icons_dir()
    import importlib.util

    modules = {m: importlib.util.find_spec(f"PySide6.{m}") is not None
               for m in ("QtPdf", "QtPdfWidgets", "QtMultimedia", "QtMultimediaWidgets")}
    data = {
        "qt_modulos": modules, "qt_completo": all(modules.values()),
        "version": __version__, "python": platform.python_version(), "frozen": bool(getattr(sys, "frozen", False)),
        "nativo": nc is not None, "nativo_version": nc.version() if nc else "",
        "nativo_archivo": getattr(nc, "__file__", "") if nc else "",
        "iconos": str(icons), "iconos_ico": sorted(p.stem for p in icons.glob("*.ico")) if icons.exists() else [],
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=1)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aero", description=f"{APP_NAME} {__version__}")
    parser.add_argument("paths", nargs="*", help="archivos o carpetas a abrir")
    parser.add_argument("--full", action="store_true", help="abrir los archivos en la aplicación completa")
    parser.add_argument("--background", action="store_true", help="iniciar en la bandeja sin mostrar ventanas")
    parser.add_argument("--register-associations", action="store_true",
                        help="registrar AERO Player en «Abrir con» y en Aplicaciones predeterminadas (usuario actual)")
    parser.add_argument("--unregister-associations", action="store_true", help="quitar ese registro")
    parser.add_argument("--action", help="acción del menú contextual (extract_here, compress, convert…)")
    parser.add_argument("--register-context-menu", action="store_true",
                        help="añadir «AERO Player» al menú contextual del Explorador (usuario actual)")
    parser.add_argument("--unregister-context-menu", action="store_true", help="quitar ese menú")
    parser.add_argument("--uninstall", action="store_true", help="desinstalar AERO Player (conserva tus datos)")
    parser.add_argument("--quiet", action="store_true", help="con --uninstall: sin ventanas")
    parser.add_argument("--diagnostico", metavar="ARCHIVO", help="escribir un diagnóstico (versión, núcleo nativo, "
                        "iconos) en ARCHIVO .json y salir, sin ventanas")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if args.diagnostico:
        return _diagnostico(args.diagnostico)
    if args.register_associations or args.unregister_associations:
        from aero.core import associations

        (associations.register if args.register_associations else associations.unregister)()
        return 0
    if args.register_context_menu or args.unregister_context_menu:
        from aero.core import shellmenu

        (shellmenu.register if args.register_context_menu else shellmenu.unregister)()
        return 0
    if args.uninstall:
        from aero.installer.ui import main_uninstall

        return main_uninstall(args.quiet)

    if os.name == "nt":
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AeroPlayer.AeroPlayer.1")
        except (OSError, AttributeError):
            pass

    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv[:1])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_ID)
    app.setApplicationVersion(__version__)
    app.setStyle("Fusion")
    app.setQuitOnLastWindowClosed(False)
    from aero.ui import gc_guard

    gc_guard.install(app)            # objetos de Qt destruidos siempre en el hilo principal (ver gc_guard.py)
    font = QFont("Segoe UI Variable Text")
    font.setPointSizeF(10)
    app.setFont(font)

    paths = [os.path.abspath(p) for p in args.paths]
    msg = {"paths": paths, "full": args.full, "background": args.background, "action": args.action}
    if _send_to_running(msg):
        return 0
    # Con varios archivos seleccionados el Explorador lanza un proceso por archivo a la vez: solo uno debe
    # convertirse en la instancia principal; los demás esperan a que escuche y le pasan su archivo.
    lock = QLockFile(os.path.join(QDir.tempPath(), f"{SERVER_NAME}.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(0):
        import time

        for _ in range(40):  # hasta ~10 s: lo que tarda en arrancar la instancia principal
            if _send_to_running(msg):
                return 0
            time.sleep(0.25)
            lock.tryLock(0)
            if lock.isLocked():
                break

    server = QLocalServer()
    QLocalServer.removeServer(SERVER_NAME)
    server.listen(SERVER_NAME)
    early: list[dict] = []  # mensajes que llegan mientras se termina de arrancar
    handler = [early.append]

    def on_conn():
        sock = server.nextPendingConnection()
        if sock is None:
            return

        def read():
            try:
                m = json.loads(bytes(sock.readAll()).decode("utf-8") or "{}")
            except ValueError:
                return
            handler[0](m)

        sock.readyRead.connect(read)
        sock.disconnected.connect(sock.deleteLater)

    server.newConnection.connect(on_conn)

    from aero.core.config import Settings
    from aero.core.db import Database
    from aero.ui.controller import AppController
    from aero.ui.glass import make_app_icon
    from aero.ui.main_window import apply_theme

    app.setWindowIcon(QIcon(make_app_icon(256)))
    settings = Settings()
    from aero.i18n import DEFAULT_LANGUAGE, set_language

    set_language(settings.get("language") or DEFAULT_LANGUAGE)
    db = Database()
    apply_theme(app, settings)
    ctl = AppController(app, settings, db)

    def handle(m: dict):
        if m.get("quit"):  # el instalador pide cerrar para actualizar o desinstalar
            ctl.quit()
        elif m.get("action"):
            ctl.run_action(m["action"], m.get("paths") or [])
        elif m.get("paths"):
            ctl.open_files(m["paths"], full=bool(m.get("full")))
        elif not m.get("background"):
            ctl.show_main()

    handler[0] = handle
    if args.action:
        ctl.run_action(args.action, paths)
    elif paths:
        ctl.open_files(paths, full=args.full)
    elif args.background and ctl.tray_active():
        pass
    else:
        ctl.show_main()
    for m in early:
        handle(m)
    code = app.exec()
    from aero import torrent

    torrent.shutdown(3.0)   # las descargas se detienen con la aplicación (los .aeropart se quedan para continuar)
    from aero.ui.async_util import shutdown

    shutdown()  # sin hilos ejecutando Python mientras el intérprete termina
    db.close()
    lock.unlock()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
