@echo off
REM =====================================================
REM  JARVIS - Encender Bluetooth de tu PC
REM  Ejecuta este archivo CLIC DERECHO > Ejecutar como administrador
REM =====================================================
echo Activando servicio de Bluetooth...
sc config bthserv start= auto >nul 2>&1
net start bthserv >nul 2>&1

echo Encendiendo el adaptador Realtek si estaba desactivado...
powershell -NoProfile -Command "Get-PnpDevice -Class Bluetooth | Where-Object {$_.Status -eq 'Error'} | Enable-PnpDevice -Confirm:$false" >nul 2>&1

echo.
echo Bluetooth activado. Cierra esta ventana.
pause
