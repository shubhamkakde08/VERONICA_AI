@echo off
REM Starts ReportBot / VERONICA on http://localhost:8000 (no Docker)
cd /d "%~dp0\..\.."
if not exist logs mkdir logs
if exist .env (for /f "usebackq tokens=1,* delims==" %%a in (`findstr /b "WEASYPRINT_DLL_DIRECTORIES=" .env`) do set WEASYPRINT_DLL_DIRECTORIES=%%b)
echo %date% %time% starting >> logs\server.log
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=127.0.0.1 >> logs\server.log 2>&1
