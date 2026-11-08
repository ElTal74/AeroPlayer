<#
  Compila AERO Player para Windows: versión portable (carpeta + ZIP), el instalador propio y checksums.

  Uso (desde la raíz del proyecto):
      powershell -ExecutionPolicy Bypass -File packaging\build.ps1
      powershell -ExecutionPolicy Bypass -File packaging\build.ps1 -BundleFFmpeg C:\ruta\a\ffmpeg\bin

  -BundleFFmpeg copia ffmpeg.exe y ffprobe.exe de la carpeta indicada a dist\AeroPlayer\bin.
  Usa solo binarios de una fuente de confianza (p. ej. https://github.com/BtbN/FFmpeg-Builds o gyan.dev)
  y conserva su licencia junto al binario (lo hace este script si encuentra LICENSE* en esa carpeta).
#>
param([string]$BundleFFmpeg = "", [switch]$SkipTests)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) { throw "No se encuentra .venv. Ejecuta primero: python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt" }
$version = (& $py -c "import aero; print(aero.__version__)").Trim()

if (-not $SkipTests) {
    Write-Host "1/6 Pruebas" -ForegroundColor Cyan
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Las pruebas han fallado: no se genera el paquete." }
    # Traducciones completas: todas las claves del código en los 6 idiomas y ninguna pantalla con textos en español
    & $py tools\i18n_keys.py --strict
    if ($LASTEXITCODE -ne 0) { throw "Faltan traducciones: no se genera el paquete." }
    & $py tools\i18n_screens.py --strict
    if ($LASTEXITCODE -ne 0) { throw "Hay pantallas con textos sin traducir: no se genera el paquete." }
}

# Núcleo nativo en Rust (docs/RUST.md). Sin Rust instalado se avisa y el paquete usa la versión Python.
& $py tools\build_native.py
if ($LASTEXITCODE -ne 0) { Write-Host "   Sin núcleo nativo (Rust no disponible): se usará la versión Python." -ForegroundColor Yellow }
& $py -c "from aero.core import native; import sys; sys.exit(0 if native.available() else 1)"
if ($LASTEXITCODE -eq 0) { Write-Host "   Núcleo nativo: sí" } else { Write-Host "   Núcleo nativo: no" -ForegroundColor Yellow }

Write-Host "2/6 Icono" -ForegroundColor Cyan
& $py packaging\make_icon.py

Write-Host "3/6 PyInstaller (programa)" -ForegroundColor Cyan
& $py -m PyInstaller packaging\aero.spec --noconfirm --clean --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller falló." }

if ($BundleFFmpeg) {
    $bin = Join-Path $root "dist\AeroPlayer\bin"
    New-Item -ItemType Directory -Force $bin | Out-Null
    Copy-Item (Join-Path $BundleFFmpeg "ffmpeg.exe"), (Join-Path $BundleFFmpeg "ffprobe.exe") $bin
    Get-ChildItem (Split-Path $BundleFFmpeg) -Filter "LICENSE*" -ErrorAction SilentlyContinue | Copy-Item -Destination $bin
    Write-Host "   FFmpeg incluido en $bin"
}

Write-Host "4/6 Portable (ZIP)" -ForegroundColor Cyan
$zip = Join-Path $root "dist\AeroPlayer-$version-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\AeroPlayer\*" -DestinationPath $zip

Write-Host "5/6 Instalador propio" -ForegroundColor Cyan
& $py packaging\make_payload.py
if ($LASTEXITCODE -ne 0) { throw "No se pudo crear el paquete del instalador." }
& $py -m PyInstaller packaging\setup.spec --noconfirm --clean --distpath dist --workpath build\setup
if ($LASTEXITCODE -ne 0) { throw "PyInstaller (instalador) falló." }

Write-Host "6/6 Checksums" -ForegroundColor Cyan
Get-ChildItem dist -File | Where-Object { $_.Name -like "AeroPlayer-$version-*" } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content -Encoding utf8 dist\SHA256SUMS.txt
Get-Content dist\SHA256SUMS.txt
Write-Host "Listo. Resultado en la carpeta dist\" -ForegroundColor Green
