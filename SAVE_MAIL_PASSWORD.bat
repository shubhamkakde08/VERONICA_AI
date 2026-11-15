@echo off
REM 1) Copy the company mail password  2) double-click this file  3) click Yes
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File %~dp0tools\save_mail_password.ps1'"
