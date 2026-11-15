# Renames the project folder C:\reportbot -> C:\VeronicaAI and the auto-start task ReportBot -> VeronicaAI.
# Started by MOVE_TO_VERONICAAI.bat (runs from %TEMP% so nothing inside the folder is open while it moves).
# Safe: if the folder cannot be moved, VERONICA is started again exactly as before. Old path keeps working (junction).
param([string]$Old = "C:\reportbot", [string]$New = "C:\VeronicaAI")
$ErrorActionPreference = "Stop"
function Health { try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 15).Content } catch { $null } }
Set-Location C:\
Write-Host "== VERONICA AI: moving $Old -> $New" -ForegroundColor Cyan
if (Test-Path $New) { Write-Host "$New already exists - nothing done." -ForegroundColor Yellow; Read-Host "Press Enter"; exit 1 }
if ((Get-Item $Old).Attributes -band [IO.FileAttributes]::ReparsePoint) { Write-Host "$Old is already a link - already moved." -ForegroundColor Yellow; Read-Host "Press Enter"; exit 1 }

Write-Host "Stopping VERONICA..."
cmd /c "schtasks /End /TN ReportBot >nul 2>&1"
Start-Sleep -Seconds 5
Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
# python / tunnel started from this folder may still hold files open
Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -like "$Old\*" -or $_.CommandLine -like "*$Old*" } |
  ForEach-Object { Write-Host "  closing $($_.Name) ($($_.ProcessId))"; Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3

$moved = $false
for ($i = 1; $i -le 6 -and -not $moved; $i++) {
  try { Rename-Item -Path $Old -NewName (Split-Path $New -Leaf); $moved = $true }
  catch { Write-Host "  folder busy (try $i/6) - close any Explorer / Excel / editor window open in it"; Start-Sleep -Seconds 5 }
}
if (-not $moved) {
  Write-Host "Could not move the folder (a file is open). Starting VERONICA again as before." -ForegroundColor Red
  cmd /c "schtasks /Run /TN ReportBot >nul 2>&1"
  Read-Host "Press Enter"; exit 1
}
Write-Host "Folder renamed." -ForegroundColor Green
cmd /c mklink /J "$Old" "$New" | Out-Null          # old path keeps working for shortcuts, tunnel, sync scripts
Write-Host "Old path $Old now points to $New."

Write-Host "Creating auto-start task VeronicaAI..."
& "$New\deploy\windows\install-autostart.ps1" -TaskName VeronicaAI
cmd /c "schtasks /Delete /TN ReportBot /F >nul 2>&1"

Write-Host "Waiting for VERONICA (up to 2 minutes)..."
for ($i = 0; $i -lt 12; $i++) { $h = Health; if ($h) { break }; Start-Sleep -Seconds 10; Write-Host "  still starting..." }
if (Test-Path "$New\START_TUNNEL.bat") { Write-Host "Restarting the public link (new link address)..."; Start-Process -FilePath "$New\START_TUNNEL.bat" -WorkingDirectory $New }
if ($h) { Write-Host "VERONICA AI is UP from $New : $h" -ForegroundColor Green }
else { Write-Host "Not answering yet - send $New\logs\server.log to Claude." -ForegroundColor Yellow }
Read-Host "Done. Press Enter"
