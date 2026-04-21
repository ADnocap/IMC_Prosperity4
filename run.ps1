# Launch the backtest dashboard (frontend + data server).
# Run backtests from the browser's Run tab.
#
# Usage:  .\run.ps1

$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"
$env:PYTHONDONTWRITEBYTECODE = "1"

# Add cargo to PATH
$cargoPath = "$env:USERPROFILE\.cargo\bin"
if ($env:PATH -notlike "*$cargoPath*") {
    $env:PATH = "$cargoPath;$env:PATH"
}

# Use absolute paths
$projectRoot = $PSScriptRoot
$backtestsDir = Join-Path $projectRoot "tmp\backtests"
if (-not (Test-Path $backtestsDir)) { New-Item -ItemType Directory -Path $backtestsDir -Force | Out-Null }

# Kill any leftover data server from a previous run (both PID file and port holders)
$existingPid = Get-Content "$env:USERPROFILE\.prosperity4mcbt\dashboard_server.pid" -ErrorAction SilentlyContinue
if ($existingPid) {
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
}

# Kill anything currently listening on :8001 -- previous .ps1 runs don't always clean up.
$holders = @(Get-NetTCPConnection -LocalPort 8001 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($holderPid in $holders) {
    if ($holderPid -and $holderPid -ne 0) {
        Write-Host "  killing stale process $holderPid on :8001" -ForegroundColor DarkYellow
        Stop-Process -Id $holderPid -Force -ErrorAction SilentlyContinue
    }
}
$viteHolders = @(Get-NetTCPConnection -LocalPort 5555 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique)
foreach ($holderPid in $viteHolders) {
    if ($holderPid -and $holderPid -ne 0) {
        Write-Host "  killing stale process $holderPid on :5555" -ForegroundColor DarkYellow
        Stop-Process -Id $holderPid -Force -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 300

# Start data server in background (stdout/stderr surfaced so import errors aren't hidden)
Write-Host "Starting data server on :8001..." -ForegroundColor Cyan
$serverLog = Join-Path $backtestsDir "dashboard_server.log"
$serverProcess = Start-Process -FilePath "python" -ArgumentList "-m", "backtester.dashboard_server", $backtestsDir, "8001" -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden -RedirectStandardOutput $serverLog -RedirectStandardError "$serverLog.err"

# Start Vite frontend in background
Write-Host "Starting frontend on :5555 (first run pre-bundles deps -- may take 20-30s)..." -ForegroundColor Cyan
$vizDir = Join-Path $projectRoot "visualizer"
$vizLog = Join-Path $backtestsDir "vite.log"
$vizProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm.cmd run dev" -WorkingDirectory $vizDir -PassThru -WindowStyle Hidden -RedirectStandardOutput $vizLog -RedirectStandardError "$vizLog.err"

# Wait for Vite to actually be ready before opening the browser
$viteReady = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    try {
        $null = Invoke-WebRequest -Uri "http://localhost:5555/" -UseBasicParsing -TimeoutSec 1 -ErrorAction Stop
        $viteReady = $true
        break
    } catch {}
    if ($i -eq 5) { Write-Host "  still waiting on Vite..." -ForegroundColor DarkGray }
}
if (-not $viteReady) {
    Write-Host "Vite did not come up within 60s. Check $vizLog / $vizLog.err" -ForegroundColor Red
}

Start-Process "http://localhost:5555/#/mc?tab=run"
Write-Host "Dashboard open at http://localhost:5555/" -ForegroundColor Green
Write-Host "Server log: $serverLog   Vite log: $vizLog" -ForegroundColor DarkGray
Write-Host "Press Ctrl+C to stop." -ForegroundColor DarkGray

try {
    while ($true) { Start-Sleep -Seconds 60 }
}
finally {
    Write-Host "`nShutting down..." -ForegroundColor Yellow
    if ($serverProcess -and !$serverProcess.HasExited) {
        Stop-Process -Id $serverProcess.Id -Force -ErrorAction SilentlyContinue
    }
    if ($vizProcess -and !$vizProcess.HasExited) {
        Stop-Process -Id $vizProcess.Id -Force -ErrorAction SilentlyContinue
    }
}
