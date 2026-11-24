@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cambiar el PIN de Luna
echo.
echo  El PIN protege a Luna: sin el, nadie mas en tu Wi-Fi puede usarla.
echo.
set "NUEVO="
set /p NUEVO= Escribe el PIN nuevo y presiona Enter: 
if "%NUEVO%"=="" (
  echo  No escribiste nada. No cambie el PIN.
  pause
  exit /b 1
)
powershell -NoProfile -Command "$f='.env'; $c = @(); if (Test-Path $f) { $c = @(Get-Content $f) }; if ($c -match '^ASISTENTE_PIN=') { $c = $c -replace '^ASISTENTE_PIN=.*', ('ASISTENTE_PIN=' + $env:NUEVO) } else { $c += ('ASISTENTE_PIN=' + $env:NUEVO) }; Set-Content -Path $f -Value $c -Encoding UTF8"
echo.
echo  Listo. Ahora abre iniciar.bat para que Luna use el PIN nuevo.
echo  La primera vez, la ventana de Luna y el celular te lo pediran una sola vez.
echo.
pause
