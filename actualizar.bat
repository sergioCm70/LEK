@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Actualizar a Luna
echo.
echo  Bajando la ultima version de Luna desde GitHub...
where git >nul 2>nul
if errorlevel 1 (
  echo  Instalando Git ^(con winget^)...
  winget install -e --id Git.Git --silent --accept-package-agreements --accept-source-agreements
  set "PATH=%PATH%;%ProgramFiles%\Git\cmd"
)
where git >nul 2>nul
if errorlevel 1 (
  echo  No pude instalar Git. Descargalo de https://git-scm.com/download/win y vuelve a abrir este archivo.
  pause
  exit /b 1
)
if not exist .git (
  echo  Conectando esta carpeta con GitHub ^(una sola vez^)...
  git init -q
  git remote add origin https://github.com/sergioCm70/LEK.git
)
git fetch -q origin main
if errorlevel 1 (
  echo  No pude conectarme con GitHub. Revisa tu internet.
  pause
  exit /b 1
)
git reset -q --mixed origin/main
git checkout -q -- .
git branch -q -M main 2>nul
git branch -q --set-upstream-to=origin/main main 2>nul
call venv\Scripts\activate.bat
pip install -q -r requisitos.txt
echo.
echo  Listo: Luna esta al dia. Tus datos, tu memoria y tus conversaciones no se tocan.
echo  Abre iniciar.bat para usar la version nueva.
echo.
pause
