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

# Kill any leftover data server from a previous run
$existingPid = Get-Content "$env:USERPROFILE\.prosperity4mcbt\dashboard_server.pid" -ErrorAction SilentlyContinue
if ($existingPid) {
    Stop-Process -Id $existingPid -Force -ErrorAction SilentlyContinue
}

# Start data server in background
Write-Host "Starting data server on :8001..." -ForegroundColor Cyan
$serverProcess = Start-Process -FilePath "python" -ArgumentList "-m", "backtester.dashboard_server", $backtestsDir, "8001" -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden

# Start Vite frontend in background
Write-Host "Starting frontend on :5555..." -ForegroundColor Cyan
$vizDir = Join-Path $projectRoot "visualizer"
$vizProcess = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm.cmd run dev" -WorkingDirectory $vizDir -PassThru -WindowStyle Hidden

# Wait for frontend to be ready, then open browser on Run tab
Start-Sleep -Seconds 3
Start-Process "http://localhost:5555/#/mc?tab=run"
Write-Host "Dashboard open at http://localhost:5555/" -ForegroundColor Green
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
