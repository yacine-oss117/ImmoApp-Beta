@echo off
setlocal
cd /d "%~dp0"
title Stop ImmoApp Beta

echo Stopping the local ImmoApp Beta backend...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stack.ps1" -Action down -UseWindowsVolumes
set "IMMOAPP_EXIT=%ERRORLEVEL%"

if not "%IMMOAPP_EXIT%"=="0" (
    echo.
    echo The backend could not be stopped cleanly.
    echo Review the error above.
    echo.
    pause
    exit /b %IMMOAPP_EXIT%
)

echo.
echo ImmoApp Beta backend stopped. Local data was kept.
timeout /t 2 /nobreak >nul
exit /b 0
