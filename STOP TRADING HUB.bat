@echo off
cd /d "%~dp0backend"
python -m ops.control stop
echo Tradeden is stopping. MT5 is left under your control.
pause
