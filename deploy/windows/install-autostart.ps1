# Runs VERONICA AI automatically when Windows starts (even before anyone logs in) and restarts it if it stops.
# Run PowerShell AS ADMINISTRATOR:  powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\install-autostart.ps1
param([string]$TaskName = "VeronicaAI")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$action   = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$Root\deploy\windows\start.bat`"" -WorkingDirectory $Root
$trigger  = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
            -ExecutionTimeLimit (New-TimeSpan -Days 0) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 8
try { $r = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 10; Write-Host "VERONICA AI is running: $($r.Content)" -ForegroundColor Green }
catch { Write-Host "Started, but /health did not answer yet. Check $Root\logs\server.log" -ForegroundColor Yellow }
Write-Host "Manage it: Task Scheduler -> '$TaskName'.  Stop: Stop-ScheduledTask $TaskName   Start: Start-ScheduledTask $TaskName"
