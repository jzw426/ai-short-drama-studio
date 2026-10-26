#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0 修复验证脚本
验证点：
1. 提交渲染任务：Celery 不可用时任务应标记 failed 并写明原因（不再永远 queued）
2. render_service 直查数据库获取分镜（不再走 http://localhost:8000 自调用）
3. 取消接口不再拿数据库 UUID 当 Celery task id（无 celery_task_id 时跳过 revoke）
4. 业务路由要求 JWT 认证（401 拦截）
"""
import asyncio
import io
import os
import sys

import httpx

# 与后端启动环境保持一致（backend 工作目录下的 .env）
BACKEND_DIR = r"E:\ai-short-drama-studio\backend"
os.chdir(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000/api/v1"
passed, failed = [], []

# 认证：业务路由现要求 JWT，脚本注册一个临时用户
TEST_USER = "p0fix_verify"
TEST_PASS = "verify-pass-123"


def check(name: str, ok: bool, detail: str = ""):
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {name}  {detail}")
    (passed if ok else failed).append(name)


async def get_token(client) -> str:
    r = await client.post(
        "/auth/register",
        json={
            "username": TEST_USER,
            "email": f"{TEST_USER}@test.local",
            "password": TEST_PASS,
            "display_name": "P0验证",
        },
    )
    if r.status_code == 409:  # 已存在，走登录
        r = await client.post(
            "/auth/login",
            json={"username": TEST_USER, "password": TEST_PASS},
        )
    check("获取测试Token", r.status_code in (200, 201), f"HTTP {r.status_code}")
    return r.json()["access_token"]


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # 1. 健康检查
        r = await client.get("/health")
        check("健康检查", r.status_code == 200, f"HTTP {r.status_code}")

        # 2. 未认证访问业务接口应 401
        r = await client.get("/projects")
        check("未认证访问项目列表→401", r.status_code == 401, f"HTTP {r.status_code}")

        token = await get_token(client)
        headers = {"Authorization": f"Bearer {token}"}

        # 3. 创建项目
        r = await client.post(
            "/projects", json={"title": "P0验证-渲染链路"}, headers=headers
        )
        check("创建项目", r.status_code == 201, f"HTTP {r.status_code}")
        if r.status_code != 201:
            return
        project_id = r.json()["id"]

        try:
            # 4. 创建镜头（POST /storyboard 会自建 storyboard）
            shot_payload = {
                "shot_number": 1,
                "label": "开场镜头",
                "description": "主角走进咖啡馆，阳光洒落",
                "duration": 3.0,
            }
            r = await client.post(
                f"/projects/{project_id}/storyboard/shots",
                json=shot_payload,
                headers=headers,
            )
            check("创建分镜镜头", r.status_code == 201, f"HTTP {r.status_code}")
            if r.status_code == 201:
                print(f"      镜头ID: {r.json()['id'][:8]}...")

            # 5. 提交渲染任务（当前无 Celery/Redis，验证失败标记逻辑）
            r = await client.post(
                f"/projects/{project_id}/render",
                json={"name": "P0验证渲染", "config": {"resolution": "1920x1080"}},
                headers=headers,
            )
            check("提交渲染任务", r.status_code == 201, f"HTTP {r.status_code}")
            if r.status_code == 201:
                task = r.json()
                print(
                    f"      任务ID: {task['id'][:8]}... status={task['status']} "
                    f"error={task.get('error_message')}"
                )
                # Celery 不可用时，任务应被标记为 failed 并写明原因
                check(
                    "Celery不可用→任务标记failed",
                    task["status"] == "failed" and "error_message" in task,
                    f"status={task['status']}, error={task.get('error_message')}",
                )

            # 6. 取消接口：failed 状态应返回 400（不会误触发 revoke）
            r = await client.post(f"/render/{task['id']}/cancel", headers=headers)
            check(
                "取消已失败任务→400",
                r.status_code == 400,
                f"HTTP {r.status_code} {r.text[:80]}",
            )

            # 7. 模拟渲染服务执行：验证直查数据库能取到镜头
            from app.services.render_service import render_service

            progress_log = []

            async def cb(p, msg):
                progress_log.append(f"{p:.2f}:{msg}")

            result = await render_service.execute_render(
                task_id="p0-verify-task",
                project_id=project_id,
                config={"add_subtitles": False, "add_bgm": False},
                progress_callback=cb,
            )
            errors = result.get("errors", [])
            segments = result.get("segments", [])
            print(f"      render结果: errors={errors} segments数={len(segments)}")
            check(
                "渲染服务直查数据库成功(无自调用错误)",
                not any("获取分镜数据失败" in e for e in errors),
                f"errors={errors}",
            )
            check(
                "镜头已进入渲染流程(AI无key→该镜头failed,但非取数失败)",
                len(segments) == 1 and segments[0].get("status") == "failed",
                f"segments={segments}",
            )
            check("进度回调已触发", len(progress_log) > 0, f"steps={len(progress_log)}")
        finally:
            # 8. 清理
            r = await client.delete(f"/projects/{project_id}", headers=headers)
            check("清理测试项目", r.status_code == 204, f"HTTP {r.status_code}")

    print("\n===== 结果 =====")
    print(f"通过: {len(passed)}  失败: {len(failed)}")
    if failed:
        print("失败项:")
        for f in failed:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
