@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo.
echo  ===== VERONICA - change login usernames =====
.venv\Scripts\python.exe -m tools.rename_usernames > logs\rename_usernames.log 2>&1
type logs\rename_usernames.log
echo.
timeout /t 60
