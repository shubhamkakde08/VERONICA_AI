@echo off
REM VERONICA AI - first install on a NEW server. Double-click. Windows asks for admin: click Yes.
REM Keys and passwords are NOT in this package. Copy your .env file in yourself when asked.
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
title VERONICA AI - server install
echo ============================================================
echo   VERONICA AI - server install in %CD%
echo ============================================================
echo.

REM ---- 1. Python 3.12
set "PYOK="
py -3.12 --version >nul 2>&1 && set "PYOK=1"
if not defined PYOK python --version 2>nul | findstr /R "3\.1[1-9]" >nul && set "PYOK=1"
if not defined PYOK (
  echo [1/6] Python 3.12 not found - installing with winget...
  winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
  if errorlevel 1 (
    echo.
    echo winget could not install Python. Install Python 3.12 from https://www.python.org/downloads/windows/
    echo tick "Add python.exe to PATH", then double-click this file again.
    pause & exit /b
  )
  echo Python installed. Close this window and double-click INSTALL_ON_SERVER.bat again ^(PATH refresh^).
  pause & exit /b
) else echo [1/6] Python OK

REM ---- 2. Settings file (.env) - you copy it in
if not exist ".env" (
  echo.
  echo [2/6] .env not found.
  echo       Copy .env from the old PC  ^(C:\reportbot\.env^)  into  %CD%
  echo       - by pen drive, NOT by e-mail / WhatsApp / chat.
  echo       Then press any key.
  pause >nul
  if not exist ".env" ( echo Still no .env - stopping. & pause & exit /b )
)
echo [2/6] .env found

REM ---- 3. Packages
echo [3/6] Installing packages ^(5-10 min first time^)...
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\install.ps1
if errorlevel 1 ( echo Install step failed - send logs\install.log screenshot to Claude. & pause & exit /b )

REM ---- 4. Database reachable?
echo [4/6] Checking the database in .env ...
.venv\Scripts\python -c "from app import datadb,store; datadb.engine.connect().close(); print('  ERP data DB: OK')" 2>nul || (
  echo   ERP data DB NOT reachable. Open .env and point DATA_DB_URL / BOT_DB_URL host to the MySQL server
  echo   ^(old PC IP, or install MySQL + Oracle sync on this server^). Then run this file again.
  pause & exit /b )

REM ---- 5. Start at boot
echo [5/6] Setting VERONICA to start at boot...
powershell -NoProfile -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1

REM ---- 6. Office network access (optional)
echo.
set /p FW="[6/6] Allow other office PCs to open VERONICA on port 8000 (LAN only)? Y/N: "
if /I "%FW%"=="Y" netsh advfirewall firewall add rule name="VERONICA AI 8000 (LAN)" dir=in action=allow protocol=TCP localport=8000 remoteip=localsubnet
echo.
echo Waiting for VERONICA to answer...
set /a n=0
:wait
timeout /t 10 /nobreak >nul
set /a n+=1
powershell -NoProfile -Command "try { $r=(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 15).Content; Write-Host ('VERONICA is UP: ' + $r); exit 0 } catch { exit 1 }"
if not errorlevel 1 goto up
if %n% lss 12 goto wait
echo VERONICA did not answer in 2 minutes. Send logs\server.log to Claude.
pause & exit /b
:up
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /C:"IPv4"') do set IP=%%a
echo.
echo ============================================================
echo  DONE.  On this server:   http://127.0.0.1:8000
echo         From office PCs:  http://%IP: =%:8000
echo ============================================================
pause
