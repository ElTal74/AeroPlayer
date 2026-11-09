# Registro de cambios

## 1.3.0 · Letras, teclas multimedia y más estabilidad

- **Letras sincronizadas.**
  - Con un archivo `.lrc` junto a la canción o con la letra incrustada en las etiquetas (MP3, FLAC, OGG,
    M4A), el reproductor la muestra con la línea que suena resaltada.
  - Clic en una línea para saltar a ese momento.
  - El botón «Letra» la muestra u oculta.
- **Teclas multimedia del teclado** (reproducir/pausa, siguiente, anterior, detener).
  - En Windows funcionan también con AERO Player en segundo plano, solo mientras reproduce o está en pausa,
    para no quitárselas a otras aplicaciones.
  - Se pueden desactivar en Ajustes › Reproducción.
- **Barra de tareas de Windows:** botones Anterior, Reproducir/Pausa y Siguiente en la miniatura de la
  ventana, y el progreso de las conversiones en el icono.
- **Registro local de errores** y botón «Informar de un problema» en Ajustes › Acerca de. El registro nunca
  se envía.
- **Arreglado: cuelgue al cerrar un vídeo.**
  - En raras ocasiones la ventana se quedaba congelada.
  - Causa: el hilo de FFmpeg y el de la interfaz se esperaban mutuamente.
- **Arreglado: cierre al parar los atajos justo después de iniciarlos.**
- **Arreglado:** en Linux y macOS el programa podía cerrarse de golpe al cerrar una ventana con música,
  o al convertir dos PDF a la vez.
- **Arreglado:** varias conexiones podían llamar a una ventana ya cerrada (ajustes de rendimiento,
  conversor, barra lateral).
- **Más rápido y ligero.**
  - Arranque unos 60 ms más rápido: mutagen y argparse solo se cargan si hacen falta.
  - La ventana de vídeo ya no ejecuta código Python en cada fotograma.
  - Descargas de torrents más fiables (ninguna conexión se pierde a medias).
- **Web.**
  - Capturas en WebP: unas 6 veces más ligeras, y la página carga mucho antes.
  - Nueva captura de las letras.
  - Imagen al compartir el enlace (WhatsApp, X, Discord…).
  - Datos para buscadores y página 404 con estilo Aero.

## 1.2.0 · Windows, Linux y macOS

- **Ahora también en Linux y macOS.**
  - Linux: paquete `tar.gz` de 64 bits con `install.sh`, que lo añade al menú de aplicaciones y a «Abrir con».
  - macOS: `AeroPlayer.app` en un DMG, para Mac con Apple Silicon y macOS 14 o posterior.
  - Todo funciona igual salvo lo exclusivo del Explorador de Windows: iconos AERO, clic derecho y vista rápida.
  - El núcleo en Rust también se compila para Linux y macOS.
- **Usar AERO Player para todo.**
  - Un botón en Ajustes › Archivos y asociaciones y una casilla al final de la instalación lo hacen predeterminado
    para todo lo que abre: música, vídeo, fotos, PDF, documentos, comprimidos, discos y torrents.
  - En Windows se abre su página en Aplicaciones predeterminadas para confirmarlo con un clic. Windows no deja
    imponerlo.
  - En Linux y macOS se aplica directamente.
  - Ajustes muestra cuántos tipos abre ya.
- **Inicio automático** también en Linux y macOS.
- **«Tu equipo»** muestra procesador, memoria, discos y batería también en Linux y macOS.
- **Listas:** las listas vacías explican cómo llenarlas, y el recuento dice «12 elementos» en lugar de un número
  suelto.
- **Conversor:** con la cola vacía ya no se ven una barra y unos botones que no hacían nada.
- **Arreglado:** algunos textos salían en español en otros idiomas: los nombres de las categorías de archivos,
  «Disponible», «Cola» y algunos botones.
- **Arreglado:** los PDF creados desde documentos tienen el texto bien unido al copiarlo o buscar en él.
- **Arreglado:** la ventana de progreso de comprimir o extraer no se cerraba sola si aparecía justo bajo el
  puntero. Ahora solo espera si mueves el ratón encima, y su cuenta atrás está traducida.
- **Web:** apartado de descargas con Windows, Linux y macOS; reconoce tu sistema.

## 1.1.0 · Actualizaciones automáticas y más detalles

- **Actualizaciones desde GitHub.**
  - AERO Player avisa cuando hay una versión nueva y muestra sus novedades.
  - Con el instalador se actualiza con un clic: descarga, comprueba la suma SHA-256 y conserva tus accesos
    directos, el menú del clic derecho y las asociaciones.
  - La versión portable avisa y abre la página de descarga.
  - Si GitHub falla un momento, reintenta. Si github.com está caído, descarga por la API de GitHub.
  - Se puede desactivar o buscar a mano en Ajustes › Acerca de.
- **Novedades tras actualizar:** la primera vez que abres una versión nueva se muestra qué ha cambiado.
- **Temporizador de apagado** en la barra del reproductor: 15 min a 2 h o al final de la pista, con el volumen
  bajando poco a poco.
- **Esquinas redondeadas en todas las ventanas,** también en el reproductor de vídeo, el visor y los editores.
- **Conversor más claro.**
  - La cola vacía explica qué hacer.
  - Los archivos añadidos se ven con su icono, su carpeta y un recuento.
  - Elegir la carpeta de salida es más fácil.
- **Biblioteca:** resumen con el número de canciones, vídeos, álbumes, artistas, carpetas y series.
- **Editor de vídeo:** el panel de medios y la línea de tiempo vacíos indican cómo empezar.
- **Botones desactivados** más fáciles de distinguir.
- **Arreglado:** al abrir varios archivos a la vez desde el menú del clic derecho, a veces llegaban por separado.
- **Arreglado:** en las descargas de la versión 1.0.0 faltaba el componente del visor PDF. Por eso el visor no se
  abría, tampoco con fotos ni documentos. Ahora la compilación comprueba que no falte nada, y si un día faltara el
  visor PDF, solo fallarían los PDF y la aplicación diría por qué.
- **Arreglado:** cierres inesperados poco frecuentes. Python podía destruir ventanas de Qt desde un hilo secundario; ahora la limpieza de memoria se hace siempre en el hilo principal.
- **Firma digital preparada:** los ejecutables se firman automáticamente cuando hay un certificado configurado.
- **Copyright y licencia:** © 2026 David Seva Gonzalvez, GPL-3.0-or-later. Ver `NOTICE.md`.
- **Web nueva** en 7 idiomas, con animaciones, capturas en el idioma de la página y una comparativa entre el
  instalador y la versión portable.

## 1.0.0 · Primera versión pública

AERO Player es un reproductor, visor y conjunto de herramientas multimedia para Windows 10 y 11. Tiene el estilo
Frutiger Aero: cristal, burbujas, cielo y agua. Es software libre (GPL-3.0-or-later) y no tiene telemetría.

- **Reproductor de música y vídeo.**
  - Cola, aleatorio, repetir, velocidad, pistas de audio y subtítulos.
  - Pantalla completa, y recuerda la posición y el volumen.
  - Series con temporadas, siguiente episodio y «Continuar viendo».
- **11 visualizadores** que analizan el sonido real, con galería, colores e intensidad.
- **Biblioteca** de música, vídeos, series, álbumes, artistas y carpetas, con escaneo incremental muy rápido
  gracias a un núcleo en Rust.
- **Visor universal.**
  - Fotos (también HEIC y AVIF) en la ventana principal, con zoom, girar, voltear y anterior/siguiente.
  - PDF con búsqueda, documentos, hojas de cálculo, presentaciones, texto y código.
  - Comprimidos e imágenes de disco sin extraer.
- **Vista rápida** con Espacio, desde el Explorador de Windows.
- **Archivos:** explorador con la familia de iconos AERO por categoría, búsqueda global y ejecución segura (nada se
  abre sin confirmar).
- **Editores.**
  - Imágenes, con capas, color, filtros, dibujo y texto, y AERO Paint.
  - Vídeo, con línea de tiempo, efectos, transiciones, títulos y manipulación directa en el visor.
  - Documentos, hojas y presentaciones.
  - PDF a documento editable, con OCR de Windows.
- **Conversor por lotes** de imágenes, audio, vídeo y documentos, con perfiles, pausa y reintento.
- **Comprimir y extraer** ZIP, 7Z, RAR, TAR e ISO, con contraseñas AES-256, protección contra rutas peligrosas y
  cancelación sin restos.
- **Imágenes de disco** ISO, IMG, BIN/CUE, NRG y MDF: explorar, extraer y montar con Windows.
- **Descargas BitTorrent.** Nada empieza sin confirmar, nada se ejecuta, no abre puertos y se puede desactivar.
- **Integración con Windows.**
  - «Abrir con» y aplicaciones predeterminadas, siempre confirmadas por ti.
  - Iconos AERO en el Explorador.
  - Menú del clic derecho.
- **7 idiomas:** inglés, español, alemán, italiano, portugués de Brasil, ruso y chino.
- **Temas, fondos animados y perfiles de rendimiento** que se aplican al momento.
- **Instalador propio** que no necesita administrador. Actualiza conservando tus datos.

El historial de las versiones de desarrollo anteriores a esta está en `docs/historial/CHANGELOG_DESARROLLO.md`.
