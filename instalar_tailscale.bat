@echo off
chcp 65001 >nul
rem Instala Tailscale y deja entrar a Luna SOLO desde Tailscale y desde la Wi-Fi de casa.
net session >nul 2>&1
if errorlevel 1 (
  echo  Windows va a pedir permiso de administrador: toca "Si".
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
title Luna desde la calle (Tailscale)
echo.
echo  === Luna desde cualquier lugar ===
echo.
set "TS=%ProgramFiles%\Tailscale\tailscale.exe"
if not exist "%TS%" (
  echo  Instalando Tailscale ^(gratis^)...
  winget install -e --id Tailscale.Tailscale --silent --accept-package-agreements --accept-source-agreements
)
if not exist "%TS%" (
  echo  No pude instalar Tailscale. Descargalo de https://tailscale.com/download/windows
  pause
  exit /b 1
)
echo  Abriendo la puerta de Luna solo para Tailscale y tu Wi-Fi de casa...
netsh advfirewall firewall delete rule name="Luna - Tailscale y Wi-Fi de casa" >nul 2>&1
netsh advfirewall firewall add rule name="Luna - Tailscale y Wi-Fi de casa" dir=in action=allow protocol=TCP localport=8443 remoteip=100.64.0.0/10,LocalSubnet >nul
if errorlevel 1 (
  echo  No pude crear la regla del firewall.
) else (
  echo  Listo: el puerto de Luna queda abierto solo para Tailscale y tu red local.
)
start "" "%ProgramFiles%\Tailscale\tailscale-ipn.exe"
echo.
echo  Ahora inicia sesion en Tailscale: se abre el navegador ^(usa tu cuenta de Google^).
"%TS%" login
echo.
"%TS%" status
echo.
echo  ==============================================================
echo   Ultimos pasos:
echo   1. En el celular instala la app Tailscale e inicia sesion con
echo      la MISMA cuenta.
echo   2. Abre iniciar.bat: la ventana negra mostrara la linea
echo      "Desde la calle (Tailscale)" con el link para el celular.
echo   3. Si aun no tienes PIN, abre cambiar_pin.bat: sin PIN, Luna
echo      no responde desde fuera de casa.
echo  ==============================================================
echo.
pause
