<#
AI Short Drama Studio - Frontend Startup Script (Local Mode)

T0 修复点：
- 不再执行 "npm config set registry"（会永久改写机器级 npm 配置），改为单次安装参数。
- 校验 Node 主版本 >= 18。
- 默认只监听 127.0.0.1。
#>
param(
    [int]$Port = 3000,
    [string]$BindHost = "127.0.0.1"
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AI Drama Studio - Frontend"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Short Drama Studio - Frontend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $scriptPath "frontend")

Write-Host "[1/4] Checking Node.js..." -ForegroundColor Yellow
$node = Get-Command node -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "[ERROR] Node.js not found. Install Node.js 18+ (LTS)." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
$nodeVersion = (& node --version) -replace "v", ""
$nodeMajor = [int]($nodeVersion.Split(".")[0])
if ($nodeMajor -lt 18) {
    Write-Host "[ERROR] Node.js $nodeVersion is too old; 18+ required." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}
Write-Host "  Node.js: $nodeVersion" -ForegroundColor Green

Write-Host ""
Write-Host "[2/4] Checking dependencies..." -ForegroundColor Yellow
if (-not (Test-Path "node_modules")) {
    Write-Host "  Installing (one-off mirror flag, no global npm config change)..." -ForegroundColor Gray
    npm install --legacy-peer-deps --registry=https://registry.npmmirror.com
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Mirror failed, retrying with default registry..." -ForegroundColor Yellow
        npm install --legacy-peer-deps
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] npm install failed. Not starting." -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  OK - node_modules present" -ForegroundColor Green
}

Write-Host ""
Write-Host "[3/4] Preparing Next.js..." -ForegroundColor Yellow
if (-not (Test-Path ".next")) { Write-Host "  First compile may take a minute." -ForegroundColor Gray }

Write-Host ""
Write-Host "[4/4] Starting Next.js..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  URL: http://$($BindHost):$Port" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""

npm run dev -- --hostname $BindHost --port $Port
