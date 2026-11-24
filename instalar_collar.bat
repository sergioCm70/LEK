@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalar collar
if not exist venv (
  echo  Primero abre instalar.bat
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
echo  Instalando el oido del collar (Whisper)...
pip install -r requisitos-collar.txt
echo  Listo.
pause
