@echo off
cd /d "%~dp0"
start "Trading Hub - Market Engine" cmd /k "cd /d "%~dp0" && call backend\start_engine.bat"
timeout /t 5 /nobreak >nul
start "Trading Hub - Dashboard" cmd /k "cd /d "%~dp0" && npm.cmd run dev"
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173/trading-hub/"
