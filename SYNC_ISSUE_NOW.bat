@echo off
REM Double-click: copies VIEW_ISSUE_ENGINE_PBI from Oracle into the MySQL replica now (needs the Oracle network / VPN).
set TNS_ADMIN=C:\data\wallet
cd /d C:\OracleMySQLSync
echo Syncing VIEW_ISSUE_ENGINE_PBI from Oracle - please wait...
echo ================ manual %date% %time% ================ >> logs\sync_manual.log
C:\Python314\python.exe C:\OracleMySQLSync\oracle_mysql_sync.py VIEW_ISSUE_ENGINE_PBI >> logs\sync_manual.log 2>&1
findstr /c:"SYNC COMPLETE" /c:"FATAL" /c:"ERROR syncing" /c:"attempt" logs\sync_manual.log
echo.
echo Done. VERONICA picks the view up by itself - no restart needed.
timeout /t 60
