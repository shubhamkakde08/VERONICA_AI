@echo off
cd /d "%~dp0"
.venv\Scripts\python -m tools.smtp_diag
timeout /t 8
