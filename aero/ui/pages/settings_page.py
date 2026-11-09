"""Ajustes: apariencia y cristal, reproducción, visor, biblioteca, conversión, vista rápida, predeterminados."""

from __future__ import annotations

import os
import shutil
import sys

import unicodedata

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout,
                               QKeySequenceEdit, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QScrollArea, QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from aero import APP_NAME, COPYRIGHT, UPDATE_REPO, __version__
from aero.core import associations, tools
from aero.core.config import DEFAULT_SHORTCUTS, SHORTCUT_LABELS
from aero.core.paths import cache_dir, data_dir
from aero.core.winintegration import set_autostart
from aero.ui.glass import GlassPanel, h_layout, label, tm
from aero.i18n import tr

# (clave, título, icono, descripción breve)
CATEGORIES = [
    ("general", "General", "home", "Inicio, bienvenida y arranque."),
    ("appearance", "Apariencia", "eye", "Transparencia y cristal de la ventana."),
    ("themes", "Temas", "star", "Elige, crea e importa temas."),
    ("motion", "Animaciones y fondos", "aero", "Movimiento del fondo y de la interfaz."),
    ("playback", "Reproducción", "play", "Reproductor, visor y visualizadores."),
    ("library", "Biblioteca", "library", "Carpetas que se escanean e historial."),
    ("files", "Archivos y asociaciones", "files", "Abrir con, clic derecho y vista rápida."),
    ("convert", "Conversión", "convert", "Destino, simultaneidad y programas externos."),
    ("archive", "Compresión", "archive", "Formato y ventana de progreso."),
    ("downloads", "Descargas BitTorrent", "download", "Archivos .torrent y carpeta de descargas."),
    ("editors", "Editores", "edit", "Qué se abre en los editores."),
    ("performance", "Rendimiento", "speed", "Calidad visual y consumo."),
    ("privacy", "Privacidad", "lock", "Historial y datos guardados."),
    ("shortcuts", "Atajos de teclado", "keyboard", "Teclas de reproducción y navegación."),
    ("system", "Sistema y almacenamiento", "folder", "Espacio usado y caché."),
    ("about", "Acerca de", "info", "Versión, licencia y tutorial."),
]


def _show_downloads():
    from aero.torrent.ui import show_downloads

    show_downloads()


def _fold(text: str) -> str:
    """Minúsculas y sin tildes, para buscar «animacion» y encontrar «Animaciones»."""
    return "".join(c for c in unicodedata.normalize("NFD", text.lower()) if unicodedata.category(c) != "Mn")


def section(title: str) -> tuple[GlassPanel, QVBoxLayout]:
    p = GlassPanel(radius=12, nested=True)
    lay = QVBoxLayout(p)
    lay.setContentsMargins(18, 14, 18, 16)
    lay.setSpacing(10)
    lay.addWidget(label(title, "h3"))
    return p, lay


def segmented(options: list[tuple[str, str]], current: str, on_change) -> QWidget:
    """Botones segmentados (una sola elección)."""
    w = QWidget()
    group = QButtonGroup(w)
    lay = h_layout(spacing=4)
    for key, text in options:
        b = QPushButton(tr(text))
        b.setCheckable(True)
        b.setChecked(key == current)
        b.setProperty("kind", "flat")
        b.clicked.connect(lambda _c=False, k=key: on_change(k))
        group.addButton(b)
        lay.addWidget(b)
    lay.addStretch(1)
    w.setLayout(lay)
    return w


class SettingsPage(QWidget):
    quicklook_changed = Signal()
    shortcuts_changed = Signal()
    clear_history = Signal()
    clear_all = Signal()
    rescan = Signal()
    tutorial = Signal()
    message = Signal(str, str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.s = settings
        self._cats: dict[str, list[QWidget]] = {key: [] for key, *_ in CATEGORIES}

        def add(cat: str, panel: QWidget):
            self._cats[cat].append(panel)

        # ------------------------------------------------------------ general
        from PySide6.QtWidgets import QComboBox

        from aero.i18n import LANGUAGES, language

        p, lay = section(tr("Idioma"))
        lang = QComboBox()
        for code, name in LANGUAGES.items():
            lang.addItem(name, code)
        lang.setCurrentIndex(max(0, lang.findData(language())))
        lang.setAccessibleName(tr("Idioma"))
        lang.currentIndexChanged.connect(lambda _i: settings.set("language", lang.currentData()))
        lay.addLayout(h_layout(lang, None))
        add("general", p)

        p, lay = section(tr("Inicio y bienvenida"))
        tour = QPushButton(tr("Ver el tutorial"))
        tour.setIcon(tm().icon("info", 16))
        tour.setToolTip(tr("Recorrido guiado por las funciones de AERO Player"))
        tour.clicked.connect(self.tutorial.emit)
        lay.addLayout(h_layout(tour, None))
        add("general", p)
        p, lay = section(tr("Al cerrar y al iniciar"))
        auto = self._check("start_with_windows", tr("Iniciar con Windows"))
        auto.toggled.connect(lambda on: set_autostart(on))
        lay.addWidget(self._check("close_to_tray", tr("Cerrar a la bandeja (sigue sonando)")))
        lay.addWidget(self._check("autosave_drafts", tr("Guardar borradores de los editores cada minuto (para "
                                                     "recuperarlos si se cierra de golpe)")))
        lay.addWidget(auto)
        add("general", p)

        # ------------------------------------------------------------ apariencia
        from aero.ui.pages.theme_studio import ThemeGallery, ValueSlider

        p, lay = section(tr("Cristal"))
        lay.addWidget(segmented([("blur", tr("Esmerilado")), ("clear", tr("Transparente")), ("opaque", tr("Opaco"))],
                                settings.get("glass_mode"), lambda k: settings.set("glass_mode", k)))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        self.transp = ValueSlider(settings.get("window_transparency"), "Cuánto se ve lo que hay detrás de la ventana")
        self.transp.changed.connect(lambda v: settings.set("window_transparency", v))
        self.intensity = ValueSlider(settings.get("glass_intensity"), "Opacidad de los paneles de cristal")
        self.intensity.changed.connect(lambda v: settings.set("glass_intensity", v))
        grid.addWidget(label("Transparencia", "muted"), 0, 0)
        grid.addWidget(self.transp, 0, 1)
        grid.addWidget(label("Paneles", "muted"), 1, 0)
        grid.addWidget(self.intensity, 1, 1)
        lay.addLayout(grid)
        add("appearance", p)

        p, lay = section(tr("Temas"))
        self.gallery = ThemeGallery(settings)
        lay.addWidget(self.gallery)
        add("themes", p)

        p, lay = section(tr("Movimiento del fondo"))
        lay.addWidget(segmented([("on", tr("Animado")), ("reduced", tr("Reducido")), ("static", tr("Estático"))],
                                settings.get("background_motion"), lambda k: settings.set("background_motion", k)))
        lay.addWidget(label(tr("Si Windows tiene las animaciones desactivadas, se usa «Reducido»."), "caption"))
        lay.addWidget(self._check("motion_rest", tr("Detener el fondo tras 3 minutos sin usar el equipo y con batería "
                                                 "(ahorra energía)")))
        add("motion", p)
        p, lay = section(tr("Interfaz"))
        lay.addWidget(self._check("reduce_motion", tr("Menos animaciones en la interfaz")))
        add("motion", p)

        # ------------------------------------------------------------ reproducción
        p, lay = section(tr("Reproducción"))
        lay.addWidget(self._check("remember_position", tr("Recordar dónde te quedaste")))
        lay.addWidget(self._check("remember_volume", tr("Recordar el volumen")))
        mk = self._check("media_keys", tr("Teclas multimedia del teclado (reproducir, pausa, siguiente…)"))
        mk.setToolTip(tr("Funcionan aunque AERO Player esté en segundo plano, solo mientras reproduce o está en "
                         "pausa: así no se las quita a otras aplicaciones."))
        lay.addWidget(mk)
        rs = self._check("viewer_remember_size", tr("Recordar el tamaño del visor"))
        rs.setToolTip(tr("Si está desactivado, la ventana se adapta a cada imagen o vídeo"))
        lay.addWidget(rs)
        add("playback", p)
        from aero.ui.pages.viz_gallery import VisualizerGallery

        p, lay = section(tr("Visualizadores"))
        lay.addWidget(self._check("visualizer_low_power", tr("Visualizador ligero")))
        lay.addWidget(VisualizerGallery(settings, columns=4))
        add("playback", p)

        # ------------------------------------------------------------ biblioteca
        p, lay = section(tr("Carpetas de la biblioteca"))
        self.folders = QListWidget()
        self.folders.setFixedHeight(110)
        self.folders.addItems(settings.get("library_folders"))
        self.excludes = QListWidget()
        self.excludes.setFixedHeight(70)
        self.excludes.addItems(settings.get("library_excludes"))
        add_f, rem_f, add_e, rem_e = (QPushButton(t) for t in ("Añadir", "Quitar", "Excluir", "Quitar"))
        add_f.setProperty("kind", "primary")
        scan = QPushButton(tr("Escanear"))
        scan.setIcon(tm().icon("refresh", 16))
        add_f.clicked.connect(lambda: self._add_dir("library_folders", self.folders))
        rem_f.clicked.connect(lambda: self._rem_dir("library_folders", self.folders))
        add_e.clicked.connect(lambda: self._add_dir("library_excludes", self.excludes))
        rem_e.clicked.connect(lambda: self._rem_dir("library_excludes", self.excludes))
        scan.clicked.connect(self.rescan)
        lay.addWidget(self.folders)
        lay.addLayout(h_layout(add_f, rem_f, None, scan))
        lay.addWidget(label("Excluidas", "muted"))
        lay.addWidget(self.excludes)
        lay.addLayout(h_layout(add_e, rem_e, None))
        add("library", p)
        p, lay = section(tr("Historial"))
        hist = self._check("history_enabled", tr("Guardar lo que reproduces y abres"))
        lay.addWidget(hist)
        add("library", p)

        # ------------------------------------------------------------ archivos y asociaciones
        # Registro, iconos del Explorador y vista rápida son de Windows: en Linux y macOS esas secciones se crean
        # (el resto del código las usa) pero no se muestran, y en su lugar se explica cómo se integra allí.
        self._hidden_sections: list = []

        def windows_only(section_widget):
            if os.name == "nt":
                add("files", section_widget)
            else:
                section_widget.hide()
                self._hidden_sections.append(section_widget)

        p, lay = section(tr("Usar AERO Player para todo"))
        if os.name == "nt":
            how = tr("Música, vídeo, fotos, PDF, documentos, comprimidos, discos y torrents se abrirán con AERO Player. "
                     "Windows te mostrará la página de AERO Player: pulsa «Establecer predeterminada» una vez y "
                     "listo (Windows exige que lo confirmes tú).")
        else:
            how = tr("Música, vídeo, fotos, PDF, documentos, comprimidos, discos y torrents se abrirán con "
                     "AERO Player.")
        lay.addWidget(label(how, "caption", wrap=True))
        self.btn_default_all = QPushButton(tr("Usar AERO Player para todos mis archivos"))
        self.btn_default_all.setProperty("kind", "primary")
        self.btn_default_all.setMinimumHeight(34)
        self.btn_default_all.clicked.connect(self._make_default_all)
        self.default_state = label("", "caption")
        lay.addLayout(h_layout(self.btn_default_all, 12, self.default_state, None))
        add("files", p)

        p, lay = section(tr("Aplicaciones predeterminadas"))
        self.assoc_grid = QGridLayout()
        self.assoc_grid.setHorizontalSpacing(18)
        lay.addLayout(self.assoc_grid)
        self.btn_register = QPushButton(tr("Registrar AERO Player"))
        self.btn_register.setProperty("kind", "primary")
        self.btn_register.setToolTip(tr("Añade AERO Player a «Abrir con» y a las aplicaciones predeterminadas de Windows "
                                     "(solo para tu usuario). Windows te pedirá confirmar."))
        self.btn_register.clicked.connect(self._register)
        self.btn_settings = QPushButton(tr("Elegir en Windows…"))
        self.btn_settings.clicked.connect(associations.open_default_apps_settings)
        self.btn_unregister = QPushButton(tr("Quitar registro"))
        self.btn_unregister.setProperty("kind", "flat")
        self.btn_unregister.clicked.connect(self._unregister)
        self.btn_refresh = QPushButton(tr("Actualizar"))
        self.btn_refresh.setProperty("kind", "flat")
        self.btn_refresh.clicked.connect(self._refresh_assoc)
        lay.addLayout(h_layout(self.btn_register, self.btn_settings, None, self.btn_refresh, self.btn_unregister))
        windows_only(p)
        if os.name != "nt":
            p, lay = section(tr("Integración con el sistema"))
            if sys.platform == "darwin":
                text = tr("AERO Player aparece en «Abrir con» del Finder para música, vídeo, fotos, documentos y "
                          "comprimidos. Para usarlo siempre con un tipo: Obtener información › Abrir con › "
                          "Cambiar todo.")
            else:
                text = tr("Ejecuta «install.sh» (incluido en la descarga) para añadir AERO Player al menú de "
                          "aplicaciones y a «Abrir con». Para usarlo siempre con un tipo, elígelo en las "
                          "propiedades del archivo de tu gestor de archivos.")
            lay.addWidget(label(text, "caption", wrap=True))
            add("files", p)

        p, lay = section(tr("Iconos AERO en el Explorador"))
        lay.addWidget(label(tr("Los tipos que abre AERO Player llevan el icono AERO de su categoría (vídeo, audio, "
                               "imagen, documento, comprimido, disco, torrent…). Para los tipos que abre otro "
                               "programa, Windows usa el icono de ese programa; puedes usar también el de AERO sin "
                               "cambiar qué programa los abre."), "caption", wrap=True))
        self.icons_foreign = QCheckBox(tr("Iconos AERO también en los tipos que abren otros programas"))
        self.icons_foreign.setChecked(bool(settings.get("explorer_icons_foreign")))
        self.icons_foreign.toggled.connect(self._toggle_foreign_icons)
        self.icons_state = label("", "caption", wrap=True)
        self.btn_icons_restore = QPushButton(tr("Restaurar iconos originales"))
        self.btn_icons_restore.setProperty("kind", "flat")
        self.btn_icons_restore.clicked.connect(self._restore_icons)
        lay.addWidget(self.icons_foreign)
        lay.addLayout(h_layout(self.icons_state, None, self.btn_icons_restore))
        windows_only(p)

        p, lay = section(tr("Fotos"))
        lay.addWidget(self._check("photos_in_main", tr("Abrir las fotos en la ventana principal de AERO Player")))
        lay.addWidget(label(tr("Desactivado, las fotos abiertas desde Windows usan el visor mínimo. La vista rápida "
                               "(Espacio) funciona igual en los dos casos."), "caption", wrap=True))
        add("files", p)
        p, lay = section(tr("Explorador de Windows"))
        cm = self._check("context_menu", tr("Menú «AERO Player» en el clic derecho"))
        cm.setToolTip(tr("Extraer, comprimir y convertir desde el Explorador. En Windows 11: «Mostrar más opciones»."))
        lay.addWidget(cm)
        self.ql = self._check("quicklook_enabled", tr("Vista rápida"))
        self.ql.setToolTip(tr("Selecciona un archivo en el Explorador y pulsa Espacio"))
        self.ql.toggled.connect(lambda _on: self.quicklook_changed.emit())
        self.ql_space = self._check("quicklook_space_in_explorer", tr("Espacio abre la vista rápida"))
        self.ql_space.setToolTip(tr("Solo con la lista de archivos enfocada, sin escribir y sin teclas modificadoras"))
        self.ql_space.toggled.connect(lambda _on: self.quicklook_changed.emit())
        self.ql_key = QKeySequenceEdit(QKeySequence(settings.get("quicklook_hotkey")))
        self.ql_key.setMaximumSequenceLength(1)
        self.ql_key.setFixedWidth(170)
        self.ql_key.editingFinished.connect(self._ql_key)
        lay.addWidget(self.ql)
        lay.addWidget(self.ql_space)
        lay.addLayout(h_layout(label(tr("Atajo de la vista rápida"), "muted"), self.ql_key, None, spacing=10))
        windows_only(p)

        # ------------------------------------------------------------ conversión
        p, lay = section(tr("Conversión"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.out_dir = QLineEdit(settings.get("output_dir"))
        self.out_dir.setReadOnly(True)
        pick = QPushButton("…")
        pick.clicked.connect(self._pick_out)
        form.addRow(tr("Guardar en"), h_layout(self.out_dir, pick))
        self.parallel = QSpinBox()
        self.parallel.setRange(1, 8)
        self.parallel.setValue(int(settings.get("max_parallel_jobs")))
        self.parallel.valueChanged.connect(lambda v: settings.set("max_parallel_jobs", v))
        form.addRow(tr("A la vez"), self.parallel)
        lay.addLayout(form)
        lay.addWidget(self._check("use_hw_encoding", tr("Usar la tarjeta gráfica para codificar")))
        add("convert", p)
        p, lay = section(tr("Programas externos"))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        self.ffmpeg = QLineEdit(settings.get("ffmpeg_path"))
        self.ffmpeg.setPlaceholderText(tools.find_tool("ffmpeg") or "No encontrado")
        ff_btn = QPushButton("…")
        ff_btn.clicked.connect(lambda: self._pick_tool("ffmpeg_path", "ffmpeg", self.ffmpeg))
        form.addRow(tr("FFmpeg"), h_layout(self.ffmpeg, ff_btn))
        self.soffice = QLineEdit(settings.get("soffice_path"))
        self.soffice.setPlaceholderText(tools.find_tool("soffice") or "Opcional")
        so_btn = QPushButton("…")
        so_btn.clicked.connect(lambda: self._pick_tool("soffice_path", "soffice", self.soffice))
        form.addRow(tr("LibreOffice"), h_layout(self.soffice, so_btn))
        lay.addLayout(form)
        add("convert", p)

        # ------------------------------------------------------------ compresión
        from aero.archive import ops as archive_ops

        p, lay = section(tr("Comprimir"))
        fmt = QComboBox()
        for k, t in archive_ops.available_write_formats().items():
            fmt.addItem(t, k)
        fmt.setCurrentIndex(max(0, fmt.findData(settings.get("archive_format"))))
        fmt.currentIndexChanged.connect(lambda _i: settings.set("archive_format", fmt.currentData()))
        lvl = QComboBox()
        for k, t in archive_ops.LEVELS.items():
            lvl.addItem(t, k)
        lvl.setCurrentIndex(max(0, lvl.findData(settings.get("archive_level"))))
        lvl.currentIndexChanged.connect(lambda _i: settings.set("archive_level", lvl.currentData()))
        form = QFormLayout()
        form.setHorizontalSpacing(14)
        form.addRow(tr("Formato"), fmt)
        form.addRow(tr("Compresión"), lvl)
        lay.addLayout(form)
        lay.addWidget(label(tr("ZIP es el más rápido y compatible; 7Z ocupa menos pero tarda más."), "caption"))
        add("archive", p)
        p, lay = section(tr("Al terminar"))
        lay.addWidget(self._check("archive_auto_close", tr("Cerrar la ventana de progreso sola")))
        add("archive", p)

        # ------------------------------------------------------------ descargas BitTorrent
        p, lay = section(tr("BitTorrent"))
        lay.addWidget(self._check("torrent_enabled", tr("Permitir descargas BitTorrent")))
        lay.addWidget(label(tr("Desactivado, los .torrent solo muestran su contenido: AERO Player no crea el motor "
                               "ni hace ninguna conexión. Nada se descarga sin pulsar «Descargar», nada de lo "
                               "descargado se ejecuta y al cerrar la aplicación las descargas se detienen."),
                            "caption", wrap=True))
        dl_btn = QPushButton(tr("Ver descargas"))
        dl_btn.clicked.connect(_show_downloads)
        lay.addLayout(h_layout(dl_btn, None))
        add("downloads", p)

        # ------------------------------------------------------------ editores
        p, lay = section(tr("Editores"))
        lay.addWidget(self._check("open_office_in_editor", tr("Abrir documentos, hojas y presentaciones en su editor")))
        add("editors", p)

        # ------------------------------------------------------------ rendimiento
        from aero.ui.pages.perf_settings import PerformanceSettings

        p, lay = section(tr("Rendimiento y calidad visual"))
        self.performance = PerformanceSettings(settings)
        lay.addWidget(self.performance)
        add("performance", p)

        # ------------------------------------------------------------ privacidad
        p, lay = section(tr("Privacidad"))
        lay.addWidget(label(tr("Sin telemetría: todo se guarda solo en este equipo."), "caption"))
        b1, b3 = QPushButton(tr("Borrar historial")), QPushButton(tr("Borrar todo"))
        b3.setProperty("kind", "danger")
        b1.clicked.connect(self.clear_history)
        b3.clicked.connect(self._clear_all)
        lay.addLayout(h_layout(b1, b3, None))
        add("privacy", p)

        # ------------------------------------------------------------ atajos
        p, lay = section(tr("Atajos de teclado"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        self.key_edits: dict[str, QKeySequenceEdit] = {}
        sc = settings.get("shortcuts")
        for i, (k, text) in enumerate(SHORTCUT_LABELS.items()):
            e = QKeySequenceEdit(QKeySequence(sc.get(k, DEFAULT_SHORTCUTS[k])))
            e.setMaximumSequenceLength(1)
            e.editingFinished.connect(self._save_shortcuts)
            self.key_edits[k] = e
            grid.addWidget(label(text, "muted"), i // 2, (i % 2) * 2)
            grid.addWidget(e, i // 2, (i % 2) * 2 + 1)
        lay.addLayout(grid)
        reset = QPushButton(tr("Restablecer"))
        reset.setProperty("kind", "flat")
        reset.clicked.connect(self._reset_shortcuts)
        lay.addLayout(h_layout(None, reset))
        add("shortcuts", p)

        # ------------------------------------------------------------ sistema
        p, lay = section(tr("Almacenamiento"))
        self.storage = label("", "muted")
        lay.addWidget(self.storage)
        b2 = QPushButton(tr("Vaciar caché"))
        b2.clicked.connect(self._clear_cache)
        open_data = QPushButton(tr("Abrir carpeta de datos"))
        open_data.setProperty("kind", "flat")
        open_data.clicked.connect(lambda: tools.open_with_default(str(data_dir())))
        lay.addLayout(h_layout(b2, open_data, None))
        add("system", p)

        # ------------------------------------------------------------ acerca de
        p, lay = section(APP_NAME)
        lay.addWidget(label(tr("Versión {v}", v=__version__), "accent"))
        lay.addWidget(label(f"{COPYRIGHT}. " + tr("Todos los derechos reservados sobre el nombre y el logotipo."),
                            "muted", wrap=True))
        lay.addWidget(label(tr("Software libre (GPL-3.0): puedes usarlo, estudiarlo, modificarlo y compartirlo, "
                               "manteniendo la autoría y la misma licencia. Sin anuncios ni telemetría."),
                            "muted", wrap=True))
        lay.addWidget(label(tr("Licencias de terceros: THIRD_PARTY_NOTICES.md"), "caption"))
        tour2 = QPushButton(tr("Ver el tutorial"))
        tour2.clicked.connect(self.tutorial.emit)
        gh = QPushButton(tr("Página del proyecto"))
        gh.setProperty("kind", "flat")
        gh.clicked.connect(lambda: tools.open_with_default(f"https://github.com/{UPDATE_REPO}"))
        bug = QPushButton(tr("Informar de un problema"))
        bug.setProperty("kind", "flat")
        bug.setToolTip(tr("Abre una incidencia en GitHub. Si algo falló, adjunta el registro de errores."))
        bug.clicked.connect(lambda: tools.open_with_default(f"https://github.com/{UPDATE_REPO}/issues/new"))
        errs = QPushButton(tr("Registro de errores"))
        errs.setProperty("kind", "flat")
        errs.setToolTip(tr("Carpeta con el registro local de errores. Nunca se envía: solo lo ves tú."))
        errs.clicked.connect(self._open_error_log)
        lay.addLayout(h_layout(tour2, gh, bug, errs, None))
        add("about", p)

        p, lay = section(tr("Actualizaciones"))
        lay.addWidget(self._check("update_check", tr("Buscar versiones nuevas automáticamente")))
        lay.addWidget(label(tr("Una vez al día como mucho, en GitHub. Nada se instala sin que pulses «Actualizar»; "
                               "el instalador se comprueba con su suma SHA-256 y conserva tus ajustes y datos."),
                            "caption", wrap=True))
        self.upd_status = label("", "muted", wrap=True)
        self.btn_upd = QPushButton(tr("Buscar ahora"))
        self.btn_upd.clicked.connect(self._check_updates_now)
        lay.addLayout(h_layout(self.btn_upd, self.upd_status, None))
        add("about", p)

        # ------------------------------------------------------------ navegación
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Buscar ajustes"))
        self.search.setClearButtonEnabled(True)
        self.search.addAction(tm().icon("search", 16), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self._filter)
        self.nav = QListWidget()
        self.nav.setFixedWidth(218)
        self.nav.setIconSize(QSize(18, 18))
        self.nav.setSpacing(1)
        self.nav.setAccessibleName(tr("Apartados de Ajustes"))
        self.stack = QStackedWidget()
        self._index: dict[str, str] = {}
        for key, title, icon, desc in CATEGORIES:
            it = QListWidgetItem(tm().icon(icon, 18), tr(title))
            it.setData(Qt.ItemDataRole.UserRole, key)
            it.setSizeHint(QSize(200, 36))
            self.nav.addItem(it)
            page = QWidget()
            col = QVBoxLayout(page)
            col.setContentsMargins(4, 0, 10, 8)
            col.setSpacing(10)
            col.addWidget(label(title, "h2"))
            col.addWidget(label(desc, "muted"))
            words = [title, desc, tr(title), tr(desc)]
            for panel in self._cats[key]:
                col.addWidget(panel)
                words += [w.text() for w in panel.findChildren(QLabel) + panel.findChildren(QCheckBox)
                          + panel.findChildren(QPushButton)]
            col.addStretch(1)
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.stack.addWidget(scroll)
            self._index[key] = _fold(" ".join(words))
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)
        side = QVBoxLayout()
        side.setSpacing(8)
        side.addWidget(self.search)
        side.addWidget(self.nav, 1)
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(16)
        root.addLayout(side)
        root.addWidget(self.stack, 1)
        self._refresh_assoc()

    # ------------------------------------------------------------------ navegación y búsqueda
    def open_category(self, key: str) -> None:
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.ItemDataRole.UserRole) == key:
                self.nav.setCurrentRow(i)
                return

    def _filter(self, text: str):
        q = _fold(text.strip())
        first = None
        for i in range(self.nav.count()):
            it = self.nav.item(i)
            hit = not q or all(w in self._index[it.data(Qt.ItemDataRole.UserRole)] for w in q.split())
            it.setHidden(not hit)
            if hit and first is None:
                first = i
        if first is not None and (self.nav.currentItem() is None or self.nav.currentItem().isHidden()):
            self.nav.setCurrentRow(first)

    def _update_storage(self):
        def size(p) -> int:
            total = 0
            for root, _d, files in os.walk(p):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            return total

        from aero.core.formats import human_size
        from aero.ui.async_util import run_async

        # Recorrer la caché (miles de miniaturas) en el hilo de la interfaz la congelaba un momento.
        data, cache = data_dir(), cache_dir()
        self.storage.setText(tr("Calculando…"))
        run_async(lambda: (size(data), size(cache)),
                  lambda r: self.storage.setText(tr("Datos: {a} · Caché: {b}", a=human_size(r[0]),
                                                    b=human_size(r[1]))), None, self)

    # ------------------------------------------------------------------ asociaciones
    def _refresh_assoc(self):
        while self.assoc_grid.count():
            it = self.assoc_grid.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if os.name != "nt":
            self.assoc_grid.addWidget(label(tr("Solo disponible en Windows"), "muted"), 0, 0)
            return
        registered = associations.is_registered()
        st = associations.status()
        for i, cat in enumerate(associations.CATEGORIES):
            mine, total = st[cat.key]
            name = label(tr(cat.label))
            exts = label(" ".join(e.lstrip(".") for e in cat.exts), "caption")
            exts.setWordWrap(True)
            if mine:
                state = tr("Predeterminado") if mine == total else tr("Predeterminado en {n}/{total}", n=mine,
                                                                       total=total)
            else:
                state = tr("Disponible") if registered else tr("Sin registrar")
            badge = label(state, "accent" if mine else "muted")
            self.assoc_grid.addWidget(name, i, 0)
            self.assoc_grid.addWidget(exts, i, 1)
            self.assoc_grid.addWidget(badge, i, 2, Qt.AlignmentFlag.AlignRight)
        self.assoc_grid.setColumnStretch(1, 1)
        mine = sum(m for m, _t in st.values())
        total = sum(t for _m, t in st.values())
        self.default_state.setText(tr("AERO Player ya abre todos sus tipos de archivo.") if mine == total else
                                   tr("AERO Player abre {n} de {total} tipos de archivo.", n=mine, total=total))
        self.btn_register.setText(tr("Volver a registrar") if registered else tr("Registrar AERO Player"))
        self.btn_unregister.setVisible(registered)

    def _register(self):
        try:
            associations.register()
        except OSError as e:
            self.message.emit(tr("No se pudo registrar: {e}", e=e), "error")
            return
        self._refresh_assoc()
        self.message.emit(tr("Registrado. Elige AERO Player en la Configuración de Windows."), "ok")
        associations.open_default_apps_settings()

    def _open_error_log(self):
        from aero.core import crashlog

        tools.open_with_default(str(crashlog.folder()))

    def _make_default_all(self):
        from aero.core import defaults

        result = defaults.make_default_everywhere()
        if result == defaults.SETTINGS:
            self._refresh_assoc()
            self.message.emit(tr("En la página que se ha abierto, pulsa «Establecer predeterminada»."), "info")
        elif result == defaults.DONE:
            self.message.emit(tr("Listo: tus archivos se abrirán con AERO Player."), "ok")
        elif sys.platform == "darwin":
            self.message.emit(tr("En el Finder: Obtener información › Abrir con › AERO Player › Cambiar todo."), "info")
        else:
            self.message.emit(tr("No se pudo cambiar automáticamente. Elige AERO Player en «Abrir con» de tu gestor "
                                 "de archivos."), "error")

    def _check_updates_now(self):
        from aero.ui.update_ui import check_in_background, show_update

        self.btn_upd.setEnabled(False)
        self.upd_status.setText(tr("Buscando…"))

        def result(rel, err):
            self.btn_upd.setEnabled(True)
            if err:
                self.upd_status.setText(tr("No se pudo consultar: {e}", e=err))
            elif rel is None:
                self.upd_status.setText(tr("Tienes la última versión ({v}).", v=__version__))
            else:
                self.upd_status.setText(tr("Versión nueva disponible: {v}", v=rel.version))
                show_update(rel, self.s, None, self.window())

        check_in_background(self.s, result, force=True, owner=self)

    def _toggle_foreign_icons(self, on: bool):
        from PySide6.QtWidgets import QMessageBox

        from aero.core import explorer_icons
        from aero.ui.async_util import run_async

        if on:
            n = len(explorer_icons.plan())
            box = QMessageBox(QMessageBox.Icon.Question, tr("Iconos AERO en el Explorador"),
                              tr("¿Usar los iconos AERO en {n} tipos de archivo que abren otros programas?", n=n),
                              parent=self)
            box.setInformativeText(tr("Solo cambia el icono que ves en el Explorador, para tu usuario. Los archivos "
                                      "se siguen abriendo con el mismo programa. Programas, scripts, accesos directos "
                                      "y archivos de sistema conservan su icono. Se guarda una copia para poder "
                                      "restaurarlo."))
            yes = box.addButton(tr("Usar iconos AERO"), QMessageBox.ButtonRole.AcceptRole)
            box.addButton(tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
            box.exec()
            if box.clickedButton() is not yes:
                self.icons_foreign.blockSignals(True)
                self.icons_foreign.setChecked(False)
                self.icons_foreign.blockSignals(False)
                return
            self.s.set("explorer_icons_foreign", True)
            run_async(explorer_icons.apply, lambda n: (self._refresh_icons(),
                                                       self.message.emit(tr("Iconos AERO aplicados ({n})", n=n), "ok")),
                      lambda e: self.message.emit(tr("No se pudieron aplicar los iconos: {e}", e=e), "error"), self)
        else:
            self._restore_icons()

    def _restore_icons(self):
        from aero.core import explorer_icons
        from aero.ui.async_util import run_async

        self.s.set("explorer_icons_foreign", False)
        self.icons_foreign.blockSignals(True)
        self.icons_foreign.setChecked(False)
        self.icons_foreign.blockSignals(False)
        run_async(explorer_icons.restore, lambda n: (self._refresh_icons(),
                                                     self.message.emit(tr("Iconos originales restaurados ({n})", n=n),
                                                                       "ok")),
                  lambda e: self.message.emit(tr("No se pudieron restaurar los iconos: {e}", e=e), "error"), self)

    def _refresh_icons(self):
        if os.name != "nt":
            self.icons_state.setText(tr("Solo disponible en Windows"))
            return
        from aero.core import explorer_icons
        from aero.ui.async_util import run_async

        run_async(lambda: (explorer_icons.applied(), len(explorer_icons.plan())),
                  lambda r: self.icons_state.setText(tr("Con icono AERO: {a} de {t} tipos de otros programas",
                                                        a=r[0], t=r[1])), None, self)

    def _unregister(self):
        associations.unregister()
        self._refresh_assoc()
        self.message.emit(tr("Registro eliminado"), "ok")

    def showEvent(self, e):
        super().showEvent(e)
        self._refresh_assoc()
        self._refresh_icons()
        self._update_storage()

    # ------------------------------------------------------------------ utilidades
    def _check(self, key: str, text: str) -> QCheckBox:
        cb = QCheckBox(tr(text))
        cb.setChecked(bool(self.s.get(key)))
        cb.toggled.connect(lambda on: self.s.set(key, on))
        return cb

    def _add_dir(self, key: str, lw: QListWidget):
        d = QFileDialog.getExistingDirectory(self, tr("Elegir carpeta"))
        if d and d not in self.s.get(key):
            self.s.set(key, list(self.s.get(key)) + [d])
            lw.addItem(d)

    def _rem_dir(self, key: str, lw: QListWidget):
        it = lw.currentItem()
        if it:
            self.s.set(key, [x for x in self.s.get(key) if x != it.text()])
            lw.takeItem(lw.row(it))

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("Carpeta de salida"), self.out_dir.text())
        if d:
            self.out_dir.setText(d)
            self.s.set("output_dir", d)

    def _pick_tool(self, key: str, name: str, edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, f"Localizar {name}", "", "Ejecutables (*.exe)")
        if path:
            edit.setText(path)
            self.s.set(key, path)
            tools.set_override(name, path)

    def _ql_key(self):
        seq = self.ql_key.keySequence().toString()
        if seq:
            self.s.set("quicklook_hotkey", seq)
            self.quicklook_changed.emit()

    def _save_shortcuts(self):
        self.s.set("shortcuts", {k: e.keySequence().toString() for k, e in self.key_edits.items()})
        self.shortcuts_changed.emit()

    def _reset_shortcuts(self):
        for k, e in self.key_edits.items():
            e.setKeySequence(QKeySequence(DEFAULT_SHORTCUTS[k]))
        self._save_shortcuts()

    def _clear_cache(self):
        shutil.rmtree(cache_dir(), ignore_errors=True)
        cache_dir()
        if hasattr(self, "storage"):
            self._update_storage()

    def _clear_all(self):
        r = QMessageBox.question(self, tr("Borrar datos"), tr("Se borrarán biblioteca, listas, favoritos, historial y caché. "
                                                       "Tus archivos no se tocan. ¿Continuar?"))
        if r == QMessageBox.StandardButton.Yes:
            self._clear_cache()
            self.clear_all.emit()
