@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Restaurar a Luna
echo.
echo  Restaurar un respaldo de Luna
echo  =============================
echo  Antes de restaurar, Luna guarda una copia de lo que tiene ahora.
echo.
if not exist venv (
  echo  Primero abre instalar.bat
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
python -m lek.respaldo listar
echo.
set /p N= Numero del respaldo a restaurar (Enter para cancelar): 
if "%N%"=="" exit /b 0
echo.
echo  Cerrando a Luna...
powershell -NoProfile -Command "try { Invoke-WebRequest -UseBasicParsing -Method Post http://127.0.0.1:8090/api/apagar -TimeoutSec 5 | Out-Null } catch {}"
timeout /t 4 /nobreak >nul
python -m lek.respaldo restaurar %N%
echo.
echo  Abre iniciar.bat para volver a encender a Luna.
pause
