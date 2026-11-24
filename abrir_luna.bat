@echo off
rem Abre la ventana de Luna escuchando. Si Luna no esta encendida, la enciende primero.
cd /d "%~dp0"
curl -s -o nul http://localhost:8090/ >nul 2>nul
if errorlevel 1 (
  start "Luna" /min cmd /c "%~dp0iniciar.bat"
  timeout /t 25 /nobreak >nul
  exit /b 0
)
set "EDGE=%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"
if not exist "%EDGE%" set "EDGE=%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"
if exist "%EDGE%" (
  start "" "%EDGE%" --app=http://localhost:8090/?manos=1 --user-data-dir="%~dp0datos\navegador" --autoplay-policy=no-user-gesture-required --window-size=460,820 --no-first-run --no-default-browser-check
) else (
  start "" http://localhost:8090/?manos=1
)
