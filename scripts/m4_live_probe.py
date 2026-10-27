#!/usr/bin/env python
"""M4-0 真实供应商打通探针（key-gated，绝不造假）。

这个脚本存在的唯一目的：把"未验证"变成"已验证"。它**只打真实 provider**，
没有 mock 分支、没有降级路径、没有"假设 provider 会这样回"。

退出码
  0  请求到的所有 shot 都拿到可判定结果（含"能力不支持"这种明确结论）
  2  BLOCKED：没有 API Key（此时不花一分钱，也不假装跑过）
  3  有 shot 出现无法判定 / 契约不符（响应无法解释）

用法
  python scripts/m4_live_probe.py                 # 只跑免费/极便宜的 shot（s0,s1,s2,s4）
  python scripts/m4_live_probe.py --shots all --yes-spend
  python scripts/m4_live_probe.py --shots s3 --image-mode datauri --yes-spend
  python scripts/m4_live_probe.py --report M4-0-实测结果.md

设计约束（不要在后续维护里"优化"掉）
  1) 没有 key 直接退出 2，不产出任何"结论"；
  2) 视频类 shot 必须显式 --yes-spend，因为每一次都是真金白银；
  3) 报错原文一律保留（脱敏后），把 provider 的拒绝理由当成结论的一部分；
  4) 成本只在 provider 真的回了计量字段时才记数字，否则写 UNKNOWN（不许拍单价）。
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "backend" / "data" / "m4_live"
MASKED = "***"


# ---------------------------------------------------------------- env / 配置
def load_env(path: Path) -> dict:
    """手写 .env 解析，避免为跑一个探针去导 pydantic settings。"""
    data = {}
    if not path.exists():
        return data
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        data[k.strip()] = v
    return data


def ffmpeg_exe() -> str:
    """本机没有系统级 ffmpeg，后端一直是靠 imageio-ffmpeg 提供的二进制。"""
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    env = load_env(ROOT / ".env").get("FFMPEG_PATH", "")
    if env and Path(env).exists():
        return env
    found = shutil.which("ffmpeg")
    if found:
        return found
    raise SystemExit("找不到 ffmpeg：请 pip install imageio-ffmpeg 或在 .env 里配 FFMPEG_PATH")


def make_reference_png(path: Path) -> Path:
    """造一张本地首帧图（免费，不用花 provider 的钱）。"""
    subprocess.run(
        [ffmpeg_exe(), "-y", "-f", "lavfi", "-i",
         "color=c=0x203040:s=512x512:d=1", "-frames:v", "1", str(path)],
        check=True, capture_output=True,
    )
    return path


def redact(text: str, key: str, limit: int = 1500) -> str:
    if key:
        text = text.replace(key, MASKED)
    text = re.sub(r"(sk-|ghp_)[A-Za-z0-9_\-]{6,}", MASKED, text)
    return text[:limit]


# ---------------------------------------------------------------- HTTP 记录
class Probe:
    def __init__(self, key: str, base: str, shots: list, yes_spend: bool,
                 image_mode: str, public_image_url: str, timeout: float, out: Path):
        self.key = key
        self.base = base.rstrip("/")
        self.shots = shots
        self.yes_spend = yes_spend
        self.image_mode = image_mode
        self.public_image_url = public_image_url
        self.timeout = timeout
        self.out = out
        self.results = []
        self.client = None
        self.png = None

    def auth(self) -> dict:
        return {"Authorization": f"Bearer {self.key}"}

    def record(self, shot: str, name: str, verdict: str, evidence: dict):
        row = {
            "shot": shot,
            "case": name,
            "verdict": verdict,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            **evidence,
        }
        self.results.append(row)
        tag = {"ok": "OK", "unsupported": "UNSUPPORTED", "failed": "FAILED",
               "unknown": "UNKNOWN"}.get(verdict, verdict)
        ms = evidence.get("latency_ms")
        print(f"  [{tag}] {shot}/{name}" + (f" {ms}ms" if ms else ""))
        return row

    # ---------------- 各 shot
    def shot_chat(self):
        payload = {
            "model": self.text_model,
            "messages": [{"role": "user", "content": "只回四个字：管道通畅"}],
            "max_tokens": 32,
            "temperature": 0,
        }
        t0 = time.time()
        r = self.client.post(f"{self.base}/chat/completions",
                             headers=self.auth(), json=payload, timeout=60)
        ms = int((time.time() - t0) * 1000)
        body = r.text
        content = ""
        usage = None
        model_echo = None
        try:
            data = r.json()
            usage = data.get("usage")
            model_echo = data.get("model")
            content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
        except Exception:
            pass
        verdict = "ok" if r.status_code == 200 and content else (
            "unknown" if r.status_code == 200 else "failed")
        return self.record("s0", "chat", verdict, {
            "http": r.status_code, "latency_ms": ms, "model_echo": model_echo,
            "content": (content or "")[:80], "usage": usage,
            "error_body": "" if r.status_code == 200 else redact(body, self.key),
        })

    def shot_image_gen(self):
        payload = {"model": self.image_model, "prompt":
                   "anime still, a young woman standing on a rooftop at dusk, cinematic, 9:16",
                   "n": 1, "size": "1024x1024", "response_format": "url"}
        t0 = time.time()
        r = self.client.post(f"{self.base}/images/generations",
                             headers=self.auth(), json=payload, timeout=300)
        ms = int((time.time() - t0) * 1000)
        data = None
        try:
            data = r.json()
        except Exception:
            pass
        url = ""
        if isinstance(data, dict):
            items = data.get("data") or data.get("images") or []
            if items and isinstance(items[0], dict):
                url = items[0].get("url") or ""
                if not url and items[0].get("b64_json"):
                    url = "b64_json"
        ok = bool(url)
        saved = ""
        dims = ""
        if url.startswith("http"):
            image_path = self.out / "s1_image.png"
            rr = self.client.get(url, timeout=180)
            image_path.write_bytes(rr.content)
            saved = str(image_path)
            dims = media_info(image_path).get("dims", "unknown")
        if ok:
            verdict = "ok"
        elif r.status_code == 200:
            verdict = "unknown"
        else:
            verdict = "failed"
        return self.record("s1", "text2image", verdict, {
            "http": r.status_code, "latency_ms": ms, "url_kind":
            ("http" if url.startswith("http") else url or "none"),
            "saved": saved, "dims": dims, "usage": (data or {}).get("usage"),
            "error_body": "" if r.status_code == 200 else redact(r.text, self.key),
        })

    def shot_image_edit(self):
        """B1：锁脸能力（/images/edits，多部件上传参考图）。"""
        img = self.png or make_reference_png(self.out / "ref.png")
        data = {"model": self.image_model, "prompt":
                "keep the same face, change background to rainy neon street, cinematic",
                "n": "1", "size": "1024x1024", "response_format": "url"}
        t0 = time.time()
        with img.open("rb") as fh:
            r = self.client.post(f"{self.base}/images/edits",
                                 headers=self.auth(), data=data,
                                 files={"image": ("ref.png", fh, "image/png")},
                                 timeout=300)
        ms = int((time.time() - t0) * 1000)
        data_json = None
        try:
            data_json = r.json()
        except Exception:
            pass
        url = ""
        if isinstance(data_json, dict):
            items = data_json.get("data") or []
            if items and isinstance(items[0], dict):
                url = items[0].get("url") or ("b64_json" if items[0].get("b64_json") else "")
        if r.status_code in (400, 404, 405, 415, 422, 501) and not url:
            verdict = "unsupported"
        elif url:
            verdict = "ok"
        elif r.status_code == 200:
            verdict = "unknown"
        else:
            verdict = "failed"
        return self.record("s2", "image_edit_lockface", verdict, {
            "http": r.status_code, "latency_ms": ms, "url_kind":
            ("http" if url.startswith("http") else url or "none"),
            "error_body": "" if url else redact(r.text, self.key),
        })

    def shot_tts(self):
        """C1：TTS 是否同账号可用（OpenAI 兼容 /audio/speech）。"""
        payload = {"model": "tts-1", "input": "别走。", "voice": "alloy",
                   "response_format": "mp3"}
        t0 = time.time()
        r = self.client.post(f"{self.base}/audio/speech",
                             headers=self.auth(), json=payload, timeout=180)
        ms = int((time.time() - t0) * 1000)
        ctype = r.headers.get("content-type", "")
        audio_ok = r.status_code == 200 and ("audio" in ctype or len(r.content) > 2000)
        saved = ""
        if audio_ok:
            p = self.out / "s4_tts.mp3"
            p.write_bytes(r.content)
            saved = str(p)
        if audio_ok:
            verdict = "ok"
        elif r.status_code in (400, 404, 405, 415, 422, 501):
            verdict = "unsupported"
        else:
            verdict = "failed"
        return self.record("s4", "tts", verdict, {
            "http": r.status_code, "latency_ms": ms, "content_type": ctype,
            "bytes": len(r.content), "saved": saved,
            "error_body": "" if audio_ok else redact(r.text, self.key),
        })

    def image_argument(self) -> tuple:
        """A1 的关键：provider 到底吃不吃什么形态的首帧图。"""
        if self.image_mode == "datauri":
            b = (self.png or make_reference_png(self.out / "ref.png")).read_bytes()
            return "data:image/png;base64," + base64.b64encode(b).decode(), "datauri"
        if self.image_mode == "public":
            return self.public_image_url, "public_url"
        return "/uploads/ai/frames/probe.png", "relative_path"

    def shot_video(self):
        """A1：图生视频。三种 image 形态各打一次，判定"能不能画面对得上图"。"""
        image_value, mode = self.image_argument()
        payload = {
            "model": self.video_model,
            "prompt": "anime cinematic shot, the same young woman turns her head slowly, rain",
            "num_frames": 81,
            "frame_rate": 24,
        }
        if image_value:
            payload["image"] = image_value
        t0 = time.time()
        r = self.client.post(f"{self.base}/videos", headers=self.auth(),
                             json=payload, timeout=120)
        ms = int((time.time() - t0) * 1000)
        data = None
        try:
            data = r.json()
        except Exception:
            pass
        task_id = ""
        if isinstance(data, dict):
            task_id = str(data.get("id") or data.get("task_id") or "")
        if not task_id:
            verdict = ("unsupported"
                       if r.status_code in (400, 415, 422) else "failed")
            return self.record("s3", f"video_submit[{mode}]", verdict, {
                "http": r.status_code, "latency_ms": ms,
                "error_body": redact(r.text, self.key),
                "note": "提交未拿到 task_id",
            })

        submitted_at = time.time()
        video_url = ""
        status = ""
        polls = 0
        while time.time() - submitted_at < self.timeout:
            polls += 1
            time.sleep(5)
            pr = self.client.get(f"{self.base}/videos/{task_id}",
                                 headers=self.auth(), timeout=60)
            try:
                pdata = pr.json()
            except Exception:
                pdata = {}
            status = str((pdata or {}).get("status") or "").lower()
            if status in ("completed", "succeeded", "success"):
                video_url = str((pdata or {}).get("video_url") or "")
                break
            if status in ("failed", "error", "cancelled"):
                break
        total_ms = int((time.time() - submitted_at) * 1000)
        saved = ""
        media = {}
        if video_url.startswith("http"):
            p = self.out / f"s3_video[{mode}].mp4"
            rr = self.client.get(video_url, timeout=300)
            p.write_bytes(rr.content)
            saved = str(p)
            media = media_info(p)
        if video_url:
            verdict = "ok"
        elif status in ("failed", "error"):
            verdict = "failed"
        else:
            verdict = "unknown"
        return self.record("s3", f"video_submit[{mode}]", verdict, {
            "http": r.status_code, "latency_ms": ms, "task_id": task_id,
            "final_status": status, "polls": polls, "poll_total_ms": total_ms,
            "video_url": ("http" if video_url.startswith("http") else (video_url or "none")),
            "saved": saved, "media": media,
        })

    # ---------------- 主流程
    def run(self) -> int:
        import httpx

        self.out.mkdir(parents=True, exist_ok=True)
        self.text_model = self.env.get("AGNES_TEXT_MODEL", "agnes-2.0-flash")
        self.image_model = self.env.get("AGNES_IMAGE_MODEL", "agnes-image-2.1-flash")
        self.video_model = self.env.get("AGNES_VIDEO_MODEL", "agnes-video-v2.0")
        self.client = httpx.Client(timeout=httpx.Timeout(300.0), follow_redirects=True)
        self.png = make_reference_png(self.out / "ref.png")

        print(f"provider base = {self.base}")
        print(f"models        = {self.text_model} / {self.image_model} / {self.video_model}")
        print(f"key           = {self.key[:4]}{MASKED} (len={len(self.key)})")
        print(f"artifacts     = {self.out}")
        print("")

        plan = {
            "s0": self.shot_chat,
            "s1": self.shot_image_gen,
            "s2": self.shot_image_edit,
            "s4": self.shot_tts,
            "s3": self.shot_video,
        }
        wants_money = "s3" in self.shots or "all" in self.shots
        if wants_money and not self.yes_spend:
            print("拒绝执行 s3：图生视频是付费调用，必须显式 --yes-spend。")
            return 1
        for name in ("s0", "s1", "s2", "s4", "s3"):
            if not ("all" in self.shots or name in self.shots):
                continue
            try:
                plan[name]()
            except Exception as e:  # noqa: BLE001 - 探针要记录异常而不是崩
                self.record(name, "exception", "failed",
                            {"error_body": redact(f"{type(e).__name__}: {e}", self.key)})
        self.client.close()
        return 0 if self.write_report() else 3

    def write_report(self) -> bool:
        bad = [r for r in self.results if r["verdict"] in ("failed", "unknown")]
        payload = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "base": self.base,
            "image_mode": self.image_mode,
            "results": self.results,
        }
        jp = self.out / "probe_result.json"
        jp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print("")
        for r in self.results:
            print(f"  {r['shot']:3s} {r['case']:28s} {r['verdict']}")
        print("")
        print(f"JSON -> {jp}")
        return not bad


DIM_RE = re.compile(r"(\d{2,5})x(\d{2,5})")
DUR_RE = re.compile(r"Duration: (\d+):(\d+):(\d+\.\d+)")
FPS_RE = re.compile(r"([\d.]+) fps")


def media_info(path: Path) -> dict:
    """没有 ffprobe，就用 ffmpeg -i 的 stderr 解析（够用且不引入新依赖）。"""
    try:
        err = subprocess.run([ffmpeg_exe(), "-hide_banner", "-i", str(path)],
                             capture_output=True, text=True).stderr
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}
    info = {"bytes": path.stat().st_size if path.exists() else 0}
    m = DIM_RE.search(err)
    if m:
        info["dims"] = f"{m.group(1)}x{m.group(2)}"
    m = DUR_RE.search(err)
    if m:
        info["duration_s"] = round(
            int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)), 3)
    m = FPS_RE.search(err)
    if m:
        info["fps"] = m.group(1)
    if "Audio:" in err:
        info["audio"] = True
    return info


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default="s0,s1,s2,s4",
                    help="逗号分隔：s0 chat / s1 text2image / s2 image_edit / s3 video / s4 tts / all")
    ap.add_argument("--yes-spend", action="store_true", help="允许付费的视频生成调用")
    ap.add_argument("--image-mode", default="relative_path",
                    choices=["relative_path", "public", "datauri"],
                    help="图生视频时传给 provider 的首帧图形态（用于验证 A1 到底吃哪种）")
    ap.add_argument("--public-image-url", default="", help="image-mode=public 时使用的公网图片地址")
    ap.add_argument("--timeout", type=float, default=900.0, help="单条视频轮询上限（秒）")
    args = ap.parse_args()

    env = load_env(ROOT / ".env")
    key = (env.get("AGNES_API_KEY") or os.environ.get("AGNES_API_KEY") or "").strip()
    base = (env.get("AGNES_API_BASE") or os.environ.get("AGNES_API_BASE")
            or "https://apihub.agnes-ai.com/v1")

    shots = [s.strip() for s in args.shots.split(",") if s.strip()]
    if "all" in shots:
        shots = ["s0", "s1", "s2", "s3", "s4"]

    if not key or key.lower() in ("", "empty", "none", "changeme"):
        print("=" * 72)
        print("BLOCKED：AGNES_API_KEY 为空，M4-0 无法取证。")
        print("")
        print("这里不会启动任何 mock 来冒充 provider —— 假设备跑出的数字")
        print("对单条镜头真实成本 / 真实延迟 / 画面对不对得上图，零证据价值。")
        print("")
        print("解法（二选一）：")
        print(f"  1) 把 key 写进 {ROOT / '.env'} 的 AGNES_API_KEY= 后面（等号后不要空格）")
        print("  2) 或临时：set AGNES_API_KEY=sk-xxx 然后重跑本脚本")
        print("")
        print("拿到 key 后依次执行（约 10 分钟 + 视频生成等待）：")
        print("  python scripts/m4_live_probe.py                  # 免费档：chat/出图/锁脸/TTS")
        print("  python scripts/m4_live_probe.py --shots s3 --image-mode datauri --yes-spend")
        print("  python scripts/m4_live_probe.py --shots s3 --image-mode public --public-image-url https://... --yes-spend")
        print("=" * 72)
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = OUT_DIR / stamp
    probe = Probe(key=key, base=base, shots=shots, yes_spend=args.yes_spend,
                  image_mode=args.image_mode, public_image_url=args.public_image_url,
                  timeout=args.timeout, out=out)
    probe.env = env
    return probe.run()


if __name__ == "__main__":
    sys.exit(main())
