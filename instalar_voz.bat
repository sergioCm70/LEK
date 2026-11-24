@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar voz de Luna
echo.
echo  === Oido de Luna: escuchar su nombre sin abrir nada ===
echo.
if not exist venv\Scripts\activate.bat (
  echo  Primero abre instalar.bat
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
echo  Instalando vosk y sounddevice...
python -m pip install -r requisitos-voz.txt
if errorlevel 1 (
  echo.
  echo  No se pudieron instalar las librerias. Revisa el internet y vuelve a abrir este archivo.
  echo  Si el error menciona cffi o compilar, tu version de Python puede ser muy nueva:
  echo  prueba con Python 3.12 o 3.13.
  pause
  exit /b 1
)

set "MODELO=vosk-model-small-es-0.42"
set "URL=https://alphacephei.com/vosk/models/%MODELO%.zip"
if not exist datos\modelos mkdir datos\modelos
if exist "datos\modelos\%MODELO%\am" goto modelo_listo

echo  Descargando el modelo de voz en espanol, puede tardar unos minutos...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri '%URL%' -OutFile 'datos\modelos\%MODELO%.zip'"
if errorlevel 1 goto modelo_manual
echo  Descomprimiendo...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -Force -Path 'datos\modelos\%MODELO%.zip' -DestinationPath 'datos\modelos'"
if errorlevel 1 goto modelo_manual
del "datos\modelos\%MODELO%.zip" >nul 2>&1
if not exist "datos\modelos\%MODELO%\am" goto modelo_manual

:modelo_listo
echo  Modelo de voz listo: datos\modelos\%MODELO%
echo.
python -c "from lek.voz.despertador import diagnosticar; d = diagnosticar(); print('  Todo listo.' if d['listo'] else '  Falta: ' + ' '.join(d['faltan']))"
echo.
echo  Para activarlo pon ASISTENTE_DESPERTADOR=si en el archivo .env y abre iniciar.bat
echo  Para probar solo el oido: venv\Scripts\python -m lek.voz.despertador
pause
exit /b 0

:modelo_manual
echo.
echo  No pude descargar el modelo solo. Hazlo a mano:
echo    1. Abre https://alphacephei.com/vosk/models
echo    2. Descarga %MODELO%.zip
echo    3. Descomprimelo dentro de la carpeta datos\modelos de Luna
echo       debe quedar datos\modelos\%MODELO%\am
start https://alphacephei.com/vosk/models
pause
exit /b 1
