# Spotify: decisión definitiva (2.1.0) — retirado

**Decisión:** la integración con Spotify se ha **eliminado por completo** en AERO Player 2.1.0.

## Por qué no se arregla

Se revisó otra vez, con la documentación oficial de la API web de Spotify (noviembre de 2026), si podía
funcionar de forma completa y estable para cualquier persona que instale AERO Player. No puede, por límites que
no dependen de AERO Player:

| Límite de Spotify | Consecuencia |
|---|---|
| Las apps nuevas solo funcionan en **modo de desarrollo**: el propietario necesita **Premium** y la app admite **5 usuarios** añadidos a mano. | Cada persona tendría que crear su propia app en el panel de desarrolladores, copiar un Client ID y registrar direcciones de vuelta. No es una experiencia «instalar y usar». |
| El **acceso ampliado** solo se concede a **empresas** con más de 250 000 usuarios activos. | AERO Player no puede publicar un Client ID para todo el mundo. |
| **Reproducir** por la API solo controla la app oficial (Spotify Connect) y solo con **Premium**; las condiciones prohíben reproducir el audio en otro reproductor. | AERO Player nunca podría reproducir Spotify en su propia interfaz: solo mandar órdenes a otra aplicación. |
| La dirección de vuelta exige coincidencia exacta y puertos fijos (80 u 8888). | Falla si otro programa usa esos puertos o si el usuario registra mal la dirección; fue la causa de los errores de 2.0.x. |

Mantener a medias una función que para la mayoría de usuarios no puede funcionar contradice la regla del
producto (nada roto, a medias ni simulado). Por eso se ha retirado en lugar de dejarla «en pruebas».

## Qué se ha quitado

* Código: `aero/spotify/` (inicio de sesión PKCE, cliente de la API, cifrado del token) y
  `aero/ui/pages/spotify_page.py`.
* Interfaz: la pestaña «Spotify» de Música, sus botones, menús, avisos y la barra «Sonando en Spotify».
* Pruebas y comprobaciones de idioma de esas pantallas.
* Datos locales: al iniciar 2.1.0 se borra **solo** el token cifrado (`spotify.bin`, `spotify.part`) de la
  carpeta de datos de AERO. No se toca nada más del usuario (ni música, ni listas, ni ajustes).
* No había dependencias exclusivas de Spotify (usaba la biblioteca estándar y `pywin32`, que se siguen usando
  para otras funciones).

Las claves de traducción que solo usaba Spotify se quedan en los catálogos sin uso (no molestan y evitan
desordenar los archivos de los traductores); `tools/i18n_keys.py` solo exige las que usa el código.

## Si algún día vuelve

Solo tendría sentido si Spotify abriera un acceso para aplicaciones de escritorio de terceros sin el límite de
5 usuarios. Entonces habría que rehacerla desde cero con esas condiciones; el código anterior está en el historial
de git (versión 2.0.1).
