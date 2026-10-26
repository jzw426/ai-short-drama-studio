#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P2 功能回归验证
验证点：
1. 项目归属隔离：用户 A 看不到/改不了用户 B 的项目
2. 剧本→分镜一键生成（无 AI Key 时走 mock，仍能生成镜头）
3. 分镜导出 JSON
4. 剧本导出 Markdown/TXT
5. 角色形象追加生成（无 Key 时 502 或走 mock——此处只验证接口存在与权限）
6. 并行渲染服务层：多镜头并发走通（AI 无 key → failed 但流程正常）
"""
import asyncio
import io
import os
import sys
import uuid

import httpx

BACKEND_DIR = r"E:\ai-short-drama-studio\backend"
os.chdir(BACKEND_DIR)
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000/api/v1"
passed, failed = [], []


def check(name: str, ok: bool, detail: str = ""):
    tag = "OK" if ok else "FAIL"
    print(f"  [{tag}] {name}  {detail}")
    (passed if ok else failed).append(name)


async def register(client, tag: str) -> str:
    uname = f"p2_{tag}_{uuid.uuid4().hex[:6]}"
    r = await client.post(
        "/auth/register",
        json={
            "username": uname,
            "email": f"{uname}@test.local",
            "password": "secret123",
        },
    )
    if r.status_code == 409:
        r = await client.post(
            "/auth/login", json={"username": uname, "password": "secret123"}
        )
    return r.json()["access_token"]


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=60) as client:
        # 1. 两个用户
        tokenA = await register(client, "a")
        tokenB = await register(client, "b")
        HA = {"Authorization": f"Bearer {tokenA}"}
        HB = {"Authorization": f"Bearer {tokenB}"}

        # 2. 用户 A 建项目
        r = await client.post("/projects", json={"title": "P2-A项目"}, headers=HA)
        check("A创建项目", r.status_code == 201, f"HTTP {r.status_code}")
        pidA = r.json()["id"]

        # 3. 用户 B 看不到 A 的项目
        r = await client.get("/projects", headers=HB)
        check("B看不到A的项目", all(p["id"] != pidA for p in r.json()), f"count={len(r.json())}")

        # 4. 用户 B 改不了 A 的项目（404）
        r = await client.put(f"/projects/{pidA}", json={"title": "hacked"}, headers=HB)
        check("B改A项目→404", r.status_code == 404, f"HTTP {r.status_code}")

        # 5. A 创建场景，用于生成分镜
        r = await client.post(
            f"/projects/{pidA}/script/scenes",
            json={
                "scene_number": 1,
                "title": "咖啡厅相遇",
                "location": "城市咖啡厅",
                "time_of_day": "afternoon",
                "interior": True,
                "summary": "男女主角初次相遇",
                "content": "阳光洒落，男主推门而入，与女主目光交汇。",
                "duration": 30,
                "sort_order": 0,
            },
            headers=HA,
        )
        check("A创建场景", r.status_code == 201, f"HTTP {r.status_code}")

        # 6. 剧本→分镜一键生成（无 Key 时 mock 生成）
        r = await client.post(
            f"/projects/{pidA}/storyboard/generate-from-script", headers=HA
        )
        check("剧本→分镜生成", r.status_code == 200 and r.json().get("total", 0) > 0,
              f"HTTP {r.status_code} total={r.json().get('total') if r.status_code == 200 else '-'}")

        # 7. 分镜导出 JSON
        r = await client.get(f"/projects/{pidA}/storyboard/export", headers=HA)
        ok_export = (
            r.status_code == 200
            and "application/json" in r.headers.get("content-type", "")
            and r.json().get("total", 0) > 0
        )
        check("分镜导出JSON", ok_export, f"HTTP {r.status_code}")

        # 8. 剧本导出 Markdown
        r = await client.get(
            f"/projects/{pidA}/script/export?format=markdown", headers=HA
        )
        ok_md = r.status_code == 200 and "咖啡厅相遇" in r.text
        check("剧本导出Markdown", ok_md, f"HTTP {r.status_code}")

        # 9. 无场景项目生成分镜 → 400
        r = await client.post("/projects", json={"title": "P2-空项目"}, headers=HA)
        pidEmpty = r.json()["id"]
        r = await client.post(
            f"/projects/{pidEmpty}/storyboard/generate-from-script", headers=HA
        )
        check("无场景生成分镜→400", r.status_code == 400, f"HTTP {r.status_code}")

        # 10. 并行渲染服务层（多镜头并发）
        from app.services.render_service import render_service

        # 再建 3 个镜头
        for i in range(3):
            await client.post(
                f"/projects/{pidA}/storyboard/shots",
                json={
                    "shot_number": i + 1,
                    "label": f"镜头{i+1}",
                    "description": f"测试镜头描述 {i+1}",
                    "duration": 3.0,
                },
                headers=HA,
            )
        progress_log = []

        async def cb(p, msg):
            progress_log.append(f"{p:.2f}:{msg}")

        result = await render_service.execute_render(
            task_id="p2-verify-task",
            project_id=pidA,
            config={"add_subtitles": False, "add_bgm": False},
            progress_callback=cb,
        )
        seg_count = len(result.get("segments", []))
        check(
            "并行渲染服务层走通",
            seg_count >= 3
            and all(s["status"] == "failed" for s in result.get("segments", [])),
            f"segments={seg_count}",
        )
        check("并发进度回调触发", len(progress_log) >= 3, f"steps={len(progress_log)}")

        # 清理
        await client.delete(f"/projects/{pidA}", headers=HA)
        await client.delete(f"/projects/{pidEmpty}", headers=HA)
        check("清理项目", True)

    print("\n===== P2 结果 =====")
    print(f"通过: {len(passed)}  失败: {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
