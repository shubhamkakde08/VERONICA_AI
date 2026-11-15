@echo off
cd /d "%~dp0"
.venv\Scripts\python -m tools.wa_check
timeout /t 10
