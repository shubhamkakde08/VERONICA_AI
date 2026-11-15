@echo off
REM Restart VERONICA AI after changing .env or updating files.
REM Uses the auto-start task if installed (run as Administrator), otherwise opens start.bat in a new window.
cd /d "%~dp0\..\.."
for /f "tokens=5" %%p in ('netstat -ano ^| findstr ":8000 " ^| findstr LISTENING') do taskkill /F /PID %%p >nul 2>&1
set "TN=ReportBot"
schtasks /Query /TN VeronicaAI >nul 2>&1 && set "TN=VeronicaAI"
schtasks /Query /TN %TN% >nul 2>&1
if errorlevel 1 goto notask

schtasks /End /TN %TN% >nul 2>&1
schtasks /Run /TN %TN% >nul
echo VERONICA AI restarted - auto-start task.
goto check

:notask
start "VERONICA AI" cmd /k "%~dp0start.bat"
echo Auto-start task not installed - started VERONICA AI in a new window. Keep that window open.
echo To start automatically with Windows, run install-autostart.ps1 as Administrator.

:check
timeout /t 6 /nobreak >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 8).Content } catch { 'Not answering yet - check logs\server.log' }"
