@echo off
setlocal
cd /d "%~dp0"
title ImmoApp Beta

echo Starting ImmoApp Beta...
echo.

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0quickstart.ps1" -DetachClient
set "IMMOAPP_EXIT=%ERRORLEVEL%"

if not "%IMMOAPP_EXIT%"=="0" (
    echo.
    echo ImmoApp Beta could not start.
    echo Review the error above. Detailed startup logs are stored under:
    echo C:\ProgramData\ImmoApp\logs
    echo.
    pause
    exit /b %IMMOAPP_EXIT%
)

cls
title ImmoApp Beta - Demo login: owner / admin
echo ==============================================================
echo                       ImmoApp Beta
echo ==============================================================
echo.
echo ImmoApp Beta is running.
echo.
echo BETA TEST LOGIN
echo   Username: owner
echo   Password: admin
echo.
echo Keep this window open as your login reminder while evaluating.
echo Closing this reminder window will NOT stop ImmoApp or delete data.
echo To stop the local backend later, double-click "Stop ImmoApp Beta.cmd".
echo.
echo ==============================================================
echo.

choice /C Q /N /M "Press Q only if you want to close this reminder window: "
exit /b 0
