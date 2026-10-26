<#
.AI Short Drama Studio - Frontend Startup Script (Local Mode)
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AI Drama Studio - Frontend"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Short Drama Studio - Frontend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$scriptPath\frontend"

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Check Node
Write-Host "[1/4] Checking Node.js..." -ForegroundColor Yellow
$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $node) {
    Write-Host "[ERROR] Node.js not found! Install Node.js 18+" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
$nodeVersion = & node --version
$npmVersion = & npm --version
Write-Host "  Node.js: $nodeVersion" -ForegroundColor Green
Write-Host "  npm: $npmVersion" -ForegroundColor Green

# Configure mirror
Write-Host ""
Write-Host "[2/4] Setting npm mirror..." -ForegroundColor Yellow
npm config set registry https://registry.npmmirror.com
Write-Host "  OK - taobao mirror" -ForegroundColor Green

# Install deps
Write-Host ""
Write-Host "[3/4] Installing dependencies (first time takes minutes)..." -ForegroundColor Yellow
if (-not (Test-Path "node_modules")) {
    npm install --legacy-peer-deps
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  npm install failed, check network" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
}

# Start service
Write-Host ""
Write-Host "[4/4] Starting Next.js frontend..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  URL: http://localhost:3000" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""

npm run dev
