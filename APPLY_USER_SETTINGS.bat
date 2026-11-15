@echo off
REM One click: new usernames + Scrap MIS plants per user + restart VERONICA. Asks Windows for admin once (click Yes).
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
if not exist logs mkdir logs
echo.
echo  ===== 1/3  New login usernames =====
.venv\Scripts\python.exe -m tools.rename_usernames > logs\rename_usernames.log 2>&1
type logs\rename_usernames.log
echo.
echo  ===== 2/3  Scrap MIS plants per user =====
.venv\Scripts\python.exe -m tools.set_scrap_plants > logs\set_scrap_plants.log 2>&1
type logs\set_scrap_plants.log
echo.
echo  ===== 3/3  Restarting VERONICA =====
set "TN=ReportBot"
schtasks /Query /TN VeronicaAI >nul 2>&1 && set "TN=VeronicaAI"
schtasks /End /TN %TN%
timeout /t 4 /nobreak >nul
schtasks /Run /TN %TN%
echo Restarting - wait 25 seconds...
timeout /t 25 /nobreak >nul
powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 8).Content } catch { 'not answering yet - wait a little and refresh' }"
echo.
echo  DONE. Everyone: press Ctrl+F5 and sign in again.
timeout /t 120
