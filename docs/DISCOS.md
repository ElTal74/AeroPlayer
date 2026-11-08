# Imágenes de disco en AERO Player (2.1.0)

Formatos: **ISO, IMG, BIN/CUE, NRG, MDF y UDF**.
Se reconocen también MDS, CCD, VHD, VHDX, DMG y TOAST: tienen icono de disco, pero no se exploran por dentro.

## Explorar y extraer sin montar

* La lectura usa `pycdlib` (LGPL-2.1, Python puro). Entiende ISO 9660, Joliet (nombres largos), Rock Ridge y UDF,
  así que sirve para discos de datos de CD, DVD y Blu-ray. Se usa el sistema de nombres más completo del disco.
* La disposición física se detecta por la firma del sistema de archivos (`CD001` o `BEA01` en el sector 16):
  * sectores de 2048 bytes (ISO, IMG);
  * sectores brutos de 2352 en modo 1 o 2 (BIN, MDF);
  * cabecera de Nero (NRG);
  * lo que indique el `.cue`.

  Un adaptador presenta todo como una ISO normal.
* Se abren en Archivos como una carpeta, con «Extraer los seleccionados en…».
  * Hay progreso real por bytes y se puede cancelar.
  * Al cancelar se deshace lo creado.
  * Se puede elegir qué hacer si el archivo ya existe: omitir o renombrar.
* Si la imagen no se puede leer, se informa con claridad y no se inventa contenido. Ocurre con un CD de audio
  (pistas AUDIO), con una imagen sin sistema de archivos reconocible y con una imagen dañada. Si falla `pycdlib`,
  las ISO se intentan además con bsdtar.

## Montar en Windows

* La opción «Montar en Windows» del menú contextual aparece solo con ISO, IMG, VHD y VHDX, que son los formatos
  que Windows monta de forma nativa. Siempre es a petición del usuario y usa `Mount-DiskImage`.
* Al montar, AERO espera a que Windows asigne la letra y abre la unidad. «Desmontar» la expulsa.
* Si Windows conecta la imagen pero no le da letra, AERO la desconecta y lo explica: no se queda ninguna unidad
  fantasma. Pasa cuando Windows no reconoce el contenido o cuando la imagen está en una carpeta con permisos que el
  servicio de discos virtuales no puede leer.
* Nunca se simula un montaje: si Windows no lo hace, se dice. Las imágenes se pueden explorar y extraer sin montar.

## Pruebas

`tests/test_v21.py` comprueba con imágenes reales:

* listar ISO, BIN/CUE, BIN sin CUE y NRG, con nombres largos y la ñ;
* extraer lo seleccionado o todo, verificando cada byte;
* cancelar sin dejar restos;
* que un CD de audio o una imagen basura da un error claro;
* montar y desmontar con Windows una ISO creada por IMAPI2;
* que un montaje que falla no deja nada conectado.
