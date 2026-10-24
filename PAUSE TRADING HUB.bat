@echo off
cd /d "%~dp0backend"
python -m ops.control pause
echo Tradeden paused. Use START TRADING HUB to resume.
pause
