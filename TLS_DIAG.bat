@echo off
cd /d "%~dp0"
.venv\Scripts\python.exe tools\tls_diag.py
type logs\tls_diag.txt
timeout /t 5
