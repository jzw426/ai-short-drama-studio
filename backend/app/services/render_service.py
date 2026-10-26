import asyncio
import tempfile
import os
from typing import Optional, List

from app.core.config import settings
from app.services.ai_service import ai_service
from app.services.storage_service import storage_service


class RenderService:
    """
    渲染编排服务
    负责协调 AI 视频生成、素材合成、字幕添加等渲染流程
    """

    async def execute_render(
        self,
        task_id: str,
        project_id: str,
        config: dict,
        progress_callback=None,
    ) -> dict:
        """
        执行完整的渲染流程：
        1. 收集分镜镜头信息
        2. 调用 Seedance API 逐个生成视频片段
        3. 使用 FFmpeg 合成最终视频
        4. 添加字幕和背景音乐
        5. 上传到 MinIO
        """
        results = {"segments": [], "errors": []}

        # Step 1: 获取镜头列表
        if progress_callback:
            await progress_callback(0.05, "收集分镜数据...")

        # 直接查询数据库获取镜头，避免容器内 localhost 自调用失效
        from sqlalchemy import select
        from app.core.database import async_session
        from app.models.storyboard import Storyboard, Shot

        shots = []
        try:
            async with async_session() as session:
                sb_result = await session.execute(
                    select(Storyboard).where(Storyboard.project_id == project_id)
                )
                storyboard = sb_result.scalar_one_or_none()
                if storyboard:
                    shot_result = await session.execute(
                        select(Shot)
                        .where(Shot.storyboard_id == storyboard.id)
                        .order_by(Shot.sort_order)
                    )
                    shots = [
                        {
                            "shot_number": s.shot_number,
                            "label": s.label,
                            "description": s.description,
                            "duration": s.duration,
                            "scene_ref": s.scene_ref,
                            "character_refs": s.character_refs or [],
                        }
                        for s in shot_result.scalars().all()
                    ]
        except Exception as e:
            results["errors"].append(f"获取分镜数据失败: {str(e)}")

        if not shots:
            results["errors"].append("没有可渲染的镜头")
            return results

        # Step 2: 并发渲染镜头（Semaphore 限流，避免 API 限流/内存暴涨）
        total_shots = len(shots)
        temp_dir = tempfile.mkdtemp(prefix="render_")
        segment_files: List[str] = []
        # 并发度：与 AI 视频 API 的并发上限对齐
        semaphore = asyncio.Semaphore(getattr(settings, "RENDER_CONCURRENCY", 3))

        async def render_one(idx: int, shot: dict) -> dict:
            async with semaphore:
                progress = 0.1 + (0.7 * idx / total_shots)
                if progress_callback:
                    await progress_callback(
                        progress,
                        f"渲染镜头 {idx + 1}/{total_shots}: {shot.get('label', '')}",
                    )
                try:
                    # 调用 Agnes 生成视频
                    video_url = await ai_service.generate_video(
                        prompt=shot.get("description", ""),
                        duration=shot.get("duration", 3.0),
                    )
                    if video_url:
                        # 下载生成的视频片段到临时目录
                        segment_path = await self._download_segment(
                            video_url, temp_dir, idx
                        )
                        if segment_path:
                            return {
                                "ok": True,
                                "shot_number": shot.get("shot_number", idx + 1),
                                "label": shot.get("label", ""),
                                "video_url": video_url,
                                "segment_path": segment_path,
                            }
                    return {
                        "ok": False,
                        "shot_number": shot.get("shot_number", idx + 1),
                        "label": shot.get("label", ""),
                        "error": "视频生成失败",
                    }
                except Exception as e:
                    return {
                        "ok": False,
                        "shot_number": shot.get("shot_number", idx + 1),
                        "label": shot.get("label", ""),
                        "error": str(e),
                    }

        results_list = await asyncio.gather(
            *[render_one(idx, shot) for idx, shot in enumerate(shots)]
        )
        for r in results_list:
            if r["ok"]:
                segment_files.append(r["segment_path"])
                results["segments"].append(
                    {
                        "shot_number": r["shot_number"],
                        "label": r["label"],
                        "video_url": r["video_url"],
                        "status": "success",
                    }
                )
            else:
                results["errors"].append(
                    f"镜头 {r['shot_number']} 渲染失败: {r['error']}"
                )
                results["segments"].append(
                    {
                        "shot_number": r["shot_number"],
                        "label": r["label"],
                        "status": "failed",
                        "error": r["error"],
                    }
                )

        # Step 3: FFmpeg 合成
        if segment_files:
            if progress_callback:
                await progress_callback(0.85, "合成视频片段...")

            output_path = os.path.join(temp_dir, "final_output.mp4")

            if await self._concat_videos(segment_files, output_path):
                # 添加字幕
                if config.get("add_subtitles"):
                    if progress_callback:
                        await progress_callback(0.92, "添加字幕...")
                    output_path = await self._add_subtitles(output_path, shots)

                # 添加背景音乐
                if config.get("add_bgm") and config.get("bgm_source"):
                    if progress_callback:
                        await progress_callback(0.95, "添加背景音乐...")
                    output_path = await self._add_bgm(output_path, config.get("bgm_source"))

                # Step 4: 上传到 MinIO
                if progress_callback:
                    await progress_callback(0.98, "上传到存储...")

                object_name = f"renders/{project_id}/{task_id}/output.mp4"
                with open(output_path, "rb") as f:
                    data = f.read()

                output_url = await storage_service.upload_file(
                    object_name=object_name,
                    data=data,
                    content_type="video/mp4",
                    size=len(data),
                )

                results["output_url"] = output_url
                results["status"] = "completed"

        # 清理临时文件
        try:
            for f in segment_files:
                if os.path.exists(f):
                    os.remove(f)
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except Exception:
            pass

        return results

    async def _download_segment(self, url: str, temp_dir: str, idx: int) -> Optional[str]:
        """下载视频片段到临时目录"""
        import httpx
        segment_path = os.path.join(temp_dir, f"segment_{idx:03d}.mp4")
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=120)
                resp.raise_for_status()
                with open(segment_path, "wb") as f:
                    f.write(resp.content)
                return segment_path
        except Exception as e:
            print(f"[Render] Failed to download segment: {e}")
            return None

    async def _run_ffmpeg(self, cmd: list) -> bool:
        """异步执行 FFmpeg 命令（避免阻塞事件循环）"""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                print(
                    f"[Render] FFmpeg failed: {stderr.decode(errors='ignore')[-500:]}"
                )
                return False
            return True
        except Exception as e:
            print(f"[Render] FFmpeg error: {e}")
            return False

    async def _normalize_segment(self, src: str, dst: str) -> bool:
        """将视频片段归一化为统一编码（H.264/yuv420p/24fps/AAC），保证 concat 兼容"""
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", src,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-r", "24",
            "-c:a", "aac",
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            dst,
        ]
        return await self._run_ffmpeg(cmd)

    async def _concat_videos(self, segment_files: List[str], output_path: str) -> bool:
        """使用 FFmpeg 拼接视频片段（拼接前统一转码，避免编码不一致导致花屏/失败）"""
        temp_dir = os.path.dirname(output_path)
        normalized_files: List[str] = []
        try:
            # 1. 统一转码所有片段
            for idx, seg in enumerate(segment_files):
                norm_path = os.path.join(temp_dir, f"norm_{idx:03d}.mp4")
                if await self._normalize_segment(seg, norm_path):
                    normalized_files.append(norm_path)
                else:
                    print(f"[Render] Segment {idx} normalize failed: {seg}")
                    return False

            if not normalized_files:
                return False

            # 2. concat 拼接（编码已一致，可安全 -c copy）
            filelist_path = os.path.join(temp_dir, "filelist.txt")
            with open(filelist_path, "w") as f:
                for seg in normalized_files:
                    f.write(f"file '{seg}'\n")

            cmd = [
                settings.FFMPEG_PATH,
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", filelist_path,
                "-c", "copy",
                output_path,
            ]
            ok = await self._run_ffmpeg(cmd)
            return ok and os.path.exists(output_path)
        except Exception as e:
            print(f"[Render] Video concat error: {e}")
            return False

    async def _add_subtitles(self, video_path: str, shots: list) -> str:
        """使用 FFmpeg 添加字幕"""
        # 生成 SRT 字幕文件
        srt_path = video_path.replace(".mp4", ".srt")
        srt_content = self._generate_srt(shots)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        output_path = video_path.replace(".mp4", "_subtitled.mp4")
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", video_path,
            "-vf", f"subtitles={srt_path}:force_style='FontSize=24,PrimaryColour=&H00FFFFFF'",
            "-c:a", "copy",
            output_path,
        ]
        if await self._run_ffmpeg(cmd):
            return output_path
        return video_path

    async def _add_bgm(self, video_path: str, bgm_source: str) -> str:
        """使用 FFmpeg 添加背景音乐"""
        output_path = video_path.replace(".mp4", "_bgm.mp4")
        cmd = [
            settings.FFMPEG_PATH,
            "-y",
            "-i", video_path,
            "-i", bgm_source,
            "-filter_complex",
            "[1:a]volume=0.3[bgm];[0:a][bgm]amix=inputs=2:duration=first",
            "-c:v", "copy",
            output_path,
        ]
        if await self._run_ffmpeg(cmd):
            return output_path
        return video_path

    def _generate_srt(self, shots: list) -> str:
        """从镜头数据生成 SRT 字幕"""
        srt_lines = []
        start_time = 0.0

        for idx, shot in enumerate(shots):
            duration = shot.get("duration", 3.0)
            end_time = start_time + duration

            start_ts = self._format_timestamp(start_time)
            end_ts = self._format_timestamp(end_time)

            srt_lines.append(str(idx + 1))
            srt_lines.append(f"{start_ts} --> {end_ts}")
            srt_lines.append(shot.get("description", shot.get("label", "")))
            srt_lines.append("")

            start_time = end_time

        return "\n".join(srt_lines)

    @staticmethod
    def _format_timestamp(seconds: float) -> str:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


render_service = RenderService()
