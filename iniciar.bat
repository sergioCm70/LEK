@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Asistente
if not exist venv (
  echo  Primero abre instalar.bat
  pause
  exit /b 1
)
call venv\Scripts\activate.bat
python servidor.py
pause
