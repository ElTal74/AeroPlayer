# Firma digital de AERO Player

## Por qué avisa Windows

Windows SmartScreen avisa ante cualquier programa descargado que no esté firmado con un certificado de firma de
código de una autoridad reconocida, o que todavía tenga poca «reputación». No es una detección de virus: es la
forma que tiene Windows de decir «no sé quién ha hecho esto».

## Lo que ya está hecho

* Las propiedades del ejecutable y del instalador (clic derecho › Propiedades › Detalles) muestran:
  * **Empresa:** David Seva Gonzalvez;
  * **Copyright:** © 2026 David Seva Gonzalvez;
  * **Producto:** AERO Player.
* «Aplicaciones instaladas» de Windows muestra como **editor** a David Seva Gonzalvez.
* `packaging/sign.ps1` firma `AeroPlayer.exe` y el instalador automáticamente en cuanto hay un certificado
  configurado: Authenticode SHA-256 con sello de tiempo, comprobando la firma después. `build.ps1` lo llama.
* Cada versión publica sus sumas SHA-256, y el actualizador de la aplicación las comprueba antes de instalar.

## Lo que hace falta para que SmartScreen deje de avisar

Un certificado de firma de código **a nombre de David Seva Gonzalvez**, emitido por una autoridad reconocida.
Para dártelo, la autoridad **verifica tu identidad** (documento oficial y, a veces, una videollamada) y cobra por
ello, así que solo puede pedirlo el propio autor. Opciones habituales para un desarrollador independiente:

| Opción | Cómo funciona | Nota |
|---|---|---|
| **Certificado «Open Source Code Signing»** de Certum (Asseco) | Certificado a tu nombre para proyectos de código abierto, en tarjeta o en la nube | De los más asequibles para particulares; muy usado en proyectos libres |
| **Microsoft Artifact Signing** (antes «Trusted Signing») | Servicio de Microsoft en Azure: firmas sin tener el certificado en tu PC | Pago mensual; la validación de identidad para particulares depende del país |
| **Certificado OV/EV** de una autoridad comercial (Sectigo, DigiCert…) | Certificado clásico en token USB | Lo más caro; un EV quita el aviso desde el primer día |
| **SignPath Foundation** | Firma gratuita para proyectos de código abierto que cumplan sus requisitos | El certificado es de la fundación, no aparece tu nombre |

Incluso firmado, un certificado nuevo que no sea EV puede tardar unas semanas en ganar «reputación» en
SmartScreen. El aviso irá desapareciendo a medida que más gente lo descargue.

## Cómo activarlo cuando tengas el certificado

* **En tu PC:**
  * con un archivo `.pfx`: define `AERO_SIGN_PFX` (ruta) y `AERO_SIGN_PASSWORD`;
  * con un certificado instalado o un token USB: define `AERO_SIGN_THUMBPRINT` (la huella);
  * después ejecuta `packaging\build.ps1`.
* **En GitHub** (compilación automática de las versiones): guarda el `.pfx` en Base64 como secreto
  `AERO_SIGN_PFX_BASE64` y la contraseña como `AERO_SIGN_PASSWORD`. El flujo `release.yml` firma si existen.

**No sirve** un certificado autofirmado (hecho en casa) con tu nombre: Windows no confía en él y el aviso
seguiría saliendo, incluso más alarmante.
