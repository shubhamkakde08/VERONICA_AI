@echo off
REM LAPTOP: dumps VERONICA's database + ERP replica into deploy\server\db_export for the new server.
cd /d "%~dp0"
.venv\Scripts\python.exe -m tools.export_db
pause
