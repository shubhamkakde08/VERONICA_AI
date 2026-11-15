@echo off
cd /d "%~dp0"
.venv\Scripts\python -m tools.mail_test you@yourcompany.com
timeout /t 10
