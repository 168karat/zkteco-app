@echo off
set "APP_DIR=%~dp0"
set "STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "VBS_PATH=%STARTUP_DIR%\ZKTeco_Background_Server.vbs"

echo Set WshShell = CreateObject("WScript.Shell") > "%VBS_PATH%"
echo WshShell.Run Chr(34) ^& "%APP_DIR%run.bat" ^& Chr(34), 0 >> "%VBS_PATH%"
echo Set WshShell = Nothing >> "%VBS_PATH%"

echo ===================================================
echo   ZKTeco ADMS Server - Auto Startup Setup
echo ===================================================
echo.
echo SUCCESS: Auto-startup script installed!
echo Location: %VBS_PATH%
echo.
pause
