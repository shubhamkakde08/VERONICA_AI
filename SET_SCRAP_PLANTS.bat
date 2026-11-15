@echo off
cd /d "%~dp0"
if not exist logs mkdir logs
echo.
echo  ===== VERONICA - Scrap MIS plants per user =====
.venv\Scripts\python.exe -m tools.set_scrap_plants > logs\set_scrap_plants.log 2>&1
type logs\set_scrap_plants.log
echo.
timeout /t 60
