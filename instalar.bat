@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar asistente
echo.
echo  === Instalando tu asistente ===
echo.
set PY=
python -c "import sys" >nul 2>nul && set PY=python
if not defined PY py -3 -c "import sys" >nul 2>nul && set PY=py -3
if not defined PY (
  echo  No encuentro Python instalado.
  echo  1. Descargalo de https://www.python.org/downloads/
  echo  2. En la PRIMERA pantalla del instalador marca "Add python.exe to PATH"
  echo  3. Cierra esta ventana y vuelve a abrir instalar.bat
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if exist venv if not exist venv\Scripts\activate.bat rmdir /s /q venv
if not exist venv (
  echo  Creando entorno de Python...
  %PY% -m venv venv
)
if not exist venv\Scripts\activate.bat (
  echo  No se pudo crear el entorno de Python. Reinstala Python desde python.org.
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
python -m pip install --upgrade pip >nul
echo  Instalando librerias...
pip install -r requisitos.txt
if errorlevel 1 (
  echo  Algo fallo instalando las librerias. Revisa tu internet y vuelve a intentar.
  pause
  exit /b 1
)
if not exist .env copy .env.ejemplo .env >nul
echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo  Falta Ollama, el cerebro gratis. Descargalo de https://ollama.com/download
  echo  Instalalo y vuelve a abrir este archivo.
  pause
  exit /b 1
)
for /f "tokens=2 delims==" %%m in ('findstr /b "ASISTENTE_MODELO=" .env') do set MODELO=%%m
if "%MODELO%"=="" set MODELO=qwen3:8b
echo  Descargando el cerebro %MODELO% (puede tardar, son varios GB)...
ollama pull %MODELO%
echo.
set /p COLLAR= Vas a usar el collar de IA? (s/n): 
if /i "%COLLAR%"=="s" pip install -r requisitos-collar.txt
echo.
echo  Listo. Abre el archivo .env con el Bloc de notas para ponerle un PIN,
echo  y luego abre iniciar.bat
echo.
pause
