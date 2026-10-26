"""渲染编排服务。

M1 第二刀改了四件要命的事（每一件都在原实现里真实丢钱或丢文件）：

1. **可取消**：`cancel_check` 在每个 AI 调用/FFmpeg/上传之前检查，配合任务表的
   `cancel_requested` 标志。原实现只 revoke Celery 任务，正在跑的 AI 生成不会停，
   取消之后还在继续烧钱，甚至会把状态写回 completed。
2. **断点续渲**：`resume` 传入上次已生成的片段 URL，重试时直接复用、不再调 AI。
   原实现 retry 从 Step 1 重来，最坏 3 倍成本。
3. **临时目录必清**：整段包 try/finally + `shutil.rmtree(ignore_errors=True)`。
   原实现只删 segment 文件再 `os.rmdir`，目录里还有 final_output/srt/norm_* 必然失败，
   每个任务在磁盘上永久留一份视频。
4. **不吃内存**：上传改 `upload_from_path`（流式），下载改 `client.stream` 分块落盘。
   原实现 `f.read()` 整段视频进内存、`resp.content` 整段片段进内存。
"""
import asyncio
import os
import shutil
import tempfile
from typing import Awaitable, Callable, List, Optional

from app.core.config import settings
from app.services.ai_service import ai_service
from app.services.storage_service import storage_service

ProgressCallback = Callable[[float, str], Awaitable[None]]
CancelCheck = Callable[[], Awaitable[bool]]
CheckpointCallback = Callable[[dict], Awaitable[None]]


class RenderCancelled(Exception):
    """用户取消渲染（协作式检查点触发，不是错误）。"""


class RenderService:
    """渲染编排：收集分镜 → 逐镜生成 → 合成 → 字幕/BGM → 上传。"""

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
        config = config or {}
        results: dict = {"segments": [], "errors": []}

        await self._progress(progress_callback, 0.05, "收集分镜数据...")
        await self._check_cancel(cancel_check)

        shots = await self._load_shots(project_id)
        if not shots:
            results["errors"].append("没有可渲染的镜头")
            return results

        total_shots = len(shots)
        resume_urls = self._resume_map(resume)
        if resume_urls:
            await self._progress(
                progress_callback, 0.08, f"断点续渲：复用 {len(resume_urls)} 个已生成片段"
            )

        temp_dir = tempfile.mkdtemp(prefix="render_")
        try:
            segments = await self._render_segments(
                shots, temp_dir, config, progress_callback, cancel_check, resume_urls
            )
            results["segments"] = segments
            results["errors"].extend(
                f"镜头 {s['shot_number']} 渲染失败: {s.get('error')}"
                for s in segments
                if s.get("status") != "success"
            )

            if checkpoint_cb:
                # 先把"AI 已经花过钱"的产物落库，之后无论失败多少次都不再重复生成
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

            segment_files = [s["segment_path"] for s in segments if s.get("segment_path")]
            if not segment_files:
                results["errors"].append("没有任何镜头产出可用片段")
                return results

            await self._check_cancel(cancel_check)
            await self._progress(progress_callback, 0.85, "合成视频片段...")
            output_path = os.path.join(temp_dir, "final_output.mp4")
            if not await self._concat_videos(segment_files, output_path, cancel_check):
                results["errors"].append("视频合成失败")
                return results

            if config.get("add_subtitles"):
                await self._check_cancel(cancel_check)
                await self._progress(progress_callback, 0.92, "添加字幕...")
                output_path = await self._add_subtitles(
                    output_path, shots, source=config.get("subtitle_source", "description")
                )

            if config.get("add_bgm") and config.get("bgm_source"):
                await self._check_cancel(cancel_check)
                await self._progress(progress_callback, 0.95, "添加背景音乐...")
                output_path = await self._add_bgm(output_path, str(config["bgm_source"]))

            await self._check_cancel(cancel_check)
            await self._progress(progress_callback, 0.98, "上传到存储...")
            object_name = f"renders/{project_id}/{task_id}/output.mp4"
            output_url = await storage_service.upload_from_path(
                object_name=object_name,
                src_path=output_path,
                content_type="video/mp4",
            )
            results["output_url"] = output_url
            results["status"] = "completed"
            return results
        finally:
            # 原实现这里必然失败：目录里还留着 final_output/norm_*/srt/_subtitled/_bgm
            shutil.rmtree(temp_dir, ignore_errors=True)

    # ---------- 内部步骤 ----------

    async def _load_shots(self, project_id: str) -> List[dict]:
        from sqlalchemy import select

        from app.core.database import async_session
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
                    await session.execute(
                        select(Shot)
                        .where(Shot.storyboard_id == sb.id)
                        .order_by(Shot.sort_order)
                    )
                ).scalars().all()
                return [
                    {
                        "shot_number": s.shot_number,
                        "label": s.label,
                        "description": s.description,
                        "duration": s.duration,
                        "scene_ref": s.scene_ref,
                        "character_refs": s.character_refs or [],
                    }
                    for s in rows
                ]
        except Exception as exc:  # 查询失败等价于没镜头，由上层报错
            print(f"[Render] 读取分镜失败: {exc}")
            return []

    async def _render_segments(
        self,
        shots: List[dict],
        temp_dir: str,
        config: dict,
        progress_callback: Optional[ProgressCallback],
        cancel_check: Optional[CancelCheck],
        resume_urls: dict,
    ) -> List[dict]:
        total = len(shots)
        semaphore = asyncio.Semaphore(getattr(settings, "RENDER_CONCURRENCY", 3))
        segments: List[dict] = [None] * total  # type: ignore[list-item]

        async def render_one(idx: int, shot: dict) -> dict:
            async with semaphore:
                await self._check_cancel(cancel_check)
                shot_number = shot.get("shot_number", idx + 1)
                if progress_callback:
                    await progress_callback(
                        0.1 + (0.7 * idx / max(total, 1)),
                        f"渲染镜头 {idx + 1}/{total}: {shot.get('label', '')}",
                    )
                try:
                    video_url = resume_urls.get(int(shot_number or 0))
                    if not video_url:
                        video_url = await ai_service.generate_video(
                            prompt=shot.get("description", ""),
                            duration=shot.get("duration", 3.0),
                        )
                    if not video_url:
                        return {"ok": False, "shot_number": shot_number,
                                "label": shot.get("label", ""), "error": "视频生成失败"}
                    segment_path = await self._download_segment(str(video_url), temp_dir, idx)
                    if not segment_path:
                        return {"ok": False, "shot_number": shot_number,
                                "label": shot.get("label", ""), "error": "片段下载失败"}
                    return {"ok": True, "shot_number": shot_number,
                            "label": shot.get("label", ""), "video_url": str(video_url),
                            "segment_path": segment_path}
                except RenderCancelled:
                    raise
                except Exception as exc:
                    return {"ok": False, "shot_number": shot_number,
                            "label": shot.get("label", ""), "error": str(exc)}

        # 用 create_task 而不用裸 gather：gather 遇到第一个异常只负责抛出，
        # 其余协程会继续跑到自然结束（取消后 AI 仍在烧钱）。这里显式 cancel。
        tasks = [asyncio.create_task(render_one(idx, shot)) for idx, shot in enumerate(shots)]
        try:
            gathered = await asyncio.gather(*tasks)
        except RenderCancelled:
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
                "segment_path": res.get("segment_path"),
                "error": res.get("error"),
            }
        return segments

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
    async def _progress(cb: Optional[ProgressCallback], value: float, message: str) -> None:
        if cb:
            await cb(value, message)

    async def _download_segment(self, url: str, temp_dir: str, idx: int) -> Optional[str]:
        """流式下载片段到磁盘（原实现把整个片段读进内存）。"""
        import httpx

        segment_path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        try:
            async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
                async with client.stream("GET", url) as resp:
                    resp.raise_for_status()
                    with open(segment_path, "wb") as fh:
                        async for chunk in resp.aiter_bytes(1024 * 1024):
                            fh.write(chunk)
            return segment_path
        except Exception as exc:
            print(f"[Render] 片段下载失败: {exc}")
            return None

    async def _run_ffmpeg(self, cmd: list, cwd: Optional[str] = None, timeout: float = 900) -> bool:
        """异步执行 FFmpeg（加超时：原实现遇到坏输入会永久挂住 worker）。"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                _, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                print(f"[Render] FFmpeg 超时({timeout}s)，已终止")
                return False
            if proc.returncode != 0:
                print(f"[Render] FFmpeg 失败: {stderr.decode(errors='ignore')[-500:]}")
                return False
            return True
        except Exception as exc:
            print(f"[Render] FFmpeg 异常: {exc}")
            return False

    async def _normalize_segment(self, src: str, dst: str) -> bool:
        """统一编码（H.264/yuv420p/24fps/AAC），保证 concat 兼容。"""
        return await self._run_ffmpeg(
            [
                settings.FFMPEG_PATH, "-y",
                "-i", src,
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
                "-c:a", "aac", "-ar", "44100", "-ac", "2",
                "-movflags", "+faststart",
                dst,
            ]
        )

    async def _concat_videos(
        self,
        segment_files: List[str],
        output_path: str,
        cancel_check: Optional[CancelCheck] = None,
    ) -> bool:
        """归一化后 concat。归一化改为有界并发（原实现串行 N 次转码，长任务必超时）。"""
        temp_dir = os.path.dirname(output_path)
        norm_paths = [os.path.join(temp_dir, f"norm_{i:03d}.mp4") for i in range(len(segment_files))]
        semaphore = asyncio.Semaphore(3)

        async def normalize(idx: int, src: str) -> bool:
            async with semaphore:
                await self._check_cancel(cancel_check)
                return await self._normalize_segment(src, norm_paths[idx])

        oks = await asyncio.gather(
            *[normalize(i, seg) for i, seg in enumerate(segment_files)]
        )
        failed = [segment_files[i] for i, ok in enumerate(oks) if not ok]
        if failed:
            print(f"[Render] 有 {len(failed)} 个片段归一化失败，放弃合成")
            return False

        filelist_path = os.path.join(temp_dir, "filelist.txt")
        with open(filelist_path, "w", encoding="utf-8") as fh:
            for path in norm_paths:
                fh.write(f"file '{path}'\n")

        await self._check_cancel(cancel_check)
        ok = await self._run_ffmpeg(
            [
                settings.FFMPEG_PATH, "-y",
                "-f", "concat", "-safe", "0",
                "-i", filelist_path,
                "-c", "copy",
                output_path,
            ]
        )
        return ok and os.path.exists(output_path)

    async def _add_subtitles(self, video_path: str, shots: list, source: str = "description") -> str:
        """烧字幕。

        Windows 盘符冒号会破坏 filtergraph 的 `subtitles=路径` 参数（原实现必然静默失败
        并返回未加字幕的视频）。这里改为以片段目录为 cwd、只传文件名，彻底绕开路径转义。
        """
        if source == "none":
            return video_path
        workdir = os.path.dirname(video_path)
        srt_name = "final_output.srt"
        srt_path = os.path.join(workdir, srt_name)
        with open(srt_path, "w", encoding="utf-8") as fh:
            fh.write(self._generate_srt(shots, source=source))

        out_name = "final_output_subtitled.mp4"
        ok = await self._run_ffmpeg(
            [
                settings.FFMPEG_PATH, "-y",
                "-i", os.path.basename(video_path),
                "-vf", f"subtitles={srt_name}:force_style='FontSize=24,PrimaryColour=&H00FFFFFF'",
                "-c:a", "copy",
                out_name,
            ],
            cwd=workdir,
        )
        if not ok:
            print("[Render] 字幕烧制失败，返回无字幕版本")
            return video_path
        return os.path.join(workdir, out_name)

    async def _has_audio(self, path: str) -> bool:
        try:
            proc = await asyncio.create_subprocess_exec(
                settings.FFPROBE_PATH, "-v", "error", "-select_streams", "a",
                "-show_entries", "stream=index", "-of", "csv=p=0", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            out, _ = await proc.communicate()
            return bool(out.strip())
        except Exception:
            return True  # 探测不了就按有音轨处理，走原来的 amix 路径

    async def _add_bgm(self, video_path: str, bgm_source: str) -> str:
        """混入背景音乐；视频没有音轨时改为直接把 BGM 铺上去（原实现必然失败且静默）。"""
        workdir = os.path.dirname(video_path)
        out_name = "final_output_bgm.mp4"
        base = [settings.FFMPEG_PATH, "-y", "-i", os.path.basename(video_path), "-i", bgm_source]

        if await self._has_audio(video_path):
            cmd = base + [
                "-filter_complex",
                "[1:a]volume=0.3[bgm];[0:a][bgm]amix=inputs=2:duration=first[aout]",
                "-map", "0:v", "-map", "[aout]",
                "-c:v", "copy", "-shortest", out_name,
            ]
        else:
            cmd = base + ["-map", "0:v", "-map", "1:a", "-c:v", "copy", "-shortest", out_name]

        if await self._run_ffmpeg(cmd, cwd=workdir):
            return os.path.join(workdir, out_name)
        print("[Render] BGM 混音失败，返回无 BGM 版本")
        return video_path

    def _generate_srt(self, shots: list, source: str = "description") -> str:
        """生成 SRT。

        注意：`description` 是画面描述，当台词烧进画面在语义上是错的（这是原实现的
        既有行为，M1 第二刀改为可配置，默认保持兼容）。正确做法是等剧本场次里的
        台词字段接入后按 dialogue 生成。
        """
        lines: List[str] = []
        start = 0.0
        for idx, shot in enumerate(shots):
            duration = float(shot.get("duration") or 3.0)
            end = start + duration
            text = ""
            if source == "label":
                text = str(shot.get("label") or "")
            elif source == "description":
                text = str(shot.get("description") or shot.get("label") or "")
            text = " ".join(text.split())  # SRT 一条字幕不能带换行
            if text:
                lines.extend([
                    str(idx + 1),
                    f"{self._format_timestamp(start)} --> {self._format_timestamp(end)}",
                    text,
                    "",
                ])
            start = end
        return "\n".join(lines)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        """毫秒四舍五入后逐级进位（原来只处理了 ms==1000，59.9996s 会输出 00:00:60,000）。"""
        total_ms = int(round(max(0.0, float(seconds)) * 1000))
        h, rem = divmod(total_ms, 3_600_000)
        m, rem = divmod(rem, 60_000)
        s, ms = divmod(rem, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


render_service = RenderService()
