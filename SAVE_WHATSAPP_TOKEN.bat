@echo off
REM 1) In Meta API Setup click the copy icon next to Access token  2) double-click this file  3) click Yes
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File %~dp0tools\save_wa_token.ps1'"
