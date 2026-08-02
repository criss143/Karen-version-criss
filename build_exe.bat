@echo off
chcp 65001 >nul
title JARVIS - Reconstruir EXE
cd /d %~dp0
set PYTHONIOENCODING=utf-8
set AUTO=0
if /i "%1"=="auto" set AUTO=1

echo.
echo   Reconstruyendo JARVIS.exe (launcher delgado)...
echo   El EXE solo arranca el Python del proyecto:
echo   cualquier cambio en VS Code se refleja sin recompilar.
echo.

if not exist ".venv\Scripts\python.exe" (
  echo   [ERROR] No hay entorno .venv. Crea uno antes.
  if %AUTO%==0 pause
  exit /b 1
)

.venv\Scripts\python.exe -m pip install -q pyinstaller
if errorlevel 1 (
  echo   [ERROR] No pude instalar PyInstaller.
  if %AUTO%==0 pause
  exit /b 1
)

if exist "build" rmdir /s /q build
if exist "dist\JARVIS.exe" del /f /q "dist\JARVIS.exe"
if exist "JARVIS.spec" del /f /q "JARVIS.spec"

.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --console ^
  --name JARVIS ^
  --distpath dist ^
  --workpath build ^
  jarvis_launcher.py

if errorlevel 1 (
  echo   [ERROR] Fallo al empaquetar.
  if %AUTO%==0 pause
  exit /b 1
)

rem Copiar a la raiz. Si JARVIS.exe esta corriendo, Windows no deja
rem sobrescribirlo: se avisa y se conserva dist\JARVIS.exe.
copy /y "dist\JARVIS.exe" "JARVIS.exe" >nul 2>nul
if errorlevel 1 (
  echo.
  echo   [AVISO] No pude sobrescribir JARVIS.exe: el programa esta en uso.
  echo   Cierralo y vuelve a correr:  build_exe.bat
  echo   El nuevo EXE queda en:  %cd%\dist\JARVIS.exe
  echo.
  if %AUTO%==0 pause
  exit /b 0
)

echo.
echo   OK - JARVIS.exe listo en:
echo     %cd%\JARVIS.exe
echo     %cd%\dist\JARVIS.exe
echo.
echo   Tip: el EXE lee siempre main.py y core\ de esta carpeta.
echo   Solo vuelve a correr build_exe.bat si cambias jarvis_launcher.py.
echo.
if %AUTO%==0 pause
exit /b 0
