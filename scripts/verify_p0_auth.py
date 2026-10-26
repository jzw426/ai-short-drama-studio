#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P0 认证 + 上传校验验证
验证点：
1. 未带 token 访问业务 API → 401
2. 注册 / 登录 / me 链路
3. 带 token 访问业务 API 正常
4. 上传合法文件 → 201；非法类型 → 415
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


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=30) as client:
        # 1. 未认证访问 → 401
        r = await client.get("/projects")
        check("未登录访问项目列表→401", r.status_code == 401, f"HTTP {r.status_code}")

        r = await client.post("/projects", json={"title": "x"})
        check("未登录创建项目→401", r.status_code == 401, f"HTTP {r.status_code}")

        # 2. 注册（随机用户名，避免历史数据冲突）
        uname = f"auth_verify_{uuid.uuid4().hex[:8]}"
        r = await client.post("/auth/register", json={
            "username": uname,
            "email": f"{uname}@example.com",
            "password": "secret123",
        })
        check("注册→201含token", r.status_code == 201 and "access_token" in r.json(), f"HTTP {r.status_code}")
        if r.status_code == 201:
            token = r.json()["access_token"]
            user_id = r.json()["user"]["id"]

            # 3. me
            r = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
            check("me→200", r.status_code == 200 and r.json()["id"] == user_id, f"HTTP {r.status_code}")

            # 4. 带 token 创建项目
            r = await client.post("/projects", json={"title": "P0认证验证"}, headers={"Authorization": f"Bearer {token}"})
            check("登录后创建项目→201", r.status_code == 201, f"HTTP {r.status_code}")
            if r.status_code == 201:
                project_id = r.json()["id"]

                # 5. 上传合法文件（伪造最小 PNG）
                png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
                files = {"file": ("test.png", png, "image/png")}
                r = await client.post(
                    f"/projects/{project_id}/assets/upload",
                    files=files,
                    data={"tags": "测试"},
                    headers={"Authorization": f"Bearer {token}"},
                )
                check("上传合法PNG→201", r.status_code == 201, f"HTTP {r.status_code}")

                # 6. 上传非法类型
                files2 = {"file": ("evil.txt", b"hello", "text/plain")}
                r = await client.post(
                    f"/projects/{project_id}/assets/upload",
                    files=files2,
                    headers={"Authorization": f"Bearer {token}"},
                )
                check("上传.txt→415", r.status_code == 415, f"HTTP {r.status_code}")

                # 7. 伪装扩展名（.png 内容但 MIME 是 text/plain）
                files3 = {"file": ("fake.png", b"not an image", "text/plain")}
                r = await client.post(
                    f"/projects/{project_id}/assets/upload",
                    files=files3,
                    headers={"Authorization": f"Bearer {token}"},
                )
                check("MIME与扩展名不符→415", r.status_code == 415, f"HTTP {r.status_code}")

                # 清理项目
                r = await client.delete(f"/projects/{project_id}", headers={"Authorization": f"Bearer {token}"})
                check("清理项目→204", r.status_code == 204, f"HTTP {r.status_code}")

        # 8. 登录（用随机用户验证登录链路）
        r = await client.post("/auth/login", json={"username": uname, "password": "secret123"})
        check("登录→200", r.status_code == 200 and "access_token" in r.json(), f"HTTP {r.status_code}")

        # 9. 错误密码
        r = await client.post("/auth/login", json={"username": uname, "password": "wrong"})
        check("错误密码→401", r.status_code == 401, f"HTTP {r.status_code}")

        # 10. 重复注册
        r = await client.post("/auth/register", json={
            "username": uname, "email": f"{uname}@example.com", "password": "secret123",
        })
        check("重复注册→409", r.status_code == 409, f"HTTP {r.status_code}")

    print("\n===== 结果 =====")
    print(f"通过: {len(passed)}  失败: {len(failed)}")
    if failed:
        for f in failed:
            print(f"  - {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
