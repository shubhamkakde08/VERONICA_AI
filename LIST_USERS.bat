@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
.venv\Scripts\python.exe -m tools.list_users > logs\users_list.txt 2>&1
type logs\users_list.txt
echo.
timeout /t 60
