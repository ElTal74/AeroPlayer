<#
  Firma digital de los ejecutables de AERO Player (Authenticode, SHA-256, con sello de tiempo).

  Solo firma si hay un certificado de firma de código configurado; si no, avisa y no hace nada (el paquete se
  genera igual, sin firmar). Lo usa packaging\build.ps1.

  Configuración (variables de entorno o secretos de GitHub Actions):
    AERO_SIGN_PFX           ruta a un certificado .pfx      + AERO_SIGN_PASSWORD con su contraseña
    AERO_SIGN_THUMBPRINT    o la huella de un certificado ya instalado en «Personal» (p. ej. un token USB)
    AERO_SIGN_TIMESTAMP     servidor de sellos de tiempo (por defecto http://timestamp.digicert.com)

  Ver docs/FIRMA.md: para que SmartScreen deje de avisar hace falta un certificado emitido por una autoridad
  reconocida a nombre de David Seva Gonzalvez (los certificados hechos en casa no sirven).
#>
param([Parameter(Mandatory = $true)][string[]]$Files)

$pfx = $env:AERO_SIGN_PFX
$thumb = $env:AERO_SIGN_THUMBPRINT
if (-not $pfx -and -not $thumb) {
    Write-Host "   Sin certificado de firma configurado: los ejecutables quedan sin firmar (ver docs\FIRMA.md)." -ForegroundColor Yellow
    exit 0
}
$signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" -ErrorAction SilentlyContinue |
    Sort-Object FullName | Select-Object -Last 1
if (-not $signtool) { throw "No se encuentra signtool.exe (Windows SDK)." }
$ts = if ($env:AERO_SIGN_TIMESTAMP) { $env:AERO_SIGN_TIMESTAMP } else { "http://timestamp.digicert.com" }
foreach ($f in $Files) {
    $cmd = @("sign", "/fd", "SHA256", "/tr", $ts, "/td", "SHA256", "/d", "AERO Player")
    if ($pfx) { $cmd += @("/f", $pfx); if ($env:AERO_SIGN_PASSWORD) { $cmd += @("/p", $env:AERO_SIGN_PASSWORD) } }
    else { $cmd += @("/sha1", $thumb) }
    & $signtool.FullName @cmd $f
    if ($LASTEXITCODE -ne 0) { throw "No se pudo firmar $f" }
    & $signtool.FullName verify /pa $f | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "La firma de $f no se verifica" }
    Write-Host "   Firmado: $f"
}
