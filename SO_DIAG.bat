@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
.venv\Scripts\python.exe -m tools.so_diag > logs\so_diag.txt 2>&1
type logs\so_diag.txt
timeout /t 60
