@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
.venv\Scripts\python.exe -m tools.issue_setup > logs\issue_setup.txt 2>&1
type logs\issue_setup.txt
echo.
timeout /t 60
