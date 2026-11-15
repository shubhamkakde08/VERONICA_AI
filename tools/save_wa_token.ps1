# Saves the WhatsApp access token that is on the clipboard into .env (nobody else sees it), then restarts VERONICA.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$tok = (Get-Clipboard -Raw).Trim()
if ($tok -notmatch '^EAA[A-Za-z0-9]{40,}$') {
  Write-Host "The clipboard does not hold a WhatsApp token." -ForegroundColor Red
  Write-Host "In Meta -> API Setup click the copy icon next to 'Access token', then run this again."
  Read-Host "Press Enter to close"; exit 1 }
$lines = Get-Content .env
if ($lines -match '^WHATSAPP_TOKEN=') { $lines = $lines -replace '^WHATSAPP_TOKEN=.*', "WHATSAPP_TOKEN=$tok" } else { $lines += "WHATSAPP_TOKEN=$tok" }
[IO.File]::WriteAllLines((Join-Path (Get-Location) ".env"), [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
Set-Clipboard -Value " "
Write-Host "Token saved in .env (clipboard cleared)." -ForegroundColor Green
& .\.venv\Scripts\python -m tools.manage set-contact 1 91XXXXXXXXXX
schtasks /End /TN ReportBot | Out-Null; Start-Sleep 4; schtasks /Run /TN ReportBot | Out-Null
Write-Host "Restarting VERONICA ..."; Start-Sleep 18
try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 8).Content } catch { "not answering yet - wait 30 s" }
Write-Host "Done. Now reply 'hi' on WhatsApp to +1 555 151 4176." -ForegroundColor Green
Read-Host "Press Enter to close"
