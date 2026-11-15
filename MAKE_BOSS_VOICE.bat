@echo off
cd /d "%~dp0"
echo.
echo  ===== Record VERONICA's "Hello Boss" greetings (once) =====
echo  Records in her Gemini voice (the one you like). Needs 4 of the 10 daily Gemini clips - run it in the morning.
echo.
.venv\Scripts\python.exe -m tools.manage boss-voice gemini
echo.
echo Done. Sign in as admin again (Ctrl+F5) to hear her.
pause
