@echo off
REM Run as administrator: saves your WhatsApp number and restarts VERONICA so new .env settings load.
cd /d "%~dp0"
REM Set your WhatsApp number (country code, no +), then remove REM:
REM .venv\Scripts\python -m tools.manage set-contact 1 91XXXXXXXXXX
set "TN=ReportBot"
schtasks /Query /TN VeronicaAI >nul 2>&1 && set "TN=VeronicaAI"
schtasks /End /TN %TN%
timeout /t 4 /nobreak >nul
schtasks /Run /TN %TN%
timeout /t 15 /nobreak >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 8).Content } catch { 'not answering yet' }"
pause
