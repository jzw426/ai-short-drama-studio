"""M3-1 真实全栈 E2E：容器化后端 + PostgreSQL + Redis + 私有 MinIO。

纯 HTTP 黑盒：不碰数据库、不改容器内部状态，只从宿主机调用公开接口。
用法（先起栈）：
  docker compose -f docker-compose.yml -f docker-compose.e2e.yml -p aidrama-e2e up -d --build postgres redis minio backend celery-worker
  backend/venv/Scripts/python.exe scripts/verify_m3_stack_e2e.py
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx


def log(msg: str) -> None:
    print(f"[stack-e2e] {msg}", flush=True)


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def ffprobe_exe() -> str:
    candidate = Path(ffmpeg_exe()).with_name("ffprobe.exe")
    if candidate.exists():
        return str(candidate)
    return "ffprobe"


def make_clip(path: Path, color: str, seconds: float = 2.0) -> None:
    cmd = [
        ffmpeg_exe(), "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s=640x360:d={seconds}",
        "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path),
    ]
    subprocess.run(cmd, check=True)


def probe(path: Path) -> str:
    """返回可断言的流信息文本。

    宿主机通常只有 imageio-ffmpeg 自带的 ffmpeg（无 ffprobe 兄弟文件），
    所以 ffprobe 不可用时退回 `ffmpeg -i`：它把流信息打在 stderr 上，
    同样包含 "1080x1920"、"Audio:"、"Subtitle: mov_text" 这些断言目标。
    """
    try:
        out = subprocess.run(
            [ffprobe_exe(), "-v", "error", "-show_streams", "-show_format", str(path)],
            capture_output=True, check=False,
        )
        text = (out.stdout or b"").decode("utf-8", "ignore")
        if text.strip():
            return text
    except FileNotFoundError:
        pass
    out = subprocess.run(
        [ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True, check=False,
    )
    return (out.stderr or b"").decode("utf-8", "ignore")


def wait_health(client: httpx.Client, timeout: float) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        try:
            r = client.get("/health", timeout=5)
            last = r.text[:200]
            if r.status_code == 200:
                body = r.json()
                if body.get("status") == "healthy":
                    return body
        except Exception as exc:  # noqa: BLE001 - 等服务起来就是这样
            last = repr(exc)
        time.sleep(3)
    raise RuntimeError(f"服务未就绪: {last}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="http://127.0.0.1:8000/api/v1")
    parser.add_argument("--timeout", type=float, default=420.0)
    args = parser.parse_args()

    suffix = uuid.uuid4().hex[:8]
    username = f"m3_{suffix}"
    password = "M3Stack!Passw0rd"
    tmp = Path(tempfile.mkdtemp(prefix="m3-stack-"))

    with httpx.Client(base_url=args.api, timeout=60, follow_redirects=True) as client:
        health = wait_health(client, args.timeout)
        log(f"health: {json.dumps(health, ensure_ascii=False)}")
        assert health.get("version"), "health 缺少 version 字段"
        for key in ("path", "free_bytes"):
            assert key not in json.dumps(health), f"公开 /health 泄露了内部字段 {key}"

        anon_metrics = httpx.get(f"{args.api}/metrics", timeout=10)
        assert anon_metrics.status_code == 401, f"/metrics 匿名应为 401，实际 {anon_metrics.status_code}"
        log("匿名 /metrics 被拒 [OK]")

        r = client.post("/auth/register", json={
            "username": username, "email": f"{username}@example.com",
            "password": password, "display_name": "M3 Stack E2E",
        })
        assert r.status_code == 201, f"注册失败 {r.status_code}: {r.text[:300]}"
        r = client.post("/auth/login", json={"username": username, "password": password})
        assert r.status_code == 200, f"登录失败 {r.status_code}: {r.text[:300]}"
        log(f"注册并登录 {username} [OK]")

        r = client.post("/projects", json={"title": f"M3 全栈 {suffix}", "description": ""})
        assert r.status_code == 201, r.text[:300]
        project_id = r.json()["id"]
        log(f"项目 {project_id} [OK]")

        seg1 = tmp / "seg1.mp4"
        seg2 = tmp / "seg2.mp4"
        make_clip(seg1, "navy")
        make_clip(seg2, "darkgreen")
        uploaded = []
        for clip in (seg1, seg2):
            with clip.open("rb") as fh:
                r = client.post(
                    f"/projects/{project_id}/assets/upload",
                    files={"file": (clip.name, fh, "video/mp4")},
                    data={"tags": "e2e"},
                )
            assert r.status_code == 201, f"上传失败 {r.status_code}: {r.text[:400]}"
            body = r.json()
            assert body.get("canonical_url"), f"素材缺少 canonical_url: {body}"
            assert "localhost:9000" in body["url"], f"MinIO 模式下应返回 MinIO 预签名地址: {body['url'][:160]}"
            uploaded.append(body)
        log(f"上传 2 个素材到私有 MinIO [OK]")

        # 用签名的公开地址去掉 query：不带签名直接打 MinIO 对象 URL，必须被拒
        object_url = uploaded[0]["url"].split("?")[0]
        anon = httpx.get(object_url, timeout=15)
        assert anon.status_code in (401, 403), f"私有桶匿名读取应为 401/403，实际 {anon.status_code}"
        log("私有桶匿名读素材被拒 [OK]")

        r = client.put(f"/projects/{project_id}/script", json={"title": "第一集", "content": "雨夜街角，她转身。"})
        assert r.status_code == 200, r.text[:300]
        r = client.post(f"/projects/{project_id}/script/scenes", json={
            "scene_number": 1, "title": "雨夜街角", "dialogue": "别走。", "duration": 2, "sort_order": 0,
        })
        assert r.status_code == 201, r.text[:300]
        log("剧本 + 场景台词 [OK]")

        for idx, asset in enumerate(uploaded, start=1):
            r = client.post(f"/projects/{project_id}/storyboard/shots", json={
                "shot_number": idx, "label": f"镜头{idx}",
                "description": f"第 {idx} 镜 雨夜街道",
                "duration": 2.0, "scene_ref": "#1",
                "video_url": asset["canonical_url"], "sort_order": idx,
            })
            assert r.status_code == 201, f"建镜头失败 {r.status_code}: {r.text[:300]}"
        log("2 个镜头绑定素材 [OK]")

        key = f"m3-{suffix}"
        payload = {
            "name": "M3 全栈渲染",
            "config": {
                "resolution": "1080x1920", "aspect_ratio": "9:16", "fps": 30,
                "quality": "medium", "subtitle_source": "dialogue",
            },
            "idempotency_key": key,
        }
        r = client.post(f"/projects/{project_id}/render", json=payload)
        assert r.status_code in (200, 201), f"提交渲染失败 {r.status_code}: {r.text[:400]}"
        task_id = r.json()["id"]
        r2 = client.post(f"/projects/{project_id}/render", json=payload)
        assert r2.status_code == 200, f"幂等重复提交应 200，实际 {r2.status_code}"
        assert r2.json()["id"] == task_id, "幂等重复提交返回了不同任务"
        log(f"提交渲染 {task_id}，幂等去重 [OK]")

        deadline = time.time() + args.timeout
        status = {}
        while time.time() < deadline:
            status = client.get(f"/render/{task_id}/status").json()
            if status.get("status") in ("completed", "failed", "cancelled"):
                break
            time.sleep(3)
        assert status.get("status") == "completed", f"渲染未完成: {json.dumps(status, ensure_ascii=False)[:600]}"
        log("渲染完成 [OK]")

        # 字幕文件：硬字幕任务也必须单独落一份 srt 并可下载（M3-3）
        subtitle_url = status.get("subtitle_url")
        assert subtitle_url, f"状态响应缺少 subtitle_url: {json.dumps(status, ensure_ascii=False)[:400]}"
        assert "/subtitle.srt" in subtitle_url, f"字幕地址不指向 subtitle.srt: {subtitle_url[:200]}"
        srt = httpx.get(subtitle_url, timeout=30)
        assert srt.status_code == 200, f"字幕下载失败 {srt.status_code}"
        srt_text = srt.text
        assert "-->" in srt_text and "别走" in srt_text, f"字幕内容异常: {srt_text[:200]}"
        log(f"字幕 srt 可下载且包含台词（{len(srt_text)} 字符）[OK]")

        r = client.get(f"/render/{task_id}/download")
        assert r.status_code == 200, r.text[:300]
        download_url = r.json()["download_url"]
        assert "localhost:9000" in download_url, f"下载地址不是 MinIO 预签名: {download_url[:160]}"
        assert "X-Amz-Signature" in download_url, f"预签名参数缺失: {download_url[:160]}"
        media = httpx.get(download_url, timeout=120)
        assert media.status_code == 200, f"预签名下载失败 {media.status_code}"
        out = tmp / "output.mp4"
        out.write_bytes(media.content)
        assert out.stat().st_size > 10_000, "成片过小"
        info = probe(out)
        assert "1080x1920" in info, f"成片分辨率不符: {info[-400:]}"
        assert "Audio:" in info, "成片无音轨"
        log(f"成片下载并校验: {out.stat().st_size} bytes, 1080x1920, 带音轨 [OK]")

        r = client.get(f"/render/{task_id}/download")
        bare = r.json()["download_url"].split("?")[0]
        anon = httpx.get(bare, timeout=15)
        assert anon.status_code in (401, 403), f"去掉签名后应 401/403，实际 {anon.status_code}"
        log("成片匿名访问被拒 [OK]")

        # 软字幕模式（M3-3）：同一套镜头再渲一次，成片里应是 mov_text 软轨而不是烧死画面
        soft_payload = {
            "name": "M3 全栈软字幕",
            "config": {
                "resolution": "1080x1920", "aspect_ratio": "9:16", "fps": 30,
                "quality": "medium", "subtitle_source": "dialogue", "subtitle_mode": "soft",
            },
            "idempotency_key": key + "-soft",
        }
        r = client.post(f"/projects/{project_id}/render", json=soft_payload)
        assert r.status_code in (200, 201), f"软字幕任务提交失败 {r.status_code}: {r.text[:300]}"
        soft_id = r.json()["id"]
        soft_status = {}
        deadline = time.time() + args.timeout
        while time.time() < deadline:
            soft_status = client.get(f"/render/{soft_id}/status").json()
            if soft_status.get("status") in ("completed", "failed", "cancelled"):
                break
            time.sleep(3)
        assert soft_status.get("status") == "completed", (
            f"软字幕渲染未完成: {json.dumps(soft_status, ensure_ascii=False)[:600]}"
        )
        soft_dl = client.get(f"/render/{soft_id}/download").json()["download_url"]
        soft_media = httpx.get(soft_dl, timeout=120)
        assert soft_media.status_code == 200, f"软字幕成片下载失败 {soft_media.status_code}"
        soft_out = tmp / "output_soft.mp4"
        soft_out.write_bytes(soft_media.content)
        soft_info = probe(soft_out)
        assert "Subtitle:" in soft_info and "mov_text" in soft_info, (
            f"软字幕成片没有 mov_text 字幕轨: {soft_info[-400:]}"
        )
        log(f"软字幕模式成片含 mov_text 轨（{soft_out.stat().st_size} bytes）[OK]")

        r = client.get("/metrics")
        assert r.status_code == 200, f"登录后 /metrics 应 200，实际 {r.status_code}"
        log("登录后 /metrics 可读 [OK]")

        r = client.get(f"/projects/{project_id}/render/tasks", params={"limit": 1})
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("X-Total-Count") is not None, "渲染列表缺少 X-Total-Count"
        log("渲染列表分页头 [OK]")

    log(f"临时目录 {tmp}（保留 output.mp4 供复检）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
