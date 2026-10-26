<#
.AI Short Drama Studio - Backend Startup Script (Local Mode)
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AI Drama Studio - Backend"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Short Drama Studio - Backend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location "$scriptPath\backend"

# Set UTF-8 encoding
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

# Check Python
Write-Host "[1/5] Checking Python..." -ForegroundColor Yellow

# Try Python 3.12 first (recommended for pydantic v1)
$pythonCandidates = @(
    "py",
    "python3.12",
    "C:\Users\jiangzewen\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Python312\python.exe",
    "python"
)

$python = $null
foreach ($candidate in $pythonCandidates) {
    $cmd = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($cmd) {
        try {
            $verOutput = & $candidate --version 2>&1
            if ($verOutput -match "Python 3\.12") {
                $python = $candidate
                Write-Host "  Found Python 3.12: $candidate" -ForegroundColor Green
                break
            }
        } catch {}
    }
}

if (-not $python) {
    Write-Host "[ERROR] Python 3.12 not found!" -ForegroundColor Red
    Write-Host "Install Python 3.12 from https://www.python.org/downloads/" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}
$version = & $python --version 2>&1
Write-Host "  Python: $version" -ForegroundColor Green

# Create venv
Write-Host ""
Write-Host "[2/5] Creating virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path "venv")) {
    & $python -m venv venv
    Write-Host "  OK - venv created" -ForegroundColor Green
} else {
    Write-Host "  OK - venv exists" -ForegroundColor Green
}

# Activate venv
Write-Host ""
Write-Host "[3/5] Activating venv..." -ForegroundColor Yellow
& ".\venv\Scripts\Activate.ps1"
Write-Host "  OK - activated" -ForegroundColor Green

# Install deps
Write-Host ""
Write-Host "[4/5] Installing dependencies (first time takes minutes)..." -ForegroundColor Yellow
if (-not (Test-Path "venv\Lib\site-packages\fastapi")) {
    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-minimal.txt --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Tsinghua mirror failed, trying default..." -ForegroundColor Yellow
        pip install -r requirements-minimal.txt
    }
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
}

# Create data dir
if (-not (Test-Path "data")) {
    New-Item -ItemType Directory -Path "data" | Out-Null
}

# Start service
Write-Host ""
Write-Host "[5/5] Starting FastAPI backend..." -ForegroundColor Yellow
Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  URL:  http://localhost:8000" -ForegroundColor Green
Write-Host "  Docs: http://localhost:8000/docs" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""

python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
