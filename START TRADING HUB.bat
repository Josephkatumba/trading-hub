@echo off
cd /d "%~dp0"
pushd backend
python -m ops.control start
popd
timeout /t 5 /nobreak >nul
netstat -ano | findstr /R /C:":5173 .*LISTENING" >nul
if errorlevel 1 start "Trading Hub - Dashboard" cmd /k "npm.cmd run dev"
timeout /t 8 /nobreak >nul
start "" "http://localhost:5173/trading-hub/"
