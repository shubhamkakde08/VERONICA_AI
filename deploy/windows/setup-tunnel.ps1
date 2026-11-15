# Permanent internet address (e.g. https://veronica.venuspipes.com) with a Cloudflare Tunnel.
# No ports opened on your router, free HTTPS, link never changes. Runs as a Windows service at boot.
#
# Before running: Cloudflare Zero Trust -> Networks -> Tunnels -> Create tunnel (Cloudflared) -> name "reportbot"
#   -> copy the token shown in the install command -> Public Hostname: veronica.venuspipes.com -> Service: http://localhost:8000
# Then run AS ADMINISTRATOR:
#   powershell -ExecutionPolicy Bypass -File C:\reportbot\deploy\windows\setup-tunnel.ps1 -Token "eyJh..."
param([Parameter(Mandatory = $true)][string]$Token)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
$exe = "$Root\cloudflared.exe"
if (-not (Test-Path $exe)) {
    Write-Host "Downloading cloudflared..."
    Invoke-WebRequest -UseBasicParsing "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $exe
}
# remove an older service if present, then install with the token (starts automatically at boot)
try { & $exe service uninstall 2>$null } catch {}
& $exe service install $Token
Start-Sleep -Seconds 5
Get-Service cloudflared | Format-Table Name, Status, StartType
Write-Host "Tunnel installed. Next: set PUBLIC_BASE_URL in .env to your https address, run deploy\windows\restart.bat," -ForegroundColor Green
Write-Host "then:  .venv\Scripts\python.exe -m tools.manage set-webhook" -ForegroundColor Green
