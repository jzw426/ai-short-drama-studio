<#
AI Short Drama Studio - Backend Startup Script (Local Mode)

T0 修复点：
- 依赖文件 requirements-minimal.txt（backend/ 下不存在）改为 requirements.txt；安装失败直接退出，
  旧版失败后仍打印 "OK - dependencies installed"。
- 去掉写死的 C:\Users\jiangzewen\...\python.exe。
- 接受 Python 3.11 / 3.12（Docker 镜像与依赖均按 3.11 构建，旧版强制 3.12）。
- 默认只监听 127.0.0.1，避免开发机把未鉴权接口暴露到局域网。
#>
param(
    [int]$Port = 8000,
    [string]$BindHost = "127.0.0.1",
    [switch]$NoReload
)

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.WindowTitle = "AI Drama Studio - Backend"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Short Drama Studio - Backend" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $scriptPath "backend")

function Find-SystemPython {
    $candidates = @(
        @{ Exe = "py";      Args = @("-3.12") },
        @{ Exe = "py";      Args = @("-3.11") },
        @{ Exe = "python";  Args = @() },
        @{ Exe = "python3"; Args = @() }
    )
    foreach ($c in $candidates) {
        if (-not (Get-Command $c.Exe -ErrorAction SilentlyContinue)) { continue }
        try { $raw = (& $c.Exe @($c.Args + @("--version")) 2>&1) | Out-String } catch { continue }
        if ($raw -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 11) {
                return @{ Exe = $c.Exe; Args = $c.Args; Version = "$major.$minor" }
            }
        }
    }
    return $null
}

Write-Host "[1/5] Locating Python (>= 3.11)..." -ForegroundColor Yellow
$venvPython = Join-Path (Get-Location) "venv\Scripts\python.exe"

if (Test-Path $venvPython) {
    $python = @{ Exe = $venvPython; Args = @(); Version = ((& $venvPython --version 2>&1) -replace "Python ", "") }
    Write-Host "  Using existing venv: $venvPython" -ForegroundColor Green
} else {
    $python = Find-SystemPython
    if (-not $python) {
        Write-Host "[ERROR] No Python >= 3.11 found on PATH." -ForegroundColor Red
        Write-Host "Install Python 3.11 or 3.12 from https://www.python.org/downloads/" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "  Found Python $($python.Version): $($python.Exe)" -ForegroundColor Green
}

Write-Host ""
Write-Host "[2/5] Preparing virtual environment..." -ForegroundColor Yellow
if (-not (Test-Path (Join-Path (Get-Location) "venv"))) {
    & $python.Exe @($python.Args + @("-m", "venv", "venv"))
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] venv creation failed" -ForegroundColor Red; exit 1 }
    Write-Host "  OK - venv created" -ForegroundColor Green
} else {
    Write-Host "  OK - venv exists" -ForegroundColor Green
}
$venvPython = Join-Path (Get-Location) "venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) { Write-Host "[ERROR] venv python missing: $venvPython" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "[3/5] Installing dependencies..." -ForegroundColor Yellow
if (-not (Test-Path "requirements.txt")) {
    Write-Host "[ERROR] backend/requirements.txt not found" -ForegroundColor Red
    exit 1
}
$needInstall = $true
& $venvPython -c "import fastapi, sqlalchemy, pydantic_settings" 2>$null
if ($LASTEXITCODE -eq 0) { $needInstall = $false }

if ($needInstall) {
    Write-Host "  Installing from requirements.txt (Tsinghua mirror first)..." -ForegroundColor Gray
    & $venvPython -m pip install --disable-pip-version-check -q -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Mirror failed, retrying with default index..." -ForegroundColor Yellow
        & $venvPython -m pip install --disable-pip-version-check -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[ERROR] Dependency installation failed. Fix the pip error above; not starting." -ForegroundColor Red
            Read-Host "Press Enter to exit"
            exit 1
        }
    }
    Write-Host "  OK - dependencies installed" -ForegroundColor Green
} else {
    Write-Host "  OK - dependencies already present" -ForegroundColor Green
}

Write-Host ""
Write-Host "[4/5] Preparing data directory..." -ForegroundColor Yellow
New-Item -ItemType Directory -Path "data" -Force | Out-Null
New-Item -ItemType Directory -Path "data\uploads" -Force | Out-Null
Write-Host "  OK - data/ ready" -ForegroundColor Green

Write-Host ""
Write-Host "[5/5] Starting FastAPI backend..." -ForegroundColor Yellow
$uvicornArgs = @("-m", "uvicorn", "app.main:app", "--host", $BindHost, "--port", "$Port")
if (-not $NoReload) { $uvicornArgs += "--reload" }

Write-Host ""
Write-Host "  ========================================" -ForegroundColor Green
Write-Host "  URL:  http://$($BindHost):$Port" -ForegroundColor Green
Write-Host "  Docs: http://$($BindHost):$Port/api/v1/docs" -ForegroundColor Green
Write-Host "  Press Ctrl+C to stop" -ForegroundColor Green
Write-Host "  ========================================" -ForegroundColor Green
Write-Host ""

& $venvPython @uvicornArgs
