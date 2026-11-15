@echo off
REM One-time: renames C:\reportbot -> C:\VeronicaAI and the auto-start task to VeronicaAI. Asks for admin (click Yes).
net session >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)
copy /y "%~dp0tools\move_to_veronicaai.ps1" "%TEMP%\move_to_veronicaai.ps1" >nul
cd /d C:\
start "VERONICA AI move" powershell -NoProfile -ExecutionPolicy Bypass -File "%TEMP%\move_to_veronicaai.ps1"
exit
