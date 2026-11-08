# Hoja de ruta

## 1.0 (actual, primera versión pública)
Todo lo descrito en `CHANGELOG.md`: reproductor, visor, editores, conversor, compresión, discos, torrents,
iconos AERO en el Explorador y núcleo de archivos y etiquetas en Rust.

## Desarrollo previo (versión interna 2.1)
Iconos AERO por categoría, imágenes de disco (explorar, extraer, montar) y BitTorrent con motor propio; Spotify
retirado (ver `docs/SPOTIFY.md`).

## Desarrollo previo (versión interna 2.0)
Inglés por defecto y traducción completa con comprobación al compilar, perfiles de rendimiento que se aplican,
Spotify con la API oficial, explorador con iconos reales y ejecución segura, Paint en la barra lateral,
manipulación directa en el editor de vídeo, sin decoraciones de temporada y menos memoria. Ver CHANGELOG.md.

## Siguiente (1.1, prioridad por impacto)
0. **Rust, fase R1** (núcleo de archivos con PyO3), en cuanto Rust y las Build Tools estén instalados con permiso.
1. **BitTorrent**: enlaces magnet y DHT (BEP 9/5), con el mismo criterio de no abrir puertos sin permiso;
   recordar las descargas entre sesiones.
2. **Editor de vídeo**: fotogramas clave para animar posición, escala y giro; recorte con el ratón también con
   giros de 90°; vista previa en tiempo real de varios vídeos superpuestos.
3. **Actualizaciones**: comprobar versiones, descargar el instalador, verificar su SHA-256 y pedir permiso
   (bloqueado hasta tener un canal de publicación con sumas firmadas).
4. **Archivos**: firma digital del ejecutable (editor y certificado) en el aviso antes de ejecutar.
5. **Borradores** también para documentos, hojas y presentaciones.
## Más adelante
* Paquete MSIX firmado (menú compacto de Windows 11 y «Aplicaciones predeterminadas» más integradas).
* Vista previa del Explorador (preview handler) como alternativa a la vista rápida.
* pt-PT y otros idiomas (la arquitectura ya admite variantes con herencia).
