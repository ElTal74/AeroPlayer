#!/usr/bin/env bash
# Instala AERO Player para tu usuario (sin sudo): copia la carpeta y lo añade al menú de aplicaciones y a
# «Abrir con». Para desinstalar: ./install.sh --uninstall
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="${XDG_DATA_HOME:-$HOME/.local/share}/aero-player"
APPS="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor/512x512/apps"
BIN="$HOME/.local/bin"

if [ "${1:-}" = "--uninstall" ]; then
  rm -rf "$DEST" "$APPS/aero-player.desktop" "$ICONS/aero-player.png" "$BIN/aero-player"
  command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
  echo "AERO Player desinstalado. Tus ajustes siguen en ~/.local/share/AeroPlayer."
  exit 0
fi

mkdir -p "$DEST" "$APPS" "$ICONS" "$BIN"
if [ "$SRC" != "$DEST" ]; then
  rm -rf "$DEST"
  cp -a "$SRC" "$DEST"
fi
cp "$SRC/aero.png" "$ICONS/aero-player.png"
sed "s#@EXEC@#\"$DEST/AeroPlayer\"#" "$SRC/aero-player.desktop" > "$APPS/aero-player.desktop"
ln -sf "$DEST/AeroPlayer" "$BIN/aero-player"
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "${ICONS%/512x512/apps}" || true
echo "AERO Player instalado: búscalo en el menú de aplicaciones o ejecuta «aero-player»."
