# Registro de cambios

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
- **Arreglado:** un cierre inesperado poco frecuente relacionado con los avisos de actualización y las novedades.
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
