@echo off
chcp 65001 >nul
rem Hace que Luna arranque sola cada vez que prendes el PC.
set "DESTINO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Luna.bat"
> "%DESTINO%" echo @echo off
>> "%DESTINO%" echo rem Arranca a Luna al prender el PC. Para quitarlo, borra este archivo.
>> "%DESTINO%" echo start "Luna" /min cmd /c "%~dp0iniciar.bat"
echo.
echo  Listo: Luna arrancara sola cada vez que prendas el PC.
echo  Para quitarlo, borra: %DESTINO%
echo.
pause
