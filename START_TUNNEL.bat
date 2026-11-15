@echo off
REM Starts the public link (free Cloudflare tunnel). Keep this window open.
cd /d "%~dp0"
if exist logs\tunnel.log move /y logs\tunnel.log logs\tunnel_old.log >nul
start "VERONICA tunnel - keep open" cmd /k "cloudflared.exe.exe tunnel --url http://localhost:8000 --logfile logs\tunnel.log"
