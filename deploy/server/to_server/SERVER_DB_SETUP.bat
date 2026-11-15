@echo off
REM SERVER: creates VERONICA's MySQL databases + logins and loads the dumps in this folder.
REM You type the MySQL root password (hidden). Nothing is shown or saved.
cd /d "%~dp0"
C:\VeronicaAI\.venv\Scripts\python.exe "%~dp0server_db_setup.py"
pause
