@echo off
REM No admin needed: new public link (and WhatsApp if WHATSAPP_APP_ID is set) pointed at it. Keep the tunnel window open.
cd /d "%~dp0"
echo %date% %time% new link > logs\wake.txt
if exist logs\tunnel_now.log del logs\tunnel_now.log >nul 2>&1
start "VERONICA tunnel - keep open" cmd /k "cloudflared.exe.exe tunnel --url http://localhost:8000 --logfile logs\tunnel_now.log"
echo Waiting for the new public link...
.venv\Scripts\python -m tools.wake_link logs\tunnel_now.log >> logs\wake.txt 2>&1
echo done >> logs\wake.txt
type logs\wake.txt
timeout /t 20
