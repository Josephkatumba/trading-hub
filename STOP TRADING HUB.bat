@echo off
title Trading Hub Shutdown

echo ==========================================
echo       STOPPING TRADING HUB...
echo ==========================================
echo.

echo [1/2] Stopping Market Engine...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do taskkill /PID %%a /T /F >nul 2>&1

echo [2/2] Stopping Dashboard...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":5173" ^| findstr "LISTENING"') do taskkill /PID %%a /T /F >nul 2>&1

echo.
echo ==========================================
echo       TRADING HUB HAS BEEN STOPPED
echo ==========================================
echo.
pause
