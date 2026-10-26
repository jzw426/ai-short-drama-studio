@echo off
chcp 65001 > nul
echo ==================================================
echo AI Short Drama Studio - 功能检测
echo ==================================================
echo.

echo [1/5] 前端构建检测
echo ------------------------------------------------
if exist "frontend\package.json" (
    echo [OK] package.json 存在
) else (
    echo [FAIL] package.json 缺失
)

if exist "frontend\node_modules" (
    echo [OK] node_modules 已安装
) else (
    echo [FAIL] node_modules 缺失，请运行 npm install
)

if exist "frontend\next.config.js" (
    echo [OK] Next.js 配置存在
) else (
    echo [FAIL] Next.js 配置缺失
)

echo.
echo [2/5] 后端配置检测
echo ------------------------------------------------
if exist "backend\requirements.txt" (
    echo [OK] requirements.txt 存在
) else (
    echo [FAIL] requirements.txt 缺失
)

if exist "backend\app\main.py" (
    echo [OK] FastAPI 主文件存在
) else (
    echo [FAIL] FastAPI 主文件缺失
)

if exist "docker-compose.yml" (
    echo [OK] Docker Compose 配置存在
) else (
    echo [FAIL] Docker Compose 配置缺失
)

echo.
echo [3/5] 功能模块检测
echo ------------------------------------------------
if exist "frontend\src\app\page.tsx" (
    echo [OK] 首页存在
) else (
    echo [FAIL] 首页缺失
)

if exist "frontend\src\app\studio\script\page.tsx" (
    echo [OK] 剧本管理页面存在
) else (
    echo [FAIL] 剧本管理页面缺失
)

if exist "frontend\src\app\studio\storyboard\page.tsx" (
    echo [OK] 分镜编辑器页面存在
) else (
    echo [FAIL] 分镜编辑器页面缺失
)

if exist "frontend\src\app\studio\render\page.tsx" (
    echo [OK] 视频渲染页面存在
) else (
    echo [FAIL] 视频渲染页面缺失
)

echo.
echo [4/5] 代码质量检测
echo ------------------------------------------------
if exist "frontend\tsconfig.json" (
    echo [OK] TypeScript 配置存在
) else (
    echo [FAIL] TypeScript 配置缺失
)

dir /s /b frontend\src\*.test.tsx 2>nul | find /c /v "" > nul 2>&1
if errorlevel 1 (
    echo [FAIL] 前端测试文件缺失
) else (
    echo [OK] 前端测试文件存在
)

echo.
echo [5/5] 文档完整性检测
echo ------------------------------------------------
if exist "README.md" (
    echo [OK] README 存在
) else (
    echo [FAIL] README 缺失
)

if exist "frontend\AUDIT_REPORT.md" (
    echo [OK] 前端审计报告存在
) else (
    echo [FAIL] 前端审计报告缺失
)

if exist "TESTING_GUIDE.md" (
    echo [OK] 测试指南存在
) else (
    echo [FAIL] 测试指南缺失
)

echo.
echo ==================================================
echo 检测完成
echo ==================================================
echo.
echo 提示：
echo 1. 前端构建：cd frontend && npm run build
echo 2. 后端启动：使用 Docker Compose（推荐）
echo 3. 运行测试：参考 TESTING_GUIDE.md
echo.
pause
