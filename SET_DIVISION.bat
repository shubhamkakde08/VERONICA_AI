@echo off
cd /d "%~dp0"
echo.
echo  ===== VERONICA - who sees which division =====
.venv\Scripts\python.exe -m tools.set_division
echo.
echo It works from that users next message. Run this again for the next user.
pause
