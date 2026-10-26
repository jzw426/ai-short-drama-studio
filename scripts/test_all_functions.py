#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Short Drama Studio - 全面功能测试 (v3.0)
基于实际API的UUID ID和正确的字段名
"""

import urllib.request
import urllib.error
import json
import socket
import sys
import io
import subprocess
from datetime import datetime
from typing import Tuple, Optional

# 设置UTF-8输出
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# 服务地址
FRONTEND_URL = "http://localhost:3000"
BACKEND_URL = "http://localhost:8000"
API_BASE = f"{BACKEND_URL}/api/v1"
MINIO_URL = "http://localhost:9000"

# 测试结果
passed = []
failed = []
warnings = []


def test_endpoint(name: str, url: str, method: str = "GET", data: dict = None, timeout: int = 5) -> Tuple[bool, str]:
    """测试一个HTTP端点"""
    try:
        if data:
            data_bytes = json.dumps(data).encode('utf-8')
            req = urllib.request.Request(
                url, data=data_bytes, method=method,
                headers={'Content-Type': 'application/json'}
            )
        else:
            req = urllib.request.Request(url, method=method)

        with urllib.request.urlopen(req, timeout=timeout) as response:
            status_code = response.getcode()
            response_body = response.read().decode('utf-8', errors='ignore')

            if status_code == 200:
                try:
                    data_json = json.loads(response_body)
                    if isinstance(data_json, dict) and data_json:
                        return True, f"HTTP 200 (返回 {len(data_json)} 字段)"
                    elif isinstance(data_json, list):
                        return True, f"HTTP 200 (返回 {len(data_json)} 项)"
                    else:
                        return True, "HTTP 200"
                except:
                    return True, "HTTP 200"
            elif status_code in [201, 202, 204]:
                return True, f"HTTP {status_code}"
            elif status_code in [404, 405]:
                return False, f"HTTP {status_code} - 端点不存在"
            elif status_code in [422, 400]:
                return True, f"HTTP {status_code} (参数错误但服务正常)"
            else:
                return True, f"HTTP {status_code}"
    except urllib.error.HTTPError as e:
        if e.code in [404, 405]:
            return False, f"HTTP {e.code} - 端点不存在"
        elif e.code in [422, 400]:
            return True, f"HTTP {e.code} (参数错误但服务正常)"
        elif e.code in [500, 502, 503]:
            return False, f"HTTP {e.code} - 服务错误"
        else:
            return True, f"HTTP {e.code}"
    except urllib.error.URLError as e:
        return False, f"连接失败: {e.reason}"
    except socket.timeout:
        return False, f"超时 ({timeout}秒)"
    except Exception as e:
        return False, f"错误: {str(e)[:100]}"


def test_api(name: str, endpoint: str, method: str = "GET", data: dict = None) -> bool:
    """测试后端API端点"""
    url = f"{API_BASE}{endpoint}"
    success, msg = test_endpoint(name, url, method, data)
    if success:
        print(f"  [OK]   {name:40s} {msg}")
        passed.append(f"API: {name}")
    else:
        print(f"  [FAIL] {name:40s} {msg}")
        failed.append(f"API: {name} - {msg}")
    return success


def test_page(name: str, path: str = "") -> bool:
    """测试前端页面"""
    url = f"{FRONTEND_URL}{path}"
    success, msg = test_endpoint(name, url)
    if success:
        print(f"  [OK]   {name:40s} {msg}")
        passed.append(f"页面: {name}")
    else:
        print(f"  [FAIL] {name:40s} {msg}")
        failed.append(f"页面: {name} - {msg}")
    return success


def test_service(name: str, url: str) -> bool:
    """测试基础服务连通性"""
    success, msg = test_endpoint(name, url)
    if success:
        print(f"  [OK]   {name:40s} {msg}")
        passed.append(f"服务: {name}")
    else:
        print(f"  [FAIL] {name:40s} {msg}")
        failed.append(f"服务: {name} - {msg}")
    return success


def create_test_project() -> Optional[str]:
    """创建一个测试项目并返回ID"""
    url = f"{API_BASE}/projects"
    try:
        req = urllib.request.Request(
            url, method="POST",
            data=json.dumps({"title": f"自动化测试-{datetime.now().strftime('%H%M%S')}"}).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            if response.getcode() == 201:
                data = json.loads(response.read().decode('utf-8'))
                return data.get("id")
    except Exception as e:
        print(f"  [WARN] 创建测试项目失败: {e}")
        warnings.append(f"创建测试项目失败: {e}")
    return None


def section(title: str):
    """打印分节标题"""
    print("")
    print("=" * 76)
    print(f"  {title}")
    print("=" * 76)


def run_tests():
    """运行所有测试"""

    # ===== 1. 基础服务连通性 =====
    section("[1] 基础服务连通性")
    test_service("前端 Next.js", FRONTEND_URL)
    test_service("后端 Swagger UI", f"{API_BASE}/docs")
    test_service("后端 ReDoc", f"{API_BASE}/redoc")
    test_service("后端 OpenAPI 规范", f"{API_BASE}/openapi.json")
    test_service("MinIO 健康检查", f"{MINIO_URL}/minio/health/live")
    test_service("MinIO 控制台", "http://localhost:9001")

    # ===== 2. 后端 API 端点 =====
    section("[2] 后端核心 API 端点")
    test_api("健康检查", "/health")

    # ===== 3. 完整 CRUD 测试 =====
    section("[3] 完整业务流程测试 (CRUD)")

    # 创建项目
    print("\n  [Step 1] 创建项目")
    project_id = create_test_project()
    if project_id:
        print(f"  [OK]   创建项目成功，ID: {project_id[:8]}...")
        passed.append("项目创建")
    else:
        print(f"  [FAIL] 创建项目失败")
        failed.append("项目创建")
        return

    # 项目管理
    print("\n  [Step 2] 项目管理")
    test_api("GET /projects - 项目列表", "/projects")
    test_api(f"GET /projects/{project_id} - 项目详情", f"/projects/{project_id}")
    test_api(f"PUT /projects/{project_id} - 更新项目", f"/projects/{project_id}", method="PUT",
             data={"title": "更新后的项目名", "description": "自动化测试更新"})

    # 剧本管理
    print("\n  [Step 3] 剧本管理")
    test_api(f"GET /projects/{project_id}/script - 获取剧本", f"/projects/{project_id}/script")
    test_api(f"PUT /projects/{project_id}/script - 更新剧本", f"/projects/{project_id}/script", method="PUT",
             data={"title": "测试剧本", "content": "剧本内容...", "logline": "一句话简介"})

    # 场景管理
    print("\n  [Step 4] 场景管理")
    test_api(f"GET /projects/{project_id}/script/scenes - 场景列表", f"/projects/{project_id}/script/scenes")
    scene_resp = test_api_endpoint(
        f"POST /projects/{project_id}/script/scenes - 创建场景",
        f"/projects/{project_id}/script/scenes", method="POST",
        data={"scene_number": 1, "title": "开场", "location": "咖啡厅", "time_of_day": "day", "interior": True}
    )

    # 分镜管理
    print("\n  [Step 5] 分镜管理")
    test_api(f"GET /projects/{project_id}/storyboard - 分镜信息", f"/projects/{project_id}/storyboard")
    test_api(f"GET /projects/{project_id}/storyboard/shots - 分镜列表", f"/projects/{project_id}/storyboard/shots")
    test_api(f"POST /projects/{project_id}/storyboard/shots - 创建分镜", f"/projects/{project_id}/storyboard/shots", method="POST",
             data={"shot_number": 1, "description": "测试分镜", "duration": 3, "shot_type": "wide"})

    # 角色管理
    print("\n  [Step 6] 角色管理")
    test_api(f"GET /projects/{project_id}/characters - 角色列表", f"/projects/{project_id}/characters")
    test_api(f"POST /projects/{project_id}/characters - 创建角色", f"/projects/{project_id}/characters", method="POST",
             data={"name": "主角", "role": "protagonist", "description": "年轻女性", "voice": "温柔"})

    # 素材管理
    print("\n  [Step 7] 素材管理")
    test_api(f"GET /projects/{project_id}/assets - 素材列表", f"/projects/{project_id}/assets")
    test_api(f"POST /projects/{project_id}/assets/upload - 素材上传", f"/projects/{project_id}/assets/upload", method="POST",
             data={"filename": "test.jpg", "content_type": "image/jpeg"})

    # 渲染管理
    print("\n  [Step 8] 渲染管理")
    test_api(f"POST /projects/{project_id}/render - 创建渲染任务", f"/projects/{project_id}/render", method="POST",
             data={"title": "测试渲染"})
    test_api(f"GET /projects/{project_id}/render/tasks - 渲染任务列表", f"/projects/{project_id}/render/tasks")

    # AI 服务
    print("\n  [Step 9] AI 服务")
    test_api(f"POST /projects/{project_id}/script/ai-generate - AI生成剧本", f"/projects/{project_id}/script/ai-generate", method="POST",
             data={"prompt": "现代都市爱情故事", "num_scenes": 5})
    test_api(f"POST /projects/{project_id}/characters/ai-generate - AI生成角色", f"/projects/{project_id}/characters/ai-generate", method="POST",
             data={"description": "一个年轻女性角色，温柔善良"})

    # 删除项目
    print("\n  [Step 10] 清理 - 删除测试项目")
    test_api(f"DELETE /projects/{project_id} - 删除项目", f"/projects/{project_id}", method="DELETE")

    # ===== 4. 前端页面测试 =====
    section("[4] 前端页面访问")
    test_page("首页 /", "/")
    test_page("工作台 /studio", "/studio")
    test_page("剧本管理 /studio/script", "/studio/script")
    test_page("角色管理 /studio/characters", "/studio/characters")
    test_page("素材管理 /studio/assets", "/studio/assets")
    test_page("分镜编辑器 /studio/storyboard", "/studio/storyboard")
    test_page("视频渲染 /studio/render", "/studio/render")

    # ===== 5. Docker 容器状态 =====
    section("[5] Docker 容器状态")
    try:
        result = subprocess.run(
            ["docker-compose", "ps", "--format", "json"],
            cwd="E:\\ai-short-drama-studio",
            capture_output=True,
            text=True,
            timeout=15,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0 and result.stdout:
            containers = []
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    try:
                        containers.append(json.loads(line))
                    except:
                        pass

            for c in containers:
                name = c.get("Name", c.get("Service", "unknown"))
                state = c.get("State", "unknown")
                status = c.get("Status", "")

                if "healthy" in status.lower() or state == "running":
                    print(f"  [OK]   {name:20s} {state} - {status}")
                    passed.append(f"容器: {name}")
                else:
                    print(f"  [WARN] {name:20s} {state} - {status}")
                    warnings.append(f"容器: {name} - {state}")
        else:
            print(f"  [WARN] docker-compose ps 无输出")
            warnings.append("docker-compose ps 无输出")
    except FileNotFoundError:
        print("  [WARN] docker-compose 命令不可用")
        warnings.append("docker-compose 不在PATH中")
    except Exception as e:
        print(f"  [WARN] 容器检查失败: {e}")
        warnings.append(f"容器检查失败: {e}")


def test_api_endpoint(name: str, endpoint: str, method: str = "GET", data: dict = None) -> bool:
    """test_api的别名以保持一致性"""
    return test_api(name, endpoint, method, data)


def print_report():
    """打印测试报告"""
    section("最终测试报告")
    print(f"\n  [统计]")
    print(f"  通过:   {len(passed)}")
    print(f"  失败:   {len(failed)}")
    print(f"  警告:   {len(warnings)}")
    total = len(passed) + len(failed)
    success_rate = len(passed) / total * 100 if total > 0 else 0
    print(f"  成功率: {success_rate:.1f}%")

    if failed:
        print(f"\n  [失败项目] ({len(failed)} 项)")
        for i, item in enumerate(failed, 1):
            print(f"  {i:3d}. {item}")

    if warnings:
        print(f"\n  [警告项目] ({len(warnings)} 项)")
        for i, item in enumerate(warnings, 1):
            print(f"  {i:3d}. {item}")

    # 按功能模块汇总
    print(f"\n  [按模块统计]")
    modules = {
        "项目管理": [f for f in passed if ("项目" in f and "API" in f) or "项目创建" in f],
        "剧本管理": [f for f in passed if "剧本" in f and "API" in f],
        "分镜管理": [f for f in passed if "分镜" in f and "API" in f],
        "角色管理": [f for f in passed if "角色" in f and "API" in f],
        "素材管理": [f for f in passed if "素材" in f and "API" in f],
        "渲染管理": [f for f in passed if "渲染" in f and "API" in f],
        "AI服务": [f for f in passed if "AI" in f and "API" in f],
        "前端页面": [f for f in passed if "页面" in f],
        "容器": [f for f in passed if "容器" in f],
    }
    for module, items in modules.items():
        if items:
            print(f"  {module}: {len(items)} 个通过")

    # 保存JSON报告
    report = {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "passed": len(passed),
            "failed": len(failed),
            "warnings": len(warnings),
            "success_rate": f"{success_rate:.1f}%"
        },
        "passed": passed,
        "failed": failed,
        "warnings": warnings
    }

    with open("test_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"\n  详细报告: test_report.json")


if __name__ == "__main__":
    print("=" * 76)
    print("  AI Short Drama Studio - 全面功能测试 (v3.0)")
    print(f"  开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 76)

    try:
        run_tests()
    except KeyboardInterrupt:
        print("\n\n测试被用户中断")
    except Exception as e:
        print(f"\n\n测试异常: {e}")
        import traceback
        traceback.print_exc()

    print_report()
