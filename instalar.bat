@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar asistente
echo.
echo  === Instalando tu asistente ===
echo.

rem ---------- Python
call :buscar_python
if not defined PY (
  echo  Instalando Python ^(con winget^)...
  winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
  call :buscar_python
)
if not defined PY (
  echo.
  echo  No pude instalar Python solo. Instalalo desde https://www.python.org/downloads/
  echo  marcando "Add python.exe to PATH", y vuelve a abrir este archivo.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
echo  Python: %PY%

if exist venv if not exist venv\Scripts\activate.bat rmdir /s /q venv
if not exist venv (
  echo  Creando entorno de Python...
  "%PY%" -m venv venv
)
if not exist venv\Scripts\activate.bat (
  echo  No se pudo crear el entorno de Python.
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

rem ---------- Ollama
call :buscar_ollama
if not defined OLLAMA (
  echo.
  echo  Instalando Ollama, el cerebro gratis ^(con winget^)...
  winget install -e --id Ollama.Ollama --silent --accept-package-agreements --accept-source-agreements
  call :buscar_ollama
)
if not defined OLLAMA (
  echo  No pude instalar Ollama solo. Descargalo de https://ollama.com/download
  echo  Instalalo y vuelve a abrir este archivo.
  start https://ollama.com/download
  pause
  exit /b 1
)
"%OLLAMA%" list >nul 2>nul
if errorlevel 1 (
  echo  Encendiendo Ollama...
  start "" /min "%OLLAMA%" serve
  timeout /t 8 /nobreak >nul
)
set MODELO=
for /f "tokens=2 delims==" %%m in ('findstr /b "ASISTENTE_MODELO=" .env') do set MODELO=%%m
if "%MODELO%"=="" set MODELO=qwen3:8b
echo.
echo  Descargando el cerebro %MODELO% (son varios GB, puede tardar un buen rato)...
"%OLLAMA%" pull %MODELO%
if errorlevel 1 (
  echo  No se pudo descargar el modelo. Revisa tu internet y vuelve a abrir este archivo.
  pause
  exit /b 1
)
echo.
echo  ==============================================
echo   LISTO. Ahora abre iniciar.bat
echo   (Para el collar: instalar_collar.bat)
echo  ==============================================
echo.
pause
exit /b 0

:buscar_python
set PY=
for %%v in (313 312 311) do (
  if not defined PY if exist "%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python%%v\python.exe"
)
if not defined PY (
  for /f "delims=" %%p in ('python -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
)
if not defined PY (
  for /f "delims=" %%p in ('py -3 -c "import sys;print(sys.executable)" 2^>nul') do set "PY=%%p"
)
exit /b 0

:buscar_ollama
set OLLAMA=
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not defined OLLAMA (
  for /f "delims=" %%p in ('where ollama 2^>nul') do if not defined OLLAMA set "OLLAMA=%%p"
)
exit /b 0
