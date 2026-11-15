# Saves the company mail password that is on the clipboard into .env (spaces removed), then restarts VERONICA.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$pw = (Get-Clipboard -Raw).Trim()
if ($pw.Length -lt 4 -or $pw -match '\s') {
  Write-Host "The clipboard does not hold a mail password." -ForegroundColor Red
  Write-Host "Copy the company mail password (Ctrl+C), then run this again."
  Read-Host "Press Enter to close"; exit 1 }
$lines = Get-Content .env
if ($lines -match '^SMTP_PASSWORD=') { $lines = $lines -replace '^SMTP_PASSWORD=.*', "SMTP_PASSWORD=$pw" } else { $lines += "SMTP_PASSWORD=$pw" }
[IO.File]::WriteAllLines((Join-Path (Get-Location) ".env"), [string[]]$lines, (New-Object System.Text.UTF8Encoding($false)))
Set-Clipboard -Value " "
Write-Host "Mail password saved in .env (clipboard cleared)." -ForegroundColor Green
schtasks /End /TN ReportBot | Out-Null; Start-Sleep 4; schtasks /Run /TN ReportBot | Out-Null
Write-Host "Restarting VERONICA ..."; Start-Sleep 18
try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 8).Content } catch { "not answering yet - wait 30 s" }
Write-Host "Done. In VERONICA say: mail this to me" -ForegroundColor Green
Read-Host "Press Enter to close"
