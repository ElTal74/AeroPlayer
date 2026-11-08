@echo off
rem Lanzador para ejecutar AERO Player desde el código fuente sin consola.
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Falta el entorno .venv. Ejecuta: python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" -m aero %*
