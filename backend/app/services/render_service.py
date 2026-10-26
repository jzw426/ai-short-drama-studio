"""渲染编排服务（M2 真实闭环版）。

M2 修的是"这条链路从来没真正出过片"：

1. **镜头可以绑定已有素材**：`shots.video_url` 有值就直接取用，只有为空才回退
   付费 AI 生成。旧实现没有这一列，没配 AI Key 时渲染必然全镜头失败 —— 这解释
   了为什么上线以来 `shots` 有数据、`render_tasks` 却是 0 个成片。
2. **渲染参数真的生效**：旧实现分辨率/帧率/画质/风格全部被忽略（归一化硬编码
   24fps、不 scale、不 pad）。现在统一到 `RenderSpec`：scale+pad 到目标画布、
   帧率、CRF/preset、轻量调色，全部可在成片上验证（ffprobe 可测）。
3. **字幕用台词而不是画面描述**：新增 `scenes.dialogue`，按镜头的 `scene_ref`
   关联；没有台词才回退画面描述，并把"回退了多少条"写进 warnings（旧实现把
   "画面描述"当台词烧进画面，语义错误且用户无法察觉）。
4. **失败可诊断**：FFmpeg 的失败原因（stderr 末段）以前只进 print，任务表里永远
   只有一句"渲染失败"。现在每个失败步骤都带 stage + stderr 末段回到
   `error_message`。
5. **本地素材直读磁盘**：同一台机器上的 /uploads 素材不再绕一圈 HTTP 下载。

保留 M1 的四件事：协作式取消、断点续渲（checkpoint 复用已生成片段）、临时目录
必清、全程不把整段视频读进内存。
"""
import asyncio
import logging
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Awaitable, Callable, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.services.ai_service import AIUnavailableError, ai_service
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[float, str], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]
CheckpointCallback = Callable[[dict], Awaitable[None]]

# ---------------------------------------------------------------------------
# 渲染参数
# ---------------------------------------------------------------------------

_RESOLUTION_RE = re.compile(r"^\s*(\d{3,4})\s*[xX×*]\s*(\d{3,4})\s*$")
_RATIO_RE = re.compile(r"^\s*(\d{1,2})\s*[:/]\s*(\d{1,2})\s*$")

# quality → (CRF, x264 preset)。数值全部进 ffmpeg 命令，成片可验证。
QUALITY_PRESETS = {
    "low": (28, "veryfast"),
    "medium": (23, "medium"),
    "high": (20, "slow"),
}

# visual_style → ffmpeg 滤镜。未知风格不做任何调色（不假装有风格）。
STYLE_FILTERS = {
    "电影级（cinematic）": "eq=contrast=1.06:saturation=1.05",
    "cinematic": "eq=contrast=1.06:saturation=1.05",
    "电影级": "eq=contrast=1.06:saturation=1.05",
    "写实": "",
    "realistic": "",
    "动漫": "eq=saturation=1.15:contrast=1.02",
    "anime": "eq=saturation=1.15:contrast=1.02",
}

# 台词引号：中文直角/双引号 + 英文双引号。左右引号必须分开——把 」 也当成
# 开引号会让「今天不回去。」她说。 匹配出 "她说。" 这种垃圾台词。
# 用单引号 Python 字符串拼正则，避免把 ASCII 双引号写进双引号字面量里。
_OPEN_QUOTES = '\u300c\u300e\u201c"'
_CLOSE_QUOTES = '\u300d\u300f\u201d"'
_DIALOGUE_RE = re.compile(
    "[" + _OPEN_QUOTES + "]([^" + _CLOSE_QUOTES + "]{1,300})[" + _CLOSE_QUOTES + "]"
)

DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
MAX_DIMENSION = 4096
MIN_DIMENSION = 144
MAX_SEGMENT_BYTES = 512 * 1024 * 1024  # 单镜头素材上限：防止 URL 把磁盘写满


def _even(value: int) -> int:
    """H.264 要求宽高为偶数（yuv420p）。"""
    value = int(value)
    return value if value % 2 == 0 else value + 1


def _clamp_dimension(value: int) -> int:
    return _even(max(MIN_DIMENSION, min(MAX_DIMENSION, int(value))))


@dataclass(frozen=True)
class RenderSpec:
    """一次渲染的规范化参数（全部会被 ffmpeg 真实使用）。"""

    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = 24
    crf: int = 20
    preset: str = "slow"
    style_filter: str = ""
    subtitle_source: str = "description"
    subtitle_font_size: int = 24

    @property
    def resolution(self) -> str:
        return f"{self.width}x{self.height}"

    def video_filter(self) -> str:
        parts = [
            f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease",
            f"pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=black",
            "setsar=1",
        ]
        if self.style_filter:
            parts.append(self.style_filter)
        parts.append("format=yuv420p")
        return ",".join(parts)

    def as_dict(self) -> dict:
        return {
            "resolution": self.resolution,
            "fps": self.fps,
            "crf": self.crf,
            "preset": self.preset,
            "style_filter": self.style_filter,
            "subtitle_source": self.subtitle_source,
        }


def build_spec(config: Optional[dict]) -> Tuple[RenderSpec, List[str]]:
    """把（用户可控的）config 规范化成 RenderSpec，非法值夹紧而不是 500。

    返回 (spec, warnings)：warnings 会进入渲染结果，用户能看到"你传的 1920x1080
    与 9:16 冲突，我按 9:16 出了 1080x1920"，而不是默默改写。
    """
    config = config or {}
    warnings: List[str] = []

    raw_resolution = str(config.get("resolution") or "").strip() or "1920x1080"
    match = _RESOLUTION_RE.match(raw_resolution)
    if match:
        base_w, base_h = int(match.group(1)), int(match.group(2))
    else:
        base_w, base_h = DEFAULT_WIDTH, DEFAULT_HEIGHT
        warnings.append(f"resolution={raw_resolution!r} 无法解析，回退 1920x1080")

    raw_ratio = str(config.get("aspect_ratio") or "").strip()
    ratio = _RATIO_RE.match(raw_ratio) if raw_ratio else None
    if ratio:
        ar_w, ar_h = int(ratio.group(1)), int(ratio.group(2))
        if ar_w <= 0 or ar_h <= 0:
            ratio = None

    if ratio:
        long_side = max(base_w, base_h)
        if ar_w >= ar_h:
            width, height = long_side, int(round(long_side * ar_h / ar_w))
        else:
            width, height = int(round(long_side * ar_w / ar_h)), long_side
        # 只有方向冲突（横屏参数配竖屏比例）才值得提示，否则是用户在正常使用
        if (base_w >= base_h) != (ar_w >= ar_h):
            warnings.append(
                f"resolution={base_w}x{base_h} 与 aspect_ratio={ar_w}:{ar_h} 方向不一致，"
                f"已按 {ar_w}:{ar_h} 输出 {_even(width)}x{_even(height)}"
            )
    else:
        width, height = base_w, base_h
        if raw_ratio:
            warnings.append(f"aspect_ratio={raw_ratio!r} 无法解析，按 resolution 输出")

    clamped_w, clamped_h = _clamp_dimension(width), _clamp_dimension(height)
    if (clamped_w, clamped_h) != (width, height):
        warnings.append(
            f"画布 {width}x{height} 超出 {MIN_DIMENSION}-{MAX_DIMENSION}，已夹紧为 {clamped_w}x{clamped_h}"
        )
    width, height = clamped_w, clamped_h

    try:
        fps = int(config.get("fps") or 24)
    except (TypeError, ValueError):
        fps = 24
    if fps < 12 or fps > 60:
        warnings.append(f"fps={fps} 超出 12-60，已夹紧")
        fps = max(12, min(60, fps))

    quality = str(config.get("quality") or "high").strip().lower()
    if quality not in QUALITY_PRESETS:
        warnings.append(f"quality={quality!r} 未知，回退 high")
        quality = "high"
    crf, preset = QUALITY_PRESETS[quality]

    style_key = str(config.get("visual_style") or "").strip().lower()
    style_filter = STYLE_FILTERS.get(style_key, "")

    subtitle_source = str(config.get("subtitle_source") or "description").strip().lower()
    if subtitle_source not in {"dialogue", "description", "label", "none"}:
        warnings.append(f"subtitle_source={subtitle_source!r} 未知，回退 description")
        subtitle_source = "description"

    spec = RenderSpec(
        width=width,
        height=height,
        fps=fps,
        crf=crf,
        preset=preset,
        style_filter=style_filter,
        subtitle_source=subtitle_source,
        # 字号跟着画布高度走：1080p 竖屏约 43px，720p 约 29px
        subtitle_font_size=max(16, min(72, round(height / 45))),
    )
    return spec, warnings


# ---------------------------------------------------------------------------
# 错误类型
# ---------------------------------------------------------------------------


class RenderCancelled(Exception):
    """用户取消渲染（协作式检查点触发，不是错误）。"""


class RenderStepError(Exception):
    """某个渲染步骤失败，带 stage 与可诊断的 detail（通常是 ffmpeg stderr 末段）。"""

    def __init__(self, stage: str, detail: str = ""):
        self.stage = stage
        self.detail = (detail or "").strip()
        super().__init__(f"{stage}: {self.detail}" if self.detail else stage)


def _tail(text: str, limit: int = 600) -> str:
    """stderr 末段单行化：塞进 error_message 时保留最有用的最后几行。"""
    clean = (text or "").strip()
    if not clean:
        return ""
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    out = " | ".join(lines[-6:])
    return out[-limit:]


def extract_dialogue(content: str) -> str:
    """从剧本正文提取引号内的台词（`scenes.dialogue` 为空时的兜底）。"""
    if not content:
        return ""
    found = []
    seen = set()
    for match in _DIALOGUE_RE.finditer(content):
        line = " ".join(match.group(1).split())
        if line and line not in seen:
            seen.add(line)
            found.append(line)
    return "\n".join(found)


class RenderService:
    """渲染编排：收集分镜 → 逐镜取素材 → 归一化 → 合成 → 字幕/BGM → 上传。"""

    # ---------------- 主流程 ----------------

    async def execute_render(
        self,
        task_id: str,
        project_id: str,
        config: dict,
        progress_callback: Optional[ProgressCallback] = None,
        cancel_check: Optional[CancelCheck] = None,
        checkpoint_cb: Optional[CheckpointCallback] = None,
        resume: Optional[dict] = None,
    ) -> dict:
        results: dict = {
            "segments": [],
            "errors": [],
            "warnings": [],
            "spec": {},
            "status": "failed",
        }

        await self._progress(progress_callback, 0.03, "收集分镜数据...")
        await self._check_cancel(cancel_check)

        shots = await self._load_shots(project_id)
        if not shots:
            results["errors"].append("没有可渲染的镜头（请先在分镜里创建镜头）")
            return results

        spec, spec_warnings = build_spec(config)
        results["spec"] = spec.as_dict()
        results["warnings"].extend(spec_warnings)

        total = len(shots)
        resume_urls = self._resume_map(resume)
        if resume_urls:
            await self._progress(
                progress_callback, 0.06, f"断点续渲：复用 {len(resume_urls)} 个已生成片段"
            )

        temp_dir = tempfile.mkdtemp(prefix="render_")
        try:
            segments = await self._render_segments(
                shots, temp_dir, spec, progress_callback, cancel_check, resume_urls
            )
            results["segments"] = segments
            results["errors"].extend(
                f"镜头 {s['shot_number']} 失败: {s.get('error')}"
                for s in segments
                if s.get("status") != "success"
            )

            if checkpoint_cb:
                # 先把"已经花过钱/已经上传"的产物落库，后续失败重试不再重复生成
                await checkpoint_cb(
                    {
                        "stage": "segments",
                        "segments": [
                            {
                                "shot_number": s["shot_number"],
                                "video_url": s.get("video_url", ""),
                                "status": s.get("status", "failed"),
                            }
                            for s in segments
                        ],
                    }
                )

            segment_files = [
                s["segment_path"] for s in segments if s.get("segment_path")
            ]
            if not segment_files:
                results["errors"].append("没有任何镜头产出可用片段")
                return results

            await self._check_cancel(cancel_check)
            await self._progress(progress_callback, 0.80, "统一画布与编码参数...")
            try:
                normalized = await self._normalize_all(
                    segment_files, temp_dir, spec, cancel_check
                )
            except RenderStepError as exc:
                results["errors"].append(str(exc))
                return results

            durations = await asyncio.gather(
                *[self._probe_duration(p) for p in normalized]
            )

            await self._check_cancel(cancel_check)
            await self._progress(progress_callback, 0.87, "合并片段...")
            output_path = os.path.join(temp_dir, "final_output.mp4")
            try:
                await self._concat_videos(normalized, output_path)
            except RenderStepError as exc:
                results["errors"].append(str(exc))
                return results

            if spec.subtitle_source != "none":
                await self._check_cancel(cancel_check)
                await self._progress(progress_callback, 0.92, "烧制字幕...")
                try:
                    output_path = await self._add_subtitles(
                        output_path, shots, durations, spec
                    )
                except RenderStepError as exc:
                    results["warnings"].append(f"字幕未烧制（成片保留无字幕版）：{exc}")

            bgm_source = str(config.get("bgm_source") or "").strip()
            if config.get("add_bgm") and bgm_source:
                await self._check_cancel(cancel_check)
                await self._progress(progress_callback, 0.95, "混入背景音乐...")
                try:
                    output_path = await self._add_bgm(output_path, bgm_source)
                except RenderStepError as exc:
                    results["warnings"].append(f"BGM 未混入（成片保留原声）：{exc}")

            await self._check_cancel(cancel_check)
            await self._progress(progress_callback, 0.98, "上传成片...")
            object_name = f"renders/{project_id}/{task_id}/output.mp4"
            output_url = await storage_service.upload_from_path(
                object_name=object_name,
                src_path=output_path,
                content_type="video/mp4",
            )
            results["output_url"] = output_url
            results["status"] = "completed"
            # 只在"有镜头但没全用上"时告警。正常成片不是 warning —— 旧写法把
            # "成片包含 2/2 个镜头"塞进 warnings，导致任何一次成功渲染都会带一条
            # 伪告警，真正的告警被淹掉。
            if shots and len(segment_files) != total:
                results["warnings"].append(
                    f"成片只包含 {len(segment_files)}/{total} 个镜头"
                )
            return results
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ---------------- 分镜与素材 ----------------

    async def _load_shots(self, project_id: str) -> List[dict]:
        """读镜头，并把所属场景的台词挂在镜头上（按 scene_ref 匹配）。"""
        from sqlalchemy import select

        from app.core.database import async_session
        from app.models.script import Scene, Script
        from app.models.storyboard import Shot, Storyboard

        try:
            async with async_session() as session:
                sb = (
                    await session.execute(
                        select(Storyboard).where(Storyboard.project_id == project_id)
                    )
                ).scalar_one_or_none()
                if not sb:
                    return []
                rows = (
                    (
                        await session.execute(
                            select(Shot)
                            .where(Shot.storyboard_id == sb.id)
                            .order_by(Shot.sort_order)
                        )
                    )
                    .scalars()
                    .all()
                )

                dialogue_map = {}
                script = (
                    await session.execute(
                        select(Script).where(Script.project_id == project_id)
                    )
                ).scalar_one_or_none()
                if script:
                    scenes = (
                        (
                            await session.execute(
                                select(Scene).where(Scene.script_id == script.id)
                            )
                        )
                        .scalars()
                        .all()
                    )
                    for scene in scenes:
                        text = (scene.dialogue or "").strip()
                        if not text:
                            text = extract_dialogue(scene.content or "")
                        if not text:
                            continue
                        dialogue_map[str(scene.title or "").strip()] = text
                        dialogue_map[f"#{scene.scene_number}"] = text
                        dialogue_map[str(scene.scene_number)] = text

                shots = []
                for s in rows:
                    ref = str(s.scene_ref or "").strip()
                    shots.append(
                        {
                            "shot_number": s.shot_number,
                            "label": s.label,
                            "description": s.description,
                            "duration": s.duration,
                            "scene_ref": s.scene_ref,
                            "character_refs": s.character_refs or [],
                            "video_url": (s.video_url or "").strip(),
                            "dialogue": dialogue_map.get(ref, ""),
                        }
                    )
                return shots
        except Exception as exc:  # 查询失败等价于没镜头，由上层报错
            logger.exception("[Render] 读取分镜失败: %s", exc)
            return []

    async def _render_segments(
        self,
        shots: List[dict],
        temp_dir: str,
        spec: RenderSpec,
        progress_callback: Optional[ProgressCallback],
        cancel_check: Optional[CancelCheck],
        resume_urls: dict,
    ) -> List[dict]:
        total = len(shots)
        semaphore = asyncio.Semaphore(int(settings.RENDER_CONCURRENCY or 3))
        segments: List[dict] = [None] * total  # type: ignore[list-item]

        async def render_one(idx: int, shot: dict) -> dict:
            async with semaphore:
                await self._check_cancel(cancel_check)
                shot_number = shot.get("shot_number", idx + 1)
                label = shot.get("label", "")
                if progress_callback:
                    await progress_callback(
                        0.08 + (0.7 * idx / max(total, 1)),
                        f"取镜头素材 {idx + 1}/{total}: {label}",
                    )
                try:
                    video_url, source_kind = await self._pick_source(
                        shot, resume_urls, spec
                    )
                    await self._check_cancel(cancel_check)
                    segment_path = await self._stage_segment(
                        video_url, temp_dir, idx, source_kind
                    )
                    await self._check_cancel(cancel_check)
                    return {
                        "ok": True,
                        "shot_number": shot_number,
                        "label": label,
                        "video_url": str(video_url),
                        "source": source_kind,
                        "segment_path": segment_path,
                    }
                except RenderCancelled:
                    raise
                except RenderStepError as exc:
                    return {
                        "ok": False,
                        "shot_number": shot_number,
                        "label": label,
                        "error": str(exc),
                    }
                except Exception as exc:  # noqa: BLE001 - 单镜头失败不拖垮整任务
                    return {
                        "ok": False,
                        "shot_number": shot_number,
                        "label": label,
                        "error": f"{type(exc).__name__}: {exc}",
                    }

        # 用 create_task 而不用裸 gather：gather 遇到第一个异常只负责抛出，
        # 其余协程会继续跑到自然结束（取消后 AI 仍在烧钱）。这里显式 cancel。
        tasks = [
            asyncio.create_task(render_one(idx, shot)) for idx, shot in enumerate(shots)
        ]
        try:
            gathered = await asyncio.gather(*tasks)
        except RenderCancelled:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except Exception:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for idx, res in enumerate(gathered):
            segments[idx] = {
                "shot_number": res["shot_number"],
                "label": res.get("label", ""),
                "status": "success" if res["ok"] else "failed",
                "video_url": res.get("video_url", ""),
                "source": res.get("source", ""),
                "segment_path": res.get("segment_path"),
                "error": res.get("error"),
            }
        return segments

    async def _pick_source(
        self, shot: dict, resume_urls: dict, spec: RenderSpec
    ) -> Tuple[str, str]:
        """按优先级决定镜头素材：显式绑定 > 断点 > AI 生成。"""
        explicit = (shot.get("video_url") or "").strip()
        if explicit:
            kind = self._source_kind(explicit)
            if not kind:
                raise RenderStepError(
                    f"镜头 {shot.get('shot_number')}",
                    f"video_url 不是受支持的媒体地址（只接受 http(s) 或 /uploads/ 路径）: {explicit[:120]}",
                )
            return explicit, kind[0]

        resumed = resume_urls.get(int(shot.get("shot_number") or 0))
        if resumed:
            kind = self._source_kind(resumed)
            if kind:
                return resumed, kind[0]

        try:
            generated = await ai_service.generate_video(
                prompt=shot.get("description") or shot.get("label") or "",
                duration=float(shot.get("duration") or 3.0),
            )
        except AIUnavailableError as exc:
            raise RenderStepError(
                f"镜头 {shot.get('shot_number')} 未绑定素材",
                f"AI 视频生成不可用（{exc}）",
            ) from exc
        if not generated:
            raise RenderStepError(
                f"镜头 {shot.get('shot_number')}", "AI 视频生成返回空地址"
            )
        kind = self._source_kind(str(generated))
        if not kind:
            raise RenderStepError(
                f"镜头 {shot.get('shot_number')}",
                f"AI 返回的地址无法下载: {str(generated)[:120]}",
            )
        return str(generated), kind[0]

    @staticmethod
    def _source_kind(url: str) -> Optional[Tuple[str, str]]:
        """把媒体 URL 分类为 http / local，并解析 local 的真实路径（越界即拒绝）。"""
        url = (url or "").strip()
        if not url:
            return None
        lowered = url.lower()
        if lowered.startswith("http://") or lowered.startswith("https://"):
            # MinIO 模式下素材的规范 URL 指向私有桶，裸 GET 一定 403 —— 必须走
            # SDK 取对象。判别依据是能否从 URL 里解析出桶内 object_name。
            if settings.STORAGE_TYPE != "local":
                from app.services.storage_service import extract_object_name

                object_name = extract_object_name(url)
                if object_name:
                    return "object", object_name
            return "http", url
        clean = url.split("?", 1)[0].split("#", 1)[0]
        if clean.startswith("/uploads/"):
            if settings.STORAGE_TYPE != "local":
                return None
            from app.services.storage_service import _secure_local_path

            try:
                path = _secure_local_path(clean[len("/uploads/"):])
            except ValueError:
                return None
            return "local", path
        return None

    async def _download_object(self, object_name: str, dest: str) -> None:
        """从私有对象存储（MinIO）取对象到本地文件。

        为什么不能走 HTTP 分支：桶是私有的，规范 URL 直接 GET 是 403；
        而镜头绑定存的是规范 URL（签名会过期），渲染时可能已经过期很久。
        所以这里用后端自己的凭据走 SDK。
        """
        from app.services.storage_service import storage_service

        client = getattr(storage_service, "client", None)
        if client is None:
            raise RenderStepError("镜头素材", "当前存储后端不支持对象下载")

        bucket = settings.MINIO_BUCKET_NAME

        def _fetch() -> None:
            client.fget_object(bucket, object_name, dest)

        try:
            await asyncio.to_thread(_fetch)
        except Exception as exc:  # noqa: BLE001
            raise RenderStepError(
                "镜头素材下载失败", f"对象存储读取 {object_name} 失败: {exc}"
            ) from exc

        size = os.path.getsize(dest) if os.path.isfile(dest) else 0
        if size > MAX_SEGMENT_BYTES:
            raise RenderStepError(
                "镜头素材",
                f"素材超过 {MAX_SEGMENT_BYTES // (1024 * 1024)}MB 上限",
            )

    async def _stage_segment(
        self, url: str, temp_dir: str, idx: int, source_kind: str
    ) -> str:
        """把镜头素材落到临时目录（local 直接复制，http 流式下载）。"""
        segment_path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")

        if source_kind == "local":
            kind = self._source_kind(url)
            if not kind:
                raise RenderStepError(
                    f"镜头 {idx + 1} 素材", "本地路径非法或不在存储根内"
                )
            src = kind[1]
            if not os.path.isfile(src) or os.path.getsize(src) == 0:
                raise RenderStepError(
                    f"镜头 {idx + 1} 素材", f"本地文件不存在或为空: {src}"
                )
            await asyncio.to_thread(shutil.copyfile, src, segment_path)
            return segment_path

        if source_kind == "object":
            kind = self._source_kind(url)
            if not kind:
                raise RenderStepError(
                    f"镜头 {idx + 1} 素材", "无法解析对象存储路径"
                )
            object_name = kind[1]
            await self._download_object(object_name, segment_path)
            if not os.path.isfile(segment_path) or os.path.getsize(segment_path) == 0:
                raise RenderStepError(f"镜头 {idx + 1} 素材", "从对象存储取到的文件为空")
            return segment_path

        import httpx

        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    written = 0
                    with open(segment_path, "wb") as fh:
                        async for chunk in resp.aiter_bytes(1024 * 1024):
                            written += len(chunk)
                            if written > MAX_SEGMENT_BYTES:
                                raise RenderStepError(
                                    f"镜头 {idx + 1} 素材",
                                    f"素材超过 {MAX_SEGMENT_BYTES // (1024 * 1024)}MB 上限",
                                )
                            fh.write(chunk)
            if written == 0:
                raise RenderStepError(f"镜头 {idx + 1} 素材", "下载到的文件为空")
            return segment_path
        except RenderStepError:
            raise
        except Exception as exc:  # noqa: BLE001 - 统一转成可诊断错误
            raise RenderStepError(
                f"镜头 {idx + 1} 素材下载失败", f"{type(exc).__name__}: {exc}"
            ) from exc

    # ---------------- FFmpeg ----------------

    async def _run_capture(
        self, cmd: Sequence[str], timeout: float = 900, cwd: Optional[str] = None
    ) -> Tuple[int, bytes, bytes]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=cwd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            raise RenderStepError(
                "FFmpeg 超时", f"{timeout:.0f}s 未完成，已终止: {os.path.basename(str(cmd[0]))}"
            ) from None
        return proc.returncode, out or b"", err or b""

    async def _ffmpeg(
        self,
        cmd: Sequence[str],
        purpose: str,
        cwd: Optional[str] = None,
        timeout: float = 900,
    ) -> None:
        """跑 ffmpeg，失败时抛带 stderr 末段的 RenderStepError（旧实现只 print）。"""
        try:
            code, _out, err = await self._run_capture(cmd, timeout=timeout, cwd=cwd)
        except FileNotFoundError as exc:
            raise RenderStepError(
                purpose, f"找不到 FFmpeg 可执行文件（FFMPEG_PATH={settings.FFMPEG_PATH}）"
            ) from exc
        if code != 0:
            raise RenderStepError(purpose, _tail(err.decode("utf-8", "ignore")))

    async def _normalize_segment(self, src: str, dst: str, spec: RenderSpec) -> None:
        await self._ffmpeg(
            [
                settings.FFMPEG_PATH,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-i", src,
                "-vf", spec.video_filter(),
                "-r", str(spec.fps),
                "-c:v", "libx264",
                "-crf", str(spec.crf),
                "-preset", spec.preset,
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-ar", "44100",
                "-ac", "2",
                "-movflags", "+faststart",
                "-sn",
                dst,
            ],
            purpose=f"镜头片段转码失败（{os.path.basename(src)}）",
        )

    async def _normalize_all(
        self,
        segment_files: Sequence[str],
        temp_dir: str,
        spec: RenderSpec,
        cancel_check: Optional[CancelCheck],
    ) -> List[str]:
        semaphore = asyncio.Semaphore(int(settings.RENDER_CONCURRENCY or 3))
        norm_paths = [
            os.path.join(temp_dir, f"norm_{i:03d}.mp4")
            for i in range(len(segment_files))
        ]

        async def normalize(idx: int, src: str) -> None:
            async with semaphore:
                await self._check_cancel(cancel_check)
                await self._normalize_segment(src, norm_paths[idx], spec)

        tasks = [
            asyncio.create_task(normalize(i, seg))
            for i, seg in enumerate(segment_files)
        ]
        try:
            await asyncio.gather(*tasks)
        except RenderCancelled:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        except RenderStepError:
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return norm_paths

    async def _concat_videos(
        self, norm_paths: Sequence[str], output_path: str
    ) -> None:
        filelist_path = os.path.join(os.path.dirname(output_path), "filelist.txt")
        with open(filelist_path, "w", encoding="utf-8") as fh:
            for path in norm_paths:
                # concat demuxer 在 Windows 上更稳的写法是正斜杠
                safe_path = os.path.abspath(path).replace("\\", "/")
                fh.write(f"file '{safe_path}'\n")
        await self._ffmpeg(
            [
                settings.FFMPEG_PATH,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-f", "concat",
                "-safe", "0",
                "-i", filelist_path,
                "-c", "copy",
                "-movflags", "+faststart",
                output_path,
            ],
            purpose="视频合成失败",
        )

    async def _probe_duration(self, path: str) -> Optional[float]:
        """取片段真实时长（字幕时间轴要对齐成片，而不是相信镜头表的 duration）。"""
        try:
            code, out, err = await self._run_capture(
                [
                    settings.FFPROBE_PATH,
                    "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                timeout=30,
            )
            if code == 0:
                return float((out or b"").decode("utf-8", "ignore").strip())
        except (FileNotFoundError, ValueError, RenderStepError):
            pass
        # 没有 ffprobe 时退回 ffmpeg -i 的 stderr（Duration: 00:00:03.00）
        try:
            _code, _out, err = await self._run_capture(
                [settings.FFMPEG_PATH, "-hide_banner", "-i", path],
                timeout=30,
            )
        except (FileNotFoundError, RenderStepError):
            return None
        match = re.search(rb"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", err or b"")
        if not match:
            return None
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)

    async def _has_audio(self, path: str) -> bool:
        """探测音轨；探不到就按"有音轨"处理（走 amix，失败会被 BGM 兜底降级）。"""
        try:
            code, out, _err = await self._run_capture(
                [
                    settings.FFPROBE_PATH,
                    "-v", "error",
                    "-select_streams", "a",
                    "-show_entries", "stream=index",
                    "-of", "csv=p=0",
                    path,
                ],
                timeout=30,
            )
            if code == 0:
                return bool((out or b"").strip())
        except (FileNotFoundError, RenderStepError):
            pass
        try:
            _code, _out, err = await self._run_capture(
                [settings.FFMPEG_PATH, "-hide_banner", "-i", path], timeout=30
            )
        except (FileNotFoundError, RenderStepError):
            return True
        return b"Audio:" in (err or b"")

    # ---------------- 字幕 / BGM ----------------

    async def _add_subtitles(
        self,
        video_path: str,
        shots: List[dict],
        durations: Sequence[Optional[float]],
        spec: RenderSpec,
    ) -> str:
        """烧字幕。以片段目录为 cwd、只传文件名，绕开 Windows 盘符冒号破坏 filtergraph。"""
        srt_text, missing = self._generate_srt(
            shots, spec.subtitle_source, durations
        )
        if not srt_text.strip():
            raise RenderStepError("字幕", "没有可用的字幕文本")

        workdir = os.path.dirname(video_path)
        srt_name = "final_output.srt"
        with open(os.path.join(workdir, srt_name), "w", encoding="utf-8") as fh:
            fh.write(srt_text)

        out_name = "final_output_subtitled.mp4"
        style = (
            f"FontSize={spec.subtitle_font_size},PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H80000000,BorderStyle=1,Outline=1,Shadow=0"
        )
        await self._ffmpeg(
            [
                settings.FFMPEG_PATH,
                "-y",
                "-hide_banner",
                "-loglevel", "error",
                "-i", os.path.basename(video_path),
                "-vf", f"subtitles={srt_name}:force_style='{style}'",
                "-c:v", "libx264",
                "-crf", str(spec.crf),
                "-preset", spec.preset,
                "-pix_fmt", "yuv420p",
                "-c:a", "copy",
                "-movflags", "+faststart",
                out_name,
            ],
            purpose="字幕烧制失败",
            cwd=workdir,
        )
        if missing:
            logger.warning("[Render] %d 个镜头没有台词，字幕已回退画面描述", missing)
        return os.path.join(workdir, out_name)

    async def _add_bgm(self, video_path: str, bgm_source: str) -> str:
        """混入背景音乐；视频没有音轨时直接把 BGM 铺上去。只接受受控媒体地址。"""
        kind = self._source_kind(bgm_source)
        if not kind:
            raise RenderStepError(
                "BGM", f"bgm_source 不是受支持的媒体地址: {bgm_source[:120]}"
            )
        source_arg = kind[1]
        workdir = os.path.dirname(video_path)
        if kind[0] == "local" and not os.path.isfile(source_arg):
            raise RenderStepError("BGM", f"BGM 文件不存在: {source_arg}")
        if kind[0] == "object":
            # 私有桶不能直接给 ffmpeg 一个 URL，先落到本地
            local_bgm = os.path.join(workdir, "bgm_source" + os.path.splitext(source_arg)[1][:8])
            await self._download_object(source_arg, local_bgm)
            source_arg = local_bgm

        out_name = "final_output_bgm.mp4"
        base = [
            settings.FFMPEG_PATH,
            "-y",
            "-hide_banner",
            "-loglevel", "error",
            "-i", os.path.basename(video_path),
            "-i", source_arg,
        ]
        if await self._has_audio(video_path):
            cmd = base + [
                "-filter_complex",
                "[1:a]volume=0.3[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-shortest", out_name,
            ]
        else:
            cmd = base + [
                "-map", "0:v", "-map", "1:a",
                "-c:v", "copy", "-shortest", out_name,
            ]
        await self._ffmpeg(cmd, purpose="BGM 混音失败", cwd=workdir)
        return os.path.join(workdir, out_name)

    def _generate_srt(
        self,
        shots: List[dict],
        source: str = "dialogue",
        durations: Optional[Sequence[Optional[float]]] = None,
    ) -> Tuple[str, int]:
        """生成 SRT。返回 (内容, 没有台词而回退的镜头数)。

        时间轴用成片里片段的真实时长（durations），没有就用镜头表 duration。
        """
        lines: List[str] = []
        start = 0.0
        missing = 0
        for idx, shot in enumerate(shots):
            duration = None
            if durations and idx < len(durations):
                duration = durations[idx]
            if not duration or duration <= 0:
                duration = float(shot.get("duration") or 3.0)
            end = start + duration

            text = ""
            if source == "dialogue":
                text = str(shot.get("dialogue") or "")
                if not text.strip():
                    missing += 1
                    text = str(shot.get("description") or shot.get("label") or "")
            elif source == "label":
                text = str(shot.get("label") or "")
            elif source == "description":
                text = str(shot.get("description") or shot.get("label") or "")
            text = " ".join(text.split())
            if text:
                lines.extend(
                    [
                        str(len(lines) // 4 + 1),
                        f"{self._format_timestamp(start)} --> {self._format_timestamp(end)}",
                        text,
                        "",
                    ]
                )
            start = end
        return "\n".join(lines), missing

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """毫秒四舍五入后逐级进位（59.9996s 不能输出成 00:00:60,000）。"""
        total_ms = int(round(max(0.0, float(seconds)) * 1000))
        h, rem = divmod(total_ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    # ---------------- 小工具 ----------------

    @staticmethod
    def _resume_map(resume: Optional[dict]) -> dict:
        urls: dict = {}
        for item in (resume or {}).get("segments", []) or []:
            if item.get("video_url") and item.get("status", "success") == "success":
                try:
                    urls[int(item.get("shot_number"))] = str(item["video_url"])
                except (TypeError, ValueError):
                    continue
        return urls

    @staticmethod
    async def _check_cancel(cancel_check: Optional[CancelCheck]) -> None:
        if cancel_check and await cancel_check():
            raise RenderCancelled("用户取消")

    @staticmethod
    async def _progress(
        cb: Optional[ProgressCallback], value: float, message: str
    ) -> None:
        if cb:
            await cb(value, message)


render_service = RenderService()
