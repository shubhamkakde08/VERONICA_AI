@echo off
REM Removes all Telegram-related chats (questions + VERONICA's replies), reports, schedules and log entries
REM from VERONICA's own database. First shows the counts, then asks before deleting. Cannot be undone.
cd /d "%~dp0"
echo.
echo === What will be removed (nothing changed yet) ===
.venv\Scripts\python -m tools.purge_telegram
echo.
set /p ok=Type YES to remove these for good:
if /I not "%ok%"=="YES" (echo Cancelled - nothing removed. & pause & exit /b)
.venv\Scripts\python -m tools.purge_telegram --apply
echo.
pause
