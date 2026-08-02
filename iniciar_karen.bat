@echo off
chcp 65001 >nul
title KAREN - Asistente personal de Tony
cd /d %~dp0
set PYTHONIOENCODING=utf-8

echo.
echo   Arrancando KAREN...
echo   (cierra esta ventana para apagarlo)
echo.

if exist "KAREN.exe" (
  start "KAREN" /wait "KAREN.exe"
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -u main.py
) else (
  python -u main.py
)

echo.
pause
