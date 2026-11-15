@echo off
cd /d "%~dp0"
.venv\Scripts\python -m tools.manage set-webhook > logs\set_webhook.txt 2>&1
call deploy\windows\restart.bat > logs\restart.txt 2>&1
