#!/usr/bin/env bash
# Compila AERO Player en Linux o macOS (el equivalente de build.ps1 en Windows).
#   Linux:  dist/AeroPlayer-<versión>-linux-x86_64.tar.gz  (carpeta + install.sh para el menú de aplicaciones)
#   macOS:  dist/AeroPlayer-<versión>-macos-arm64.dmg      (AeroPlayer.app para arrastrar a Aplicaciones)
# Uso: bash packaging/build_unix.sh   (con el entorno de Python activado o PY=/ruta/python)
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PY:-python3}"
VERSION="$("$PY" -c 'import aero; print(aero.__version__)')"
OS="$(uname -s)"
ARCH="$(uname -m)"
[ "$ARCH" = "aarch64" ] && ARCH="arm64"
echo "AERO Player $VERSION · $OS $ARCH"

echo "1/5 Núcleo nativo (Rust)"
"$PY" tools/build_native.py || echo "   Sin Rust: se usará la versión Python del núcleo."

echo "2/5 Módulos de Qt imprescindibles"
"$PY" -c "import PySide6.QtPdf, PySide6.QtPdfWidgets, PySide6.QtMultimedia" \
  || { echo "Falta un módulo de Qt (QtPdf / QtMultimedia): instala requirements.txt."; exit 1; }

echo "3/5 Iconos"
QT_QPA_PLATFORM="${QT_QPA_PLATFORM:-offscreen}" "$PY" packaging/make_icon.py

echo "4/5 PyInstaller"
"$PY" -m PyInstaller packaging/aero.spec --noconfirm --clean --distpath dist --workpath build

echo "5/5 Paquete"
cd dist
if [ "$OS" = "Darwin" ]; then
  OUT="AeroPlayer-$VERSION-macos-$ARCH.dmg"
  rm -rf dmg "$OUT"
  mkdir dmg
  cp -R AeroPlayer.app dmg/
  ln -s /Applications dmg/Applications 2>/dev/null || true
  hdiutil create -volname "AERO Player" -srcfolder dmg -ov -format UDZO "$OUT"
  rm -rf dmg
  SUMS="SHA256SUMS-macos.txt"
  shasum -a 256 "$OUT" > "$SUMS"
else
  OUT="AeroPlayer-$VERSION-linux-$ARCH.tar.gz"
  cp ../packaging/linux/install.sh ../packaging/linux/aero-player.desktop ../packaging/aero.png AeroPlayer/
  chmod +x AeroPlayer/install.sh AeroPlayer/AeroPlayer
  tar -czf "$OUT" AeroPlayer
  SUMS="SHA256SUMS-linux.txt"
  sha256sum "$OUT" > "$SUMS"
fi
cat "$SUMS"
echo "Listo: dist/$OUT"
