@echo off
REM Double-click: asks Windows for admin (click Yes), then restarts VERONICA and waits until she answers (up to 2 minutes).
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
set "TN=ReportBot"
schtasks /Query /TN VeronicaAI >nul 2>&1 && set "TN=VeronicaAI"
schtasks /End /TN %TN%
timeout /t 4 /nobreak >nul
.venv\Scripts\python -m tools.clean_logs >nul 2>&1
schtasks /Run /TN %TN%
echo Restarting VERONICA - she loads the sales order book first, this takes 30-90 seconds...
set /a n=0
:wait
timeout /t 10 /nobreak >nul
set /a n+=1
powershell -NoProfile -Command "try { $r=(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 15).Content; Write-Host ('VERONICA is UP: ' + $r); exit 0 } catch { exit 1 }"
if not errorlevel 1 goto up
echo   still starting... (%n%0 s)
if %n% lss 12 goto wait
echo.
echo VERONICA did not answer in 2 minutes. Send logs\server.log to Claude.
pause
exit /b
:up
echo.
echo Done. Open http://127.0.0.1:8000 and press Ctrl+F5.
timeout /t 15
