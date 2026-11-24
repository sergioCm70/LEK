@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Pruebas de Luna
call venv\Scripts\activate.bat
pip install -q -r requisitos-dev.txt
python -m pytest -q tests
pause
