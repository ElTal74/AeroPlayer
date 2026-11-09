"""Controlador de la aplicación: decide qué ventana abrir (modo completo, visor minimalista o Quick Look).

* Modo A — `MainWindow`: se crea solo cuando hace falta (acceso directo, carpeta, «abrir en AERO Player»).
* Modo B — `MediaWindow`: un archivo abierto desde el Explorador se muestra en su propia ventana mínima.
* Modo C — Quick Look: ventana de vista previa ligera controlada por el atajo / Espacio en el Explorador.
La bandeja y Quick Look funcionan aunque la ventana principal no exista.
"""

from __future__ import annotations

import os
import sys
import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from aero import APP_NAME
from aero.core import tools
from aero.core.formats import kind_of
from aero.ui.glass import make_app_icon
from aero.ui.main_window import apply_levels, apply_theme
from aero.i18n import tr

EDITOR_KINDS = {"document", "sheet", "slides"}
VIEWER_KINDS = {"image", "video", "audio", "pdf", "document", "sheet", "slides", "text", "archive"}


class AppController(QObject):
    def __init__(self, app: QApplication, settings, db):
        super().__init__()
        self.app = app
        self.settings = settings
        self.db = db
        self.main = None
        self.media_windows: list = []
        self.editors: list = []
        self.quicklook = None
        self.hotkeys = None
        self.tray: QSystemTrayIcon | None = None
        self._tray_hint = False
        self._pending_actions: dict[str, list[str]] = {}
        self._action_timer = QTimer(self)
        self._action_timer.setSingleShot(True)
        self._action_timer.setInterval(600)
        self._action_timer.timeout.connect(self._flush_actions)
        self._apply_tools()
        self._init_quality()
        self._remove_old_feature_data()
        from aero.torrent.ui import bind_settings

        bind_settings(self.settings)
        if os.name == "nt" and getattr(sys, "frozen", False):
            # Solo el programa instalado actualiza su registro (nunca una ejecución de desarrollo o de pruebas)
            QTimer.singleShot(2500, self._upgrade_registration)
        if self.settings.get("explorer_icons_foreign") and os.name == "nt":
            # Si el usuario cambió de programa predeterminado, el nuevo también recibe el icono AERO
            from aero.core import explorer_icons
            from aero.ui.async_util import run_async

            QTimer.singleShot(4000, lambda: run_async(explorer_icons.apply, lambda _n: None, None, None))
        settings.changed.connect(self._setting_changed)
        self.sync_quicklook()
        # Restos de vistas previas de comprimidos de una sesión anterior (p. ej. si se cerró de golpe).
        QTimer.singleShot(3000, self._purge_previews)
        if getattr(sys, "frozen", False):
            # Programa instalado: el menú contextual sigue la preferencia y la ruta actual del ejecutable
            QTimer.singleShot(2000, lambda: self.sync_context_menu(refresh_only=True))

    def _init_quality(self) -> None:
        """Primer arranque: se elige el perfil recomendado para este equipo (el usuario puede cambiarlo)."""
        from aero.ui.perf import auto_tuner

        if not self.settings.get("quality_profile"):
            from aero.core.hardware import detect, recommend

            hw = detect()
            scr = self.app.primaryScreen()
            if scr is not None:
                g = scr.geometry()
                hw.screen = (int(g.width() * scr.devicePixelRatio()), int(g.height() * scr.devicePixelRatio()))
            self.settings.set("quality_profile", recommend(hw)[0])
        # Aplicarlo ya: el tema se aplicó antes con el perfil vacío (= Equilibrado) y aún no escuchamos los cambios
        # de ajustes, así que sin esto el perfil elegido no tenía efecto hasta el siguiente arranque.
        from aero.ui.main_window import apply_quality

        apply_quality(self.settings)
        tuner = auto_tuner()
        tuner.settings = self.settings
        tuner.set_enabled(bool(self.settings.get("quality_auto")))
        tuner.set_rest_enabled(bool(self.settings.get("motion_rest")))

    def _upgrade_registration(self) -> None:
        """Si AERO Player ya estaba registrado (lo aceptó el usuario), se pone al día una vez: iconos por categoría
        e imágenes de disco y torrents con su propio tipo. Solo se tocan claves de AERO Player; nunca `UserChoice`."""
        from aero.core import associations

        if int(self.settings.get("assoc_version") or 0) >= associations.REG_VERSION:
            return
        try:
            # Ya registrado (lo aceptó el usuario) o elegido en Windows pero roto: se registra de nuevo
            if associations.is_registered() or associations.chosen_but_missing():
                associations.register()
            self.settings.set("assoc_version", associations.REG_VERSION)
        except OSError:
            pass

    @staticmethod
    def _remove_old_feature_data() -> None:
        """La integración con Spotify se retiró en 2.1: se borra su token cifrado si quedaba de una versión anterior.
        Solo esos archivos (el ID de cliente desaparece solo de los ajustes, que ignoran claves desconocidas)."""
        from aero.core.paths import data_dir

        for name in ("spotify.bin", "spotify.part"):
            try:
                (data_dir() / name).unlink()
            except OSError:
                pass

    @staticmethod
    def _purge_previews() -> None:
        from aero.archive import Workspace
        from aero.ui.async_util import run_async

        run_async(Workspace.purge_old, lambda _r: None)

    # ------------------------------------------------------------------ preferencias globales
    def _setting_changed(self, key: str) -> None:
        if key in ("glass_intensity", "window_transparency"):
            apply_levels(self.settings)
        elif key.startswith("quality_"):
            from aero.ui.main_window import apply_quality

            apply_quality(self.settings)
            if key == "quality_auto":
                from aero.ui.perf import auto_tuner

                auto_tuner().set_enabled(bool(self.settings.get(key)))
        elif key in ("theme", "glass_mode", "reduce_motion", "custom_colors", "background_motion") or (
                key == "user_themes" and str(self.settings.get("theme")).startswith("user:")):
            apply_theme(self.app, self.settings)
        elif key == "motion_rest":
            from aero.ui.perf import auto_tuner

            auto_tuner().set_rest_enabled(bool(self.settings.get(key)))
        elif key in ("close_to_tray", "quicklook_enabled"):
            self.sync_tray()
        elif key in ("ffmpeg_path", "soffice_path"):
            self._apply_tools()
        elif key == "language":
            self.change_language()
        elif key == "context_menu":
            self.sync_context_menu()

    def change_language(self) -> None:
        """Aplica el idioma al momento: la ventana principal se vuelve a construir en el nuevo idioma. Lo que
        sonaba se detiene guardando su posición (se retoma al volver a abrirlo)."""
        from aero.i18n import DEFAULT_LANGUAGE, set_language

        set_language(self.settings.get("language") or DEFAULT_LANGUAGE)
        old = self.main
        if old is None:
            return
        page = old.current_page()
        old.quitting = True
        old.shutdown()          # guarda geometría, posición y ajustes
        old.hide()
        self.main = None
        win = self.show_main()
        win.navigate(page)
        old.deleteLater()

    def sync_context_menu(self, refresh_only: bool = False) -> None:
        """Registra o quita el menú contextual según la preferencia (solo HKCU, sin administrador)."""
        if os.name != "nt":
            return
        from aero.core import shellmenu

        try:
            shellmenu.sync(bool(self.settings.get("context_menu")), refresh_only=refresh_only)
        except OSError:
            pass

    def _apply_tools(self) -> None:
        ff = self.settings.get("ffmpeg_path")
        tools.set_override("ffmpeg", ff)
        if ff:
            tools.set_override("ffprobe", os.path.join(os.path.dirname(ff), "ffprobe.exe"))
        tools.set_override("soffice", self.settings.get("soffice_path"))

    # ------------------------------------------------------------------ ventanas
    def show_main(self, paths: list[str] | None = None):
        if self.main is None:
            from aero.ui.main_window import MainWindow

            self.main = MainWindow(self.settings, self.db, self)
        self.main.show_window()
        if paths:
            QTimer.singleShot(0, self.main, lambda: self.main is not None and self.main.open_paths(paths))
        elif not self.settings.get("tutorial_done") and not os.environ.get("AERO_NO_TUTORIAL"):
            # Primera vez: tutorial de bienvenida (se puede saltar; se vuelve a ver desde Ajustes)
            QTimer.singleShot(700, lambda: self.main is not None and self.main.start_tutorial())
        if not getattr(self, "_recovery_checked", False):
            # Trabajo sin guardar de una sesión que se cerró de golpe: se ofrece recuperarlo una vez por inicio.
            self._recovery_checked = True
            # Atados a la ventana: si se cierra antes de que salten, no se ejecutan (con una ventana ya destruida
            # como padre del diálogo, Qt fallaba de forma intermitente).
            QTimer.singleShot(900, self.main, self._offer_recovery)
            # Versiones nuevas en GitHub (en segundo plano, como mucho una vez al día, desactivable en Ajustes)
            QTimer.singleShot(8000, self.main, self._check_updates)
        return self.main

    def _check_updates(self) -> None:
        from aero.ui.update_ui import startup_check, whats_new

        if self.main is None:
            return
        whats_new(self)                      # tras actualizar: «Novedades de la versión…» (una sola vez)
        if os.environ.get("AERO_NO_UPDATES"):
            return
        startup_check(self)

    def _offer_recovery(self) -> None:
        from aero.ui.recovery import offer

        offer(self, self.main)

    def open_files(self, paths: list[str], full: bool = False) -> None:
        """Abre archivos desde el Explorador / línea de órdenes respetando el modo adecuado."""
        paths = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
        if not paths:
            self.show_main()
            return
        if full or any(os.path.isdir(p) for p in paths):
            self.show_main(paths)
            return
        first = paths[0]
        low = first.lower()
        if low.endswith(".torrent"):
            # Un .torrent solo muestra su contenido: nada se descarga sin pulsar «Descargar»
            from aero.torrent.ui import open_torrent

            open_torrent(first, self.main)
            return
        if low.endswith((".aerovid", ".aeroimg")):
            # Proyectos propios: se abren en su editor
            self.open_video_editor(first) if low.endswith(".aerovid") else self.open_image_editor(first)
            return
        if kind_of(first) in EDITOR_KINDS and self.settings.get("open_office_in_editor"):
            # Documentos, hojas y presentaciones se abren directamente en su editor (sección 11)
            for p in paths:
                self.open_editor_for(p)
            return
        if kind_of(first) not in VIEWER_KINDS:
            self.show_main(paths)
            return
        if kind_of(first) == "image" and self.settings.get("photos_in_main"):
            # Las fotos se abren en el visor de la ventana principal (anterior/siguiente, zoom, girar, voltear,
            # editar). La vista rápida sigue aparte: Espacio en el Explorador o en Archivos.
            self.show_main([first])
            return
        same = [p for p in paths if kind_of(p) == kind_of(first)]
        self.open_media_window(first, same if len(same) > 1 else None)

    def open_media_window(self, path: str, playlist: list[str] | None = None):
        from aero.ui.media_window import MediaWindow

        w = MediaWindow(self.settings, self.db, self)
        self.media_windows.append(w)
        w.destroyed.connect(lambda *_: None)
        w.open(path, playlist)
        if self.settings.get("history_enabled"):
            self.db.add_recent(path, kind_of(path))
        return w

    def media_window_closed(self, w) -> None:
        if w in self.media_windows:
            self.media_windows.remove(w)
        QTimer.singleShot(0, self._maybe_quit)

    def open_editor_for(self, path: str):
        """Editor adecuado para el tipo de archivo (o None si no hay editor para él)."""
        k = kind_of(path)
        if k == "image":
            return self.open_image_editor(path)
        if k in ("document", "text"):
            return self.open_document_editor(path)
        if k == "sheet":
            return self.open_sheet_editor(path)
        if k == "slides":
            return self.open_slides_editor(path)
        if k == "pdf":
            return self.open_pdf_convert(path)
        if k == "video" or path.lower().endswith(".aerovid"):
            return self.open_video_editor(path)
        return None

    def open_image_editor(self, path: str):
        """Editor de imágenes en su propia ventana (el módulo se carga solo ahora)."""
        from aero.editors.image.window import open_editor

        w = open_editor(path, self)
        self.editors.append(w)
        return w

    def open_document_editor(self, path: str = ""):
        """Editor de documentos (DOCX, ODT, RTF, TXT, Markdown, HTML) en su propia ventana."""
        from aero.office.doc_editor import open_editor

        w = open_editor(path, self)
        self.editors.append(w)
        return w

    def open_sheet_editor(self, path: str = ""):
        """Editor de hojas de cálculo (XLSX, XLS, ODS, CSV) en su propia ventana."""
        from aero.office.sheet_editor import open_editor

        w = open_editor(path, self)
        self.editors.append(w)
        return w

    def open_slides_editor(self, path: str = ""):
        """Editor de presentaciones (PPTX; ODP y PPT con LibreOffice) en su propia ventana."""
        from aero.office.slides_editor import open_editor

        w = open_editor(path, self)
        self.editors.append(w)
        return w

    def open_video_editor(self, path: str = ""):
        """Editor de vídeo no lineal (proyecto .aerovid o un vídeo para empezar) en su propia ventana."""
        from aero.editors.video.window import open_editor

        w = open_editor(path, self)
        self.editors.append(w)
        return w

    def open_paint(self, path: str = ""):
        """AERO Paint: dibujo y retoque rápido (lienzo nuevo o una imagen)."""
        from aero.editors.paint.window import open_paint

        w = open_paint(path, self)
        self.editors.append(w)
        return w

    def open_pdf_convert(self, path: str = ""):
        """PDF a documento editable (reconstrucción y OCR) en su propia ventana."""
        from aero.pdfconv.window import open_window

        w = open_window(path, self)
        self.editors.append(w)
        w.destroyed.connect(lambda *_: w in self.editors and self.editors.remove(w))
        return w

    def editor_closed(self, w) -> None:
        saver = getattr(w, "autosaver", None)
        if saver is not None:
            saver.stop()  # cierre normal: ya no hace falta el borrador
        if w in self.editors:
            self.editors.remove(w)
        QTimer.singleShot(0, self._maybe_quit)

    # ------------------------------------------------------------------ menú contextual del Explorador
    def run_action(self, action: str, paths: list[str], immediate: bool = False) -> None:
        """Acción pedida desde el menú contextual. Con varios elementos seleccionados el Explorador lanza una
        orden por elemento: se agrupan las que llegan en poco tiempo para comprimir o convertir todo junto."""
        if action == "extract_members":  # [comprimido, miembros…] desde un navegador de la aplicación
            self._do_action(action, paths)
            return
        paths = [os.path.abspath(p) for p in paths if p and os.path.exists(p)]
        if not paths:
            QTimer.singleShot(0, self._maybe_quit)
            return
        if immediate:
            self._do_action(action, paths)
            return
        if not self._pending_actions:
            self._actions_since = time.monotonic()
        pend = self._pending_actions.setdefault(action, [])
        pend.extend(p for p in paths if p not in pend)
        self._action_timer.start()

    @staticmethod
    def _siblings_starting(actions) -> bool:
        """¿Hay otros procesos de AERO Player arrancando con la misma acción? (el Explorador lanza uno por
        archivo y, con el equipo cargado, pueden tardar segundos en llegar)."""
        try:
            import psutil
        except ImportError:
            return False
        me = os.getpid()
        try:
            for proc in psutil.process_iter(["pid", "cmdline"]):
                if proc.info["pid"] == me:
                    continue
                cmd = proc.info.get("cmdline") or []
                if "--action" in cmd and any(a in cmd for a in actions) and any("aero" in c.lower() for c in cmd):
                    return True
        except (psutil.Error, OSError):
            return False
        return False

    def _flush_actions(self) -> None:
        # Se espera a los archivos que aún vienen de camino (máximo 12 s) para comprimir o convertir todo junto
        if self._pending_actions and time.monotonic() - getattr(self, "_actions_since", 0) < 12                 and self._siblings_starting(list(self._pending_actions)):
            self._action_timer.start(250)
            return
        self._action_timer.setInterval(600)
        pending, self._pending_actions = self._pending_actions, {}
        for action, paths in pending.items():
            try:
                self._do_action(action, paths)
            except Exception as e:  # noqa: BLE001 - un fallo aquí no debe cerrar la aplicación en silencio
                from PySide6.QtWidgets import QMessageBox

                QMessageBox.warning(None, APP_NAME, tr("No se pudo completar la acción: {e}", e=e))
        QTimer.singleShot(0, self._maybe_quit)

    def _do_action(self, action: str, paths: list[str]) -> None:
        from pathlib import Path

        from aero.archive import ops, ui

        if action == "open":
            self.open_files(paths)
        elif action == "browse":
            self.open_in_main(paths[0])
        elif action == "quicklook":
            self.show_quicklook(paths[0])
        elif action == "edit":
            for p in paths:
                if self.open_editor_for(p) is None:
                    self.open_files([p])
        elif action == "extract_here":
            for p in paths:
                ui.run_extract(self, p, str(Path(p).parent))
        elif action == "extract_folder":
            for p in paths:
                folder = ops.suggested_folder(p)
                if folder.exists() and any(folder.iterdir()):
                    folder = ops._unique(folder)
                ui.run_extract(self, p, str(folder))
        elif action == "extract_to":
            for p in paths:
                dlg = ui.ExtractDialog(p)
                if dlg.exec():
                    ui.run_extract(self, p, dlg.dest.text(), dlg.mode.currentData(), dlg.password.text() or None,
                                   open_after=dlg.open_after.isChecked())
        elif action == "extract_members":
            src, members = paths[0], paths[1:]
            dlg = ui.ExtractDialog(src)
            if dlg.exec():
                ui.run_extract(self, src, dlg.dest.text(), dlg.mode.currentData(), dlg.password.text() or None,
                               members or None, dlg.open_after.isChecked())
        elif action == "open_archive":
            for p in paths:
                self.editors.append(ui.open_manager(p, self))
        elif action in ("compress_zip", "compress_7z"):
            fmt = action.removeprefix("compress_")
            out = ops.default_archive_name(paths, fmt)
            if out.exists():
                out = ops._unique(out)
            ui.run_compress(self, paths, str(out), fmt, int(self.settings.get("archive_level")))
        elif action == "compress":
            dlg = ui.CompressDialog(paths, fmt=self.settings.get("archive_format"),
                                    level=int(self.settings.get("archive_level")))
            if dlg.exec():
                ui.run_compress(self, paths, dlg.output(), dlg.fmt(), dlg.level.currentData(),
                                dlg.password.text() or None, dlg.open_after.isChecked())
        elif action == "convert":
            from aero.ui.quick_convert import open_quick_convert

            self.editors.append(open_quick_convert(paths, self))
        elif action in ("batch_rename", "batch_resize"):
            from aero.ui import batch_tools

            fn = batch_tools.open_batch_rename if action == "batch_rename" else batch_tools.open_batch_resize
            self.editors.append(fn(paths, self))
        else:
            self.open_files(paths)

    def open_in_main(self, path: str) -> None:
        if os.path.isdir(path):
            # Desde Quick Look, una carpeta se explora en «Archivos» (no se reproduce todo su contenido).
            win = self.show_main()
            win._browse_dirs = True
            QTimer.singleShot(0, lambda: win.open_paths([path]))
            return
        self.show_main([path])

    def main_closed(self, w) -> None:
        self.main = None
        w.deleteLater()
        QTimer.singleShot(0, self._maybe_quit)

    def _maybe_quit(self) -> None:
        visible = (self.main is not None and self.main.isVisible()) or any(m.isVisible() for m in self.media_windows) \
            or any(e.isVisible() for e in self.editors) or (self.quicklook is not None and self.quicklook.isVisible())
        if not visible and not self.tray_active():
            self.quit()

    def quit(self) -> None:
        if self.main is not None:
            self.main.quitting = True
            self.main.shutdown()
            self.main.hide()
        for m in list(self.media_windows):
            m.close()
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        if self.quicklook is not None:
            self.quicklook.close_preview()
        if self.tray is not None:
            self.tray.hide()
        self.settings.save_now()
        self.app.quit()

    # ------------------------------------------------------------------ bandeja
    def tray_active(self) -> bool:
        return self.tray is not None and bool(self.settings.get("close_to_tray") or self.settings.get("quicklook_enabled"))

    def sync_tray(self) -> None:
        need = bool(self.settings.get("quicklook_enabled") or self.settings.get("close_to_tray"))
        if need and self.tray is None and QSystemTrayIcon.isSystemTrayAvailable():
            self.tray = QSystemTrayIcon(QIcon(make_app_icon(64)), self)
            self.tray.setToolTip(APP_NAME)
            menu = QMenu()
            menu.addAction(tr("Abrir AERO Player"), self.show_main)
            menu.addSeparator()
            self.tray_ql = QAction(tr("Vista rápida"), menu, checkable=True)
            self.tray_ql.toggled.connect(lambda on: (self.settings.set("quicklook_enabled", on), self.sync_quicklook()))
            menu.addAction(self.tray_ql)
            menu.addSeparator()
            menu.addAction(tr("Salir"), self.quit)
            self.tray.setContextMenu(menu)
            self.tray.activated.connect(
                lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and self.show_main())
            self._tray_menu = menu
            self.tray.show()
        elif not need and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None
        if self.tray is not None:
            self.tray_ql.blockSignals(True)
            self.tray_ql.setChecked(bool(self.settings.get("quicklook_enabled")))
            self.tray_ql.blockSignals(False)

    def tray_message(self, text: str) -> None:
        if self.tray is not None:
            self.tray.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, 2500)

    # ------------------------------------------------------------------ Quick Look
    def sync_quicklook(self) -> None:
        if self.hotkeys is not None:
            self.hotkeys.stop()
            self.hotkeys = None
        if self.settings.get("quicklook_enabled") and os.name == "nt":
            from aero.quicklook.winhook import HotkeyThread

            self.hotkeys = HotkeyThread(self.settings.get("quicklook_hotkey"),
                                        bool(self.settings.get("quicklook_space_in_explorer")), self)
            self.hotkeys.triggered.connect(self.quicklook_triggered)
            self.hotkeys.failed.connect(self._hotkey_failed)
            self.hotkeys.start()
        self.sync_tray()

    def _hotkey_failed(self, msg: str) -> None:
        if self.main is not None:
            self.main.notify(msg, "error")
        else:
            self.tray_message(msg)

    def quicklook_triggered(self, source: str) -> None:
        if self.quicklook is not None and self.quicklook.isVisible():
            self.quicklook.close_preview()
            return
        from aero.quicklook.explorer import selected_paths

        try:
            paths = selected_paths()
        except Exception:  # noqa: BLE001
            paths = []
        if not paths:
            if source == "hotkey":
                self.tray_message("Selecciona un archivo en el Explorador")
            return
        self.show_quicklook(paths[0])

    def show_quicklook(self, path: str) -> None:
        from aero.ui.media_window import MediaWindow

        if self.quicklook is None:
            self.quicklook = MediaWindow(self.settings, self.db, self, quicklook=True)
        self.quicklook.open(path)
