# ReportBot / VERONICA - one-time install on Windows (no Docker)
# Run in PowerShell:   cd C:\reportbot ;  powershell -ExecutionPolicy Bypass -File deploy\windows\install.ps1
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
Set-Location $Root
Write-Host "== ReportBot install in $Root" -ForegroundColor Cyan

# 1. Python 3.11+
$py = $null
foreach ($c in @("py -3.12", "py -3.13", "py -3.11", "python")) {
    try { $v = & cmd /c "$c --version" 2>$null; if ($v -match "Python 3\.(1[1-9])") { $py = $c; break } } catch {}
}
if (-not $py) {
    Write-Host "Python 3.11+ not found. Install Python 3.12 from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH'), then run this again." -ForegroundColor Red
    exit 1
}
Write-Host "Using $py ($v)"

# 2. Virtual environment + packages
if (-not (Test-Path ".venv\Scripts\python.exe")) { & cmd /c "$py -m venv .venv" }
& .venv\Scripts\python.exe -m pip install --upgrade pip
& .venv\Scripts\python.exe -m pip install -r requirements.txt

# 3. Settings file
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "Created .env - fill in your keys (notepad .env)" -ForegroundColor Yellow }
$envText = Get-Content ".env" -Raw
if ($envText -match "host\.docker\.internal") {
    # Not in Docker any more: MySQL on this machine is 127.0.0.1
    $envText -replace "host\.docker\.internal", "127.0.0.1" | Set-Content ".env" -Encoding UTF8
    Write-Host "Changed host.docker.internal -> 127.0.0.1 in .env (MySQL on this PC)." -ForegroundColor Yellow
}
New-Item -ItemType Directory -Force -Path "output", "logs" | Out-Null

# 4. PDF support check (WeasyPrint needs GTK on Windows)
# (checked through cmd so a missing library prints a warning instead of stopping the install)
& cmd /c ".venv\Scripts\python.exe -c ""import weasyprint"" >nul 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-Host "PDF engine not ready (GTK missing). Excel/HTML/chart/table work; PDF will be skipped." -ForegroundColor Yellow
    Write-Host "To enable PDF: install MSYS2 (https://www.msys2.org), then in 'MSYS2 MINGW64' run:  pacman -S mingw-w64-x86_64-pango" -ForegroundColor Yellow
    Write-Host "and add to .env:  WEASYPRINT_DLL_DIRECTORIES=C:\msys64\mingw64\bin" -ForegroundColor Yellow
}

# 5. Create tables + first admin
& .venv\Scripts\python.exe -m tools.manage init
Write-Host ""
Write-Host "Done. Test it now:  deploy\windows\start.bat   then open http://localhost:8000" -ForegroundColor Green
Write-Host "Auto-start at boot: powershell -ExecutionPolicy Bypass -File deploy\windows\install-autostart.ps1  (as Administrator)" -ForegroundColor Green
