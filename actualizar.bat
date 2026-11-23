@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo  Bajando la ultima version desde GitHub...
git pull
if errorlevel 1 (
  echo  No se pudo actualizar. Necesitas Git: https://git-scm.com/download/win
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
pip install -r requisitos.txt >nul
echo  Actualizado. Tus datos, notas y memoria siguen intactos.
pause
