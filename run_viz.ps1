# Usage: .\run_viz.ps1 [trader_file] [-Heavy]
#   trader_file  path to trader script (default: traders/a.py)
#   -Heavy       run heavy backtest instead of quick
param(
    [string]$Trader = "traders/a.py",
    [switch]$Heavy
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Ensure Cargo/Rust is on PATH if installed
$cargoPath = "$env:USERPROFILE\.cargo\bin"
if ((Test-Path $cargoPath) -and ($env:PATH -notlike "*$cargoPath*")) {
    $env:PATH += ";$cargoPath"
}

$Mode = if ($Heavy) { "--heavy" } else { "--quick" }
$TraderName = [System.IO.Path]::GetFileNameWithoutExtension($Trader)
$Timestamp = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
$RunDir = "tmp/${TraderName}_${Timestamp}"
$Out = "$RunDir/dashboard.json"
New-Item -ItemType Directory -Path $RunDir -Force | Out-Null

# Start Vite dev server in the background
Write-Host "==> Starting visualizer frontend..." -ForegroundColor Cyan
$vizJob = Start-Process -NoNewWindow -PassThru -FilePath "cmd.exe" `
    -ArgumentList "/c npx vite" -WorkingDirectory "visualizer"

# Wait for Vite to be ready
Write-Host "==> Waiting for Vite dev server..." -ForegroundColor Cyan
$vitePort = $null
for ($i = 0; $i -lt 30; $i++) {
    foreach ($port in 5555..5560) {
        try {
            Invoke-WebRequest -Uri "http://localhost:$port" -UseBasicParsing -TimeoutSec 1 | Out-Null
            $vitePort = $port
            break
        } catch {}
    }
    if ($vitePort) { break }
    Start-Sleep -Seconds 1
}

if (-not $vitePort) {
    Write-Host "==> Could not detect Vite. Continuing anyway..." -ForegroundColor Yellow
}

# Run backtester with --vis (starts data server on 8001 and opens browser)
Write-Host "==> Running backtest: $Trader ($Mode)" -ForegroundColor Cyan
prosperity4mcbt $Trader $Mode --vis --out $Out

Write-Host "==> Backtest complete. Dashboard is live. Press Ctrl+C to stop." -ForegroundColor Green

try {
    $vizJob.WaitForExit()
} finally {
    if (!$vizJob.HasExited) { $vizJob.Kill() }
}
