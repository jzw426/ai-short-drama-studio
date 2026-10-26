<#
.AI Short Drama Studio - One-Click Startup
#>

$Host.UI.RawUI.WindowTitle = "AI Drama Studio - Launcher"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  AI Short Drama Studio - One-Click Start" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Will open 2 new windows:" -ForegroundColor Yellow
Write-Host "  1. Backend (FastAPI - Port 8000)" -ForegroundColor White
Write-Host "  2. Frontend (Next.js - Port 3000)" -ForegroundColor White
Write-Host ""
Write-Host "After started, visit: http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to start..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

$scriptPath = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "[1/2] Opening backend window..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-File", "$scriptPath\start-backend.ps1"
Start-Sleep -Seconds 2

Write-Host "[2/2] Opening frontend window..." -ForegroundColor Yellow
Start-Process powershell -ArgumentList "-NoExit", "-File", "$scriptPath\start-frontend.ps1"
Start-Sleep -Seconds 2

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  Started!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Two new windows opened:" -ForegroundColor White
Write-Host "  - Backend window: installing dependencies and starting" -ForegroundColor Gray
Write-Host "  - Frontend window: installing dependencies and starting" -ForegroundColor Gray
Write-Host ""
Write-Host "First time needs 5-10 minutes to install deps." -ForegroundColor Yellow
Write-Host ""
Write-Host "Visit: " -ForegroundColor White -NoNewline
Write-Host "http://localhost:3000" -ForegroundColor Green
Write-Host ""
Write-Host "API Docs: " -ForegroundColor White -NoNewline
Write-Host "http://localhost:8000/docs" -ForegroundColor Green
Write-Host ""
Write-Host "Press any key to close this window..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
