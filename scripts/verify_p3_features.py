"""
P3 功能回归验证（多模型路由 / 监控指标 / 用户配额）
运行方式（在 backend 目录）：
    venv\\Scripts\\python scripts\\verify_p3_features.py
说明：使用 FastAPI TestClient 进程内验证；脚本会临时清空 AGNES_API_KEY，
      AI 调用走 mock 降级路径（快速、稳定、不耗真实额度）。
"""
import os
import sys
import uuid

# 让脚本可以从 backend 目录独立运行
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
APP_DIR = os.path.join(ROOT_DIR, "backend")
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

# 必须先于 app 导入设置：测试期间不调用真实 AI
from app.core.config import settings  # noqa: E402
settings.AGNES_API_KEY = ""
settings.AI_DAILY_QUOTA = 100  # 默认额度，脚本内再单独压测

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[OK] {name}  {extra}")
    else:
        FAIL += 1
        print(f"[FAIL] {name}  {extra}")


def new_user(client: TestClient):
    """注册并登录随机用户，返回 (token, username)"""
    username = f"p3user_{uuid.uuid4().hex[:10]}"
    r = client.post("/api/v1/auth/register", json={
        "username": username,
        "email": f"{username}@test.local",
        "password": "testpass123",
        "display_name": "P3验证用户",
    })
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/v1/auth/login", json={
        "username": username, "password": "testpass123",
    })
    token = r.json()["access_token"]
    return token, username


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def main():
    with TestClient(app) as client:
        # ---------- 1. 监控指标 ----------
        token, _ = new_user(client)
        headers = auth_headers(token)

        h = client.get("/api/v1/health")
        body = h.json()
        check("health 返回 healthy", h.status_code == 200 and body.get("status") == "healthy", f"status={body.get('status')}")
        check("health 含 database 检查", body.get("database") == "ok", f"database={body.get('database')}")
        check("health 含 storage 检查", "storage" in body, "")
        check("health 含 uptime", "uptime_seconds" in body, "")

        m = client.get("/api/v1/metrics")
        mb = m.json()
        check("metrics 返回 200", m.status_code == 200, "")
        check("metrics 累计请求数 > 0", mb.get("total_requests", 0) > 0, f"total={mb.get('total_requests')}")

        # ---------- 2. 项目 + AI 端点（mock 路径） ----------
        r = client.post("/api/v1/projects", json={"title": "P3验证项目"}, headers=headers)
        project_id = r.json()["id"]
        check("创建项目", r.status_code in (200, 201), f"id={project_id}")

        # 剧本 AI 生成（配额内）
        r = client.post(
            f"/api/v1/projects/{project_id}/script/ai-generate",
            json={"prompt": "测试剧本生成"},
            headers=headers,
        )
        check("剧本 AI 生成（mock）", r.status_code == 200, f"status={r.status_code}")

        # 无场景生成分镜 → 400
        r = client.post(
            f"/api/v1/projects/{project_id}/storyboard/generate-from-script",
            headers=headers,
        )
        check("无场景生成分镜 → 400", r.status_code == 400, f"status={r.status_code}")

        # ---------- 3. 配额压测（进程内改小额度，独立用户避免前置消耗干扰） ----------
        settings.AI_DAILY_QUOTA = 2
        token2, _ = new_user(client)
        headers2 = auth_headers(token2)
        r = client.post("/api/v1/projects", json={"title": "P3配额压测项目"}, headers=headers2)
        pid2 = r.json()["id"]
        # 消耗第 1 次
        r1 = client.post(
            f"/api/v1/projects/{pid2}/script/ai-generate",
            json={"prompt": "配额测试1"},
            headers=headers2,
        )
        # 消耗第 2 次
        r2 = client.post(
            f"/api/v1/projects/{pid2}/script/ai-generate",
            json={"prompt": "配额测试2"},
            headers=headers2,
        )
        # 第 3 次应 429
        r3 = client.post(
            f"/api/v1/projects/{pid2}/script/ai-generate",
            json={"prompt": "配额测试3"},
            headers=headers2,
        )
        check("配额内调用正常", r1.status_code == 200 and r2.status_code == 200,
              f"r1={r1.status_code} r2={r2.status_code}")
        check("超配额返回 429", r3.status_code == 429, f"r3={r3.status_code}")
        check("429 提示含上限", "上限" in r3.json().get("detail", ""), r3.json().get("detail", "")[:30])
        client.delete(f"/api/v1/projects/{pid2}", headers=headers2)
        settings.AI_DAILY_QUOTA = 100  # 恢复

        # ---------- 4. 多模型路由单测 ----------
        from app.services.ai_service import ai_service

        # 4.1 两个无效 provider → 全部失败 → generate_script 降级 mock
        settings.AI_TEXT_PROVIDERS_RAW = (
            '[{"name":"ghost1","base":"http://127.0.0.1:1/v1","model":"m1","api_key":"k1"},'
            '{"name":"ghost2","base":"http://127.0.0.1:1/v1","model":"m2","api_key":"k2"}]'
        )
        text = __import__("asyncio").run(ai_service.generate_script("路由测试"))
        check("全部 provider 失败 → 降级 mock", "AI自动生成" in text, "")

        # 4.2 第一个 provider 无 key → 跳过 → 第二个有效（用假 base 快速失败）→ 仍失败降级
        settings.AI_TEXT_PROVIDERS_RAW = (
            '[{"name":"nokey","base":"http://127.0.0.1:9/v1","model":"m1","api_key":""},'
            '{"name":"ghost","base":"http://127.0.0.1:1/v1","model":"m2","api_key":"k2"}]'
        )
        text2 = __import__("asyncio").run(ai_service.generate_script("路由跳过测试"))
        check("无 key provider 被跳过", "AI自动生成" in text2, "")

        # 4.3 provider 链可配置性（配置 JSON 数组被正确解析）
        pv = settings.AI_TEXT_PROVIDERS
        check("provider 链来自 RAW 配置", len(pv) == 2 and pv[0]["name"] == "nokey", f"len={len(pv)}")
        settings.AI_TEXT_PROVIDERS_RAW = ""  # 恢复默认（agnes）

        # ---------- 4.4 调度清单端点（GET /ai/providers） ----------
        # 临时配置 Key 便于验证清单展示（不真实调用）
        settings.AGNES_API_KEY = "test-key-for-listing"
        rp = client.get("/api/v1/ai/providers", headers=headers)
        rpb = rp.json()
        settings.AGNES_API_KEY = ""  # 恢复
        check("调度清单端点 200", rp.status_code == 200, f"status={rp.status_code}")
        check("清单含三类 provider", {"text", "image", "video"} <= set(rpb.get("providers", {}).keys()), "")
        text_items = rpb.get("providers", {}).get("text", [])
        check("文本链含已配置的 agnes", len(text_items) >= 1 and text_items[0]["name"] == "agnes",
              f"chain={[i['name'] for i in text_items]}")
        check("清单不泄露 Key", all("api_key" not in i for i in text_items), "")
        check("清单含冷却状态字段", all("cooling" in i and "configured" in i for i in text_items), "")

        # ---------- 4.5 熔断逻辑单测 ----------
        for _ in range(settings.AI_PROVIDER_FAILURE_THRESHOLD):
            ai_service._report_failure("text", "ghost")
        check("连续失败达阈值进入冷却", ai_service._is_cooling("text", "ghost"), "")
        ai_service._report_success("text", "ghost")
        check("成功一次解除冷却", not ai_service._is_cooling("text", "ghost"), "")
        settings.AI_TEXT_PROVIDERS_RAW = '[{"name":"cooldown1","base":"http://127.0.0.1:1/v1","model":"m","api_key":"k"}]'
        for _ in range(settings.AI_PROVIDER_FAILURE_THRESHOLD):
            ai_service._report_failure("text", "cooldown1")
        ok_cooled = ai_service._is_cooling("text", "cooldown1")
        text3 = __import__("asyncio").run(ai_service.generate_script("冷却跳过测试"))
        check("冷却 provider 被跳过并快速降级", ok_cooled and "AI自动生成" in text3, "")
        settings.AI_TEXT_PROVIDERS_RAW = ""  # 恢复默认

        # ---------- 5. 清理 ----------
        r = client.delete(f"/api/v1/projects/{project_id}", headers=headers)
        check("清理项目", r.status_code in (200, 204), f"status={r.status_code}")

    print(f"\n===== P3 结果 =====\n通过: {PASS}  失败: {FAIL}")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
