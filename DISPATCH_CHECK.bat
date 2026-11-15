@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
.venv\Scripts\python.exe -m tools.dispatch_check > logs\dispatch_check.txt 2>&1
type logs\dispatch_check.txt
echo.
timeout /t 60
